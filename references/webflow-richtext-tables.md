# Webflow CMS RichText: Tables via API

## The short answer

Webflow's RichText field accepts raw HTML strings. Tables work. Pass a `<table>` block inside the RichText field string. No special wrapper, no Webflow-specific class, no tricks.

## What works

```html
<table>
  <thead>
    <tr><th>Col A</th><th>Col B</th><th>Col C</th></tr>
  </thead>
  <tbody>
    <tr><td>row 1a</td><td>row 1b</td><td>row 1c</td></tr>
    <tr><td>row 2a</td><td>row 2b</td><td>row 2c</td></tr>
  </tbody>
</table>
```

Pass that as part of the `fieldData["article-text"]` string when calling `create_collection_items` or `update_collection_items` via the Webflow Data API or MCP tool.

## Exact API call pattern

```json
{
  "collection_id": "YOUR_COLLECTION_ID",
  "request": {
    "isDraft": true,
    "fieldData": [{
      "name": "Article title",
      "slug": "article-slug",
      "article-text": "<p>Intro paragraph.</p><table><thead><tr><th>Slug</th><th>Field</th><th>Alt text</th><th>Chars</th></tr></thead><tbody><tr><td>dydx</td><td>main-image</td><td>dYdX homepage hero with headline</td><td>83</td></tr></tbody></table><p>More content after table.</p>"
    }]
  }
}
```

## Rules that matter

1. **Single string only.** The entire RichText value is one HTML string. Tables sit inline with `<p>`, `<h2>`, `<ul>`, `<pre>` — no nesting issues.
2. **Escape quotes inside attribute values.** If your HTML has `href="..."` or `<code>` with quotes, escape them as `\"` in the JSON string.
3. **No `<figure>` wrapper needed.** Plain `<table>` works. Webflow renders it.
4. **`<thead>` is optional but recommended.** Without `<thead>`, Webflow still renders the table — it just won't bold the header row in some themes.
5. **No inline styles needed.** Webflow applies your site's table styles automatically. Don't add `style=""` attributes.
6. **Run through `compact.py`.** Like all RichText HTML, table markup should go through `compact.py` to strip whitespace between tags before pushing.

## What other agents get wrong

- **Wrapping in `<figure class="w-richtext-figure-type-table">`** — unnecessary, sometimes breaks rendering.
- **Using markdown table syntax (`| col | col |`)** — does NOT work in RichText fields. Must be HTML.
- **Putting the table in a separate API call or field** — not needed. It goes inline in the same RichText string.
- **Double-escaping HTML entities** — `&amp;amp;` instead of `&amp;`. Encode once.
- **Claiming tables are impossible or get stripped** — this is wrong. HTML `<table>` works. Markdown tables don't.

## Verified

Tested on Karpi Studio blog collection `67756fb6c22d9437aa3af048`.  
Article: `webflow-multi-image-alt-text-claude` — table renders live.
