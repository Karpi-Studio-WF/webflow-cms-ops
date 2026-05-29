# TODO

## Bare `<pre><code>` blocks without a `language-` class (deferred)

Surfaced during the Schema Glossary code-block migration (2026-05). These blocks
are already in `<pre><code>` shape but carry no `language-` class, so highlight.js
does not colorize them. They are NOT the legacy `<p><code>` shape, so the
migration transform never touched them. The legacy migration itself is complete:
0 legacy `<p><code>` remain in either collection.

Eight blocks across the two collections, in two categories.

### 1. Live Webflow field bindings (6, Terms / `body`) — do NOT fix via API

Each is a one-line dynamic binding, e.g.
`"uploadDate": "{{wf {"path":"video-publish-date","type":"PlainText"} }}"`.
The binding's inner quotes are double-encoded (`&amp;quot;`). A body re-push
re-ingests the whole field, and Webflow normalizes encoding on ingest, which
risks corrupting the binding and breaking the dynamic value on the live page.
If you want these highlighted, set the language by hand in the Webflow Designer
(the binding is a native object there), not via the API.

- `schema-glossary-terms/upload-date`
- `schema-glossary-terms/thumbnail-url`
- `schema-glossary-terms/expires`
- `schema-glossary-terms/embed-url`
- `schema-glossary-terms/duration`
- `schema-glossary-terms/content-url`

### 2. Non-code preformatted snippets (2) — leaving bare is defensible

Not real code, so a `language-` class would be a mislabel; plain monospace is fine.

- `schema-glossary-terms/employment-type` : enum list (`FULL_TIME`, `PART_TIME`, ...)
- `schema-glossary-types/restaurant` : type-hierarchy breadcrumb (`Thing > Organization > ... > Restaurant`)

### Decision needed

Leave all 8 as-is (recommended; none are standard highlightable code), or set
classes by hand in the Designer for any you want highlighted. Revisit later.
