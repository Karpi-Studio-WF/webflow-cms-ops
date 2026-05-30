# Webflow CMS RichText: Tables via API

## The short answer

A table renders correctly in Webflow RichText only when **two** things are true: it sits inside a Rich Text HTML-Embed wrapper (so the markup survives intact), and the site has CSS that targets it (so it isn't unstyled).

A bare `<table>` pushed straight into a RichText field is unreliable. In older cases Webflow flattened the grid into a run-on paragraph; in the current blog collection the grid **survives** ingest but renders with **no styling**, so the live page looks broken either way. The API GET echoes your markup back intact in both cases, so the breakage is invisible to automated checks — you only see it on the rendered page (the "API lies" trap, `webflow-gotchas.md` #7).

The fix:

1. Wrap every table in `<div data-rt-embed-type="true">...</div>`. Contents inside the embed are stored and rendered raw (passthrough), so the table structure is preserved verbatim.
2. Style it with one site-wide CSS rule scoped to your rich-text wrapper, targeting the bare `table` / `th` / `td` tags. **Tables carry no class** — the CSS hooks the tags, not a per-table class.

## What works

```html
<div data-rt-embed-type="true">
<table>
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

Pass that as part of the RichText field string when calling `create_collection_items` or `update_collection_items` via the Webflow Data API or MCP tool. No class on the `<table>`; styling comes from the site CSS below.

## What does NOT work

```html
<!-- (a) Bare table, no embed wrapper. Unreliable: the grid has been observed to
        flatten to a run-on paragraph, and where it survives it renders unstyled.
        Either way the live page looks broken. -->
<table>
  <thead><tr><th>Col A</th><th>Col B</th></tr></thead>
  <tbody><tr><td>row 1a</td><td>row 1b</td></tr></tbody>
</table>
```

```html
<!-- (b) Correctly embed-wrapped, but the site has no CSS targeting tables inside
        the rich-text wrapper. The grid is preserved but renders with browser-default
        (i.e. effectively no) styling — the "looks like shit on the front end" case. -->
<div data-rt-embed-type="true">
<table><thead><tr><th>Col A</th></tr></thead><tbody><tr><td>row 1a</td></tr></tbody></table>
</div>
```

Both are real failure modes. (a) is the structural risk; (b) is the styling risk. You need the wrapper AND the CSS.

## Why the embed wrapper

The `data-rt-embed-type="true"` div is how Webflow serializes a Rich Text HTML-Embed node. Webflow does NOT reparse the contents of an embed; the inner HTML is stored raw and rendered raw. Inside the embed:

- `<table>`, `<thead>`, `<tbody>`, `<tr>`, `<th>`, `<td>` all survive verbatim.
- Inline `style="..."` attributes survive.
- HTML comments survive.
- Whitespace and newlines between tags are fine; the whitespace-drop bug (`webflow-gotchas.md` #2) does NOT apply inside an embed.

## Styling

Style tables with **one site-wide rule scoped to your rich-text wrapper, targeting the bare tags**. The tables themselves carry no class. Substitute your own wrapper class for `.rich-text-body` (an example wrapper class — yours will differ; inspect the rendered article to find it):

```html
<!-- Styling tables inside the rich-text blogs -->
<style>
  .rich-text-body table {
    width: 100%;
    border-collapse: collapse;
    margin: var(--size--size-6) 0;
    font-family: var(--text--body);
    font-size: var(--text--sm);
    line-height: var(--text--line-height-base);
  }
  .rich-text-body table thead th {
    text-align: left;
    padding: var(--size--size-3) var(--size--size-4);
    border-bottom: 2px solid var(--_color-primitive---black--900);
    font-weight: 500;
    color: var(--_color-primitive---black--900);
  }
  .rich-text-body table tbody td {
    padding: var(--size--size-3) var(--size--size-4);
    border-bottom: 1px solid var(--_color-primitive---grey--600_a50);
    color: var(--_color-primitive---grey--800);
  }
  .rich-text-body table tbody tr:last-child td {
    border-bottom: none;
  }
  .rich-text-body table tbody tr:hover {
    background: rgba(0, 0, 0, 0.02);
  }
  /* Emphasize the first column structurally — no class needed */
  .rich-text-body table tbody td:first-child {
    color: var(--_color-primitive---black--900);
    font-weight: 500;
  }
  .rich-text-body table a {
    color: var(--_color-primitive---black--700);
    text-decoration: underline;
  }
  /* Optional additive helpers — applied to specific cells/rows when wanted.
     They enhance when present and degrade silently when absent, so a class-less
     table never breaks; it just renders without the accent. */
  .rich-text-body table .cell-highlight {
    color: var(--_color-primitive---black--900);
    font-weight: 500;
  }
  .rich-text-body table .row-total td {
    border-top: 2px solid var(--_color-primitive---black--900);
  }
</style>
```

Notes:

- The `var(--...)` values are the site's design tokens. Substitute your own tokens or literal values.
- **Structural selectors do the per-column / per-row work.** `td:first-child` emphasizes the first column on every table with no class; `tr:last-child td` removes the last row's border. This is why tables need no class.
- **`.cell-highlight` and `.row-total` are optional.** Keep them if you want to accent a specific cell or mark a totals row that structure alone can't identify. A table without them simply renders without that accent — nothing breaks. Do not require them.
- The same wrapper-scoped approach styles code blocks. Target `.rich-text-body pre` / `… pre code` (and, if a line-number highlighter is wired up, `… pre .hljs-ln` etc.) the same way.

## Migrating from the old class-based approach

If your site still styles tables via a per-table class like `.legacy-table-class` (a class on every `<table>`), the move is to class-less tables + the tag-scoped CSS above. **Sequence it carefully:** the tag-scoped rule must be live *before* you strip `legacy-table-class` from the tables, or the already-correct tables go unstyled in the gap.

1. Add the `.rich-text-body table { … }` rule to the site (it can coexist with the existing `.legacy-table-class` rule).
2. Verify a published page still renders tables correctly with both rules present.
3. Then run a fix pass (`references/fix-pass-pattern.md`) that removes `class="legacy-table-class"` from `<table>` tags across the collection.
4. Remove the now-dead `.legacy-table-class` rule.

## Rules that matter

1. **Wrap every table in the embed, AND make sure the site CSS targets it.** A bare `<table>` renders broken (flattened, or surviving-but-unstyled). The `data-rt-embed-type="true"` wrapper is non-optional, and so is having a CSS rule that styles tables inside the rich-text wrapper.
2. **No class on the `<table>`.** Style via tags scoped to the rich-text wrapper. Reserve classes for optional accents (`.cell-highlight`, `.row-total`) that degrade gracefully.
3. **Single string only.** The entire RichText value is one HTML string. Embed-wrapped tables sit inline with `<p>`, `<h2>`, `<ul>`, `<pre>`; no nesting issues.
4. **Escape quotes inside attribute values.** When the HTML lives inside a JSON request, escape `href="..."` as `href=\"...\"` in the JSON string.
5. **`<thead>` is optional but recommended.** Without `<thead>`, the table still renders; header styling may differ.
6. **`compact.py` is fine but not required inside the embed.** Content inside `data-rt-embed-type` is passthrough, so compacting does not change its rendered behavior. Outside the embed, keep using `compact.py` for normal RichText HTML.

## What other agents get wrong

- **Pushing a bare `<table>`** (no embed wrapper). It renders broken on the live page — flattened to a paragraph, or surviving but unstyled. The `data-rt-embed-type` wrapper is required.
- **Wrapping correctly but assuming Webflow styles it.** Webflow applies no useful default styling to a table in rendered rich text. Without a site CSS rule targeting tables inside the rich-text wrapper, an embed-wrapped table still looks broken. This is the regression an earlier version of this skill caused by saying "no class needed, bare `<table>` is the default" — bare tables survived but rendered unstyled.
- **Putting a per-table class back as the styling mechanism.** The class-less + tag-scoped-CSS approach is the standard. A class is only for optional accents that degrade gracefully.
- **Wrapping in `<figure class="w-richtext-figure-type-table">`.** Webflow's Designer uses this figure class internally, but the correct shape for API pushes is the `data-rt-embed-type` embed div.
- **Using markdown table syntax (`| col | col |`).** Markdown pipe tables do NOT work in RichText fields. Convert to HTML inside the embed.
- **Double-escaping HTML entities.** `&amp;amp;` instead of `&amp;`. Encode once.
- **Downgrading to bullet lists every time.** Bullets are a fine fallback when an embed is not a fit, but the embed wrapper handles real tables.

## Verified

- A live blog item with 12 tables, every one wrapped in a `<div data-rt-embed-type="true">` embed: confirms the embed-wrapper requirement against the live Data API. When last checked, those tables still carried a legacy per-table styling class, with the migration to class-less + tag-scoped CSS still pending (see the migration sequence above).
- Elsewhere in the same collection, several other tables are bare — no embed wrapper, no class. Their grid HTML survives in storage but renders unstyled on the live page. These are the "looks broken on the front end" cases this reference exists to prevent.
