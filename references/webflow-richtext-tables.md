# Webflow CMS RichText: Tables via API

## The short answer

Webflow's RichText parser strips bare `<table>` tags on ingest. The cells survive but the grid is gone, so the table renders as a run-on paragraph. The fix: wrap the table in a Rich Text HTML-Embed div, `<div data-rt-embed-type="true">...</div>`. Contents inside the embed are passthrough; the table tags survive verbatim and render normally.

## What works

```html
<div data-rt-embed-type="true">
<table class="your-custom-class">
  <thead>
    <tr><th>Col A</th><th>Col B</th><th>Col C</th></tr>
  </thead>
  <tbody>
    <tr><td>row 1a</td><td>row 1b</td><td>row 1c</td></tr>
    <tr><td>row 2a</td><td>row 2b</td><td>row 2c</td></tr>
  </tbody>
</table>
</div>
```

Pass that as part of the RichText field string when calling `create_collection_items` or `update_collection_items` via the Webflow Data API or MCP tool.

## What does NOT work

```html
<!-- Webflow strips the table grid on ingest; cells render concatenated into a paragraph -->
<table>
  <thead><tr><th>Col A</th><th>Col B</th></tr></thead>
  <tbody><tr><td>row 1a</td><td>row 1b</td></tr></tbody>
</table>
```

This is the failure mode behind the flattened "Choosing your @type" table observed on `schema-glossary-types/organization` before the fix: every `<th>` and `<td>` text concatenated into a single `<p>` with no row or column boundaries.

## Why the embed wrapper

The `data-rt-embed-type="true"` div is how Webflow serializes a Rich Text HTML-Embed node. Webflow does NOT reparse the contents of an embed; the inner HTML is stored raw and rendered raw. Inside the embed:

- `<table>`, `<thead>`, `<tbody>`, `<tr>`, `<th>`, `<td>` all survive verbatim.
- Custom classes survive (e.g., `class="ks-pricing-table"`).
- Inline `style="..."` attributes survive.
- HTML comments survive.
- Whitespace and newlines between tags are fine; the whitespace-drop bug (`webflow-gotchas.md` #2) does NOT apply inside an embed.

## Styling

Webflow does not auto-style raw embed contents. Define site-wide CSS targeting a custom class on `<table>` (e.g., `.ks-pricing-table`); that CSS is what gives the table borders, padding, header backgrounds, etc. Without a custom class plus site CSS, the table renders with browser-default styling.

## Rules that matter

1. **Wrap every table in the embed.** Bare `<table>` is stripped on ingest. The `data-rt-embed-type="true"` wrapper is non-optional.
2. **Single string only.** The entire RichText value is one HTML string. Embed-wrapped tables sit inline with `<p>`, `<h2>`, `<ul>`, `<pre>`; no nesting issues.
3. **Escape quotes inside attribute values.** When the HTML lives inside a JSON request, escape `href="..."` as `href=\"...\"` in the JSON string.
4. **`<thead>` is optional but recommended.** Without `<thead>`, the table still renders; header styling may differ.
5. **`compact.py` is fine but not required inside the embed.** Content inside `data-rt-embed-type` is passthrough, so compacting does not change its rendered behavior. Outside the embed, keep using `compact.py` for normal RichText HTML.

## What other agents get wrong

- **Pushing a bare `<table>`.** It gets stripped; cells render concatenated. The `data-rt-embed-type` wrapper is required.
- **Wrapping in `<figure class="w-richtext-figure-type-table">`.** Webflow's Designer uses this figure class internally, but the correct shape for API pushes is the `data-rt-embed-type` embed div.
- **Using markdown table syntax (`| col | col |`).** Markdown pipe tables do NOT work in RichText fields. Convert to HTML inside the embed.
- **Double-escaping HTML entities.** `&amp;amp;` instead of `&amp;`. Encode once.
- **Downgrading to bullet lists every time.** Bullets are a fine fallback when an embed is not a fit, but the embed wrapper handles real tables.

## Verified

- Karpi Studio blog `/blog/webflow-pricing`: 12 pricing tables, all stored as `<div data-rt-embed-type="true"><table class="ks-pricing-table">...</table></div>` and rendering live.
- `schema-glossary-types/organization`: bare `<table>` was stripped to a flattened paragraph (the failure mode); embed-wrapped replacement preserves the table structure on ingest and was confirmed in the stored HTML after PATCH.
