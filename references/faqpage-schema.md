# FAQPage Schema via a CMS Field

Use this when articles on a Webflow site carry visible Q&A sections and you want them emitted as `FAQPage` JSON-LD so AI engines (ChatGPT, Perplexity, Bing Copilot, Google AI Overviews) and Google Rich Results can extract each Q&A as a discrete unit.

The pattern generalizes. The same one-CMS-field + one-template-embed shape works for any **secondary JSON-LD block** alongside a page's primary schema: FAQPage, HowTo, Product, Review, BreadcrumbList, and others. FAQPage is the worked example because it's the most common per-article secondary schema across blogs and reference sites.

## The mechanism

A Webflow page can carry multiple `<script type="application/ld+json">` blocks. The site's existing primary schema (BlogPosting, Article, Product, etc.) stays in the template, untouched. The secondary schema (FAQPage) lives in a dedicated CMS field per article and renders into its own separate `<script>` block via a CMS-field binding in the template's custom code. The field holds only the JSON object; the template provides the `<script>` wrapper. Empty field renders an empty `<script>` block (harmless; no schema warning).

This decouples the secondary schema from the primary template. Writers populate one CMS field per article; no Designer touch needed per article after the one-time setup.

## One-time per-client setup (three steps)

This is the part that standardizes across the whole client base. Same three steps for every new client, collection, and secondary schema type.

### Step 1: Create the CMS field

In Webflow Designer, on the target collection (e.g., the blog), add a field:

- **Display name:** `FAQ Schema` (or whatever names the schema type)
- **Slug:** `faq-schema`
- **Type:** PlainText
- **Mode:** multi-line  (important; see gotcha below)
- **Required:** No

**Webflow gotcha:** the Data API creates the field as single-line PlainText and does NOT expose a flag to set multi-line. After creating via API, open the field in Designer and toggle to multi-line by hand. Pasted JSON is unusable in the single-line editing UX.

### Step 2: Wire the template embed

In the collection's page template, add to Page Settings → Custom Code → Inside `<head>` (recommended; can also live as a body Embed component):

```html
<!-- FAQ schema (renders empty when faq-schema field is empty) -->
<script type="application/ld+json">
{{wf {&quot;path&quot;:&quot;faq-schema&quot;,&quot;type&quot;:&quot;PlainText&quot;\} }}
</script>
```

The `{{wf ... }}` token is Webflow's CMS-field binding syntax. When the field is populated, Webflow inlines its content verbatim between the `<script>` tags. When the field is empty, the `<script>` block renders empty — no markup error, no schema warning.

The same template embed is reusable across collections. Other secondary schemas (HowTo, Product) use parallel embeds with different field slugs and JSON shapes.

### Step 3: Republish the site

Once the template embed is live, the field is wired. From now on, populating `faq-schema` on any article injects the JSON-LD on render with no further Designer touch.

## The Q&A source convention (non-negotiable)

Q&As MUST live in the rich text body of the article, in a standardized structure:

- A section headed by `<h2>Frequently Asked Questions</h2>` or `<h2>FAQ</h2>` (match either; case-insensitive).
- Inside that section, each Q&A pair is: one `<h3>` (the question), followed by one or more `<p>` (the answer), continuing until the next `<h3>` or the next `<h2>` (or end of body).

Example:

```html
<h2>Frequently Asked Questions</h2>
<h3>How much does it cost?</h3>
<p>$25/mo annually, $39/mo monthly.</p>
<h3>Is it cheaper than WordPress?</h3>
<p>For most B2B teams over a three-year window, yes.</p>
<p>The hidden costs of WordPress (themes, plugins, maintenance) add up...</p>
```

This is the single source of truth for FAQ content. Benefits:

- Q&As are visible to readers (good UX; good for AI parsers that fall back to body-text extraction even without schema).
- Q&As are extractable by a single consistent rule across every client and every article.
- `name` and `acceptedAnswer.text` are guaranteed 1:1 with what readers see (Google Rich Results requirement).

## Per-article workflow

For each article that needs FAQPage schema:

1. **Extract** Q&A pairs from the body using the convention above.
2. **Build** the FAQPage JSON-LD object (shape below).
3. **PATCH** the `faq-schema` field with the JSON object (no `<script>` tags).
4. **Human publishes** the item from the Webflow Designer.

This is `content-repair-pattern.md` applied across two fields: read from a source field (the body), transform, write to a destination field (`faq-schema`). Use `scripts/repair_template.py` with `SOURCE_FIELD = "body-2"` (or your collection's body slug) and `DEST_FIELD = "faq-schema"`. The transformer is in the worked example below.

## Non-conforming articles: migrate first

If an article's Q&As are NOT in the rich text body (they live in a separate FAQs collection referenced via MultiReference, or in a custom field, or are scattered as components), step zero is a **migration pass** that pulls the Q&As into the body under an FAQ H2.

That migration is itself a `content-repair-pattern.md` pass with its own transformer (read source-of-Q&As → format as `<h3>Q</h3><p>A</p>` blocks → insert under `<h2>Frequently Asked Questions</h2>` in the body). Each client has its own source format; the migration transformer is per-client. Once migrated, the per-article workflow above runs unchanged.

This gives a standardized FAQPage workflow regardless of how a given client's CMS was originally shaped: migrate to convention if needed, then backfill.

## The JSON-LD shape (what the field stores)

The `faq-schema` field stores exactly this object. No `<script>` wrapper. No leading or trailing whitespace.

```json
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {
      "@type": "Question",
      "name": "<visible question text, 1:1>",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "<visible answer text, 1:1>"
      }
    },
    {
      "@type": "Question",
      "name": "...",
      "acceptedAnswer": { "@type": "Answer", "text": "..." }
    }
  ]
}
```

The `mainEntity` array holds one Question object per Q&A pair. The template wraps the whole object in `<script type="application/ld+json">...</script>` on render.

## Non-negotiables

1. **The field stores the JSON object only.** No `<script>` tags inside the field. The template adds them. Pasting `<script>` into the field double-wraps and breaks the JSON-LD block on render.
2. **JSON must be valid.** Straight quotes only (watch for smart/curly quotes that copy in from styled-text editors). Escape inner `"` as `\"`. No trailing commas. No raw `</script>` inside any answer text (escape as `<\/script>` if unavoidable).
3. **`name` and `text` match the visible Q&A 1:1.** Google Rich Results flags mismatches. The body-as-source convention guarantees this when extraction is faithful.
4. **The CMS field is multi-line in Designer.** The API creates it single-line; manual toggle required. Editing JSON in single-line mode is unusable.
5. **Empty field is fine.** Renders an empty `<script>` block — no parser warnings, no schema errors.
6. **The template embed is one-time per collection.** Don't re-add per article or per push.

## Verification

After each push and after the human publishes:

- Run the published URL through [Google Rich Results Test](https://search.google.com/test/rich-results). Confirm FAQPage detection and zero warnings.
- Optionally validate the raw JSON against [Schema.org Validator](https://validator.schema.org/) for stricter spec compliance.
- View source on the published page. Confirm two `<script type="application/ld+json">` blocks: the primary (BlogPosting / Article / etc.) and the FAQPage block with the expected questions.

## Generalization to other secondary JSON-LD

Same one-field + one-template-embed pattern works for any per-article secondary schema. One CMS field, one template embed, one transformer per schema type:

| Schema | Suggested field slug | Body convention | When to use |
|---|---|---|---|
| FAQPage | `faq-schema` | `<h2>FAQ</h2>` section with `<h3>Q</h3><p>A</p>` pairs | Q&A-heavy articles |
| HowTo | `howto-schema` | `<h2>Steps</h2>` with numbered `<h3>` per step + `<p>` body | Step-by-step guides |
| Product | `product-schema` | Product detail collection items | Ecommerce, SaaS comparison pages |
| Review | `review-schema` | `<h2>Review</h2>` with rating + body | Product reviews, case studies |
| BreadcrumbList | `breadcrumb-schema` | Derived from collection hierarchy | Multi-level CMS structures |

For each new schema type: repeat the three-step setup with that schema's field name, write a new transformer (body or source → JSON-LD), use the same `scripts/repair_template.py` harness to push.

## Worked transformer: FAQPage extraction

Sketch of the `transform()` to drop into `scripts/repair_template.py`. Reads body HTML, extracts Q&As under the FAQ H2, returns the FAQPage JSON-LD string. Idempotent: same body in produces same JSON out.

```python
import json
import re
from html import unescape

H2_FAQ   = re.compile(r'<h2[^>]*>\s*(?:Frequently Asked Questions|FAQ)\s*</h2>', re.IGNORECASE)
NEXT_H2  = re.compile(r'<h2[^>]*>', re.IGNORECASE)
H3_OPEN  = re.compile(r'<h3[^>]*>(.*?)</h3>', re.IGNORECASE | re.DOTALL)
P_BLOCK  = re.compile(r'<p[^>]*>(.*?)</p>', re.IGNORECASE | re.DOTALL)
TAGS     = re.compile(r'<[^>]+>')


def _visible(html_fragment: str) -> str:
    """Strip tags, decode entities, collapse whitespace."""
    return re.sub(r'\s+', ' ', unescape(TAGS.sub('', html_fragment))).strip()


def transform(body_html: str) -> str:
    """Extract Q&As from the body's FAQ section, return FAQPage JSON-LD string.
    Returns "" if no FAQ section is found (article doesn't need FAQPage schema)."""
    m_start = H2_FAQ.search(body_html)
    if not m_start:
        return ""

    # FAQ section: from just after the FAQ H2 to the next H2 (or end of body)
    after = body_html[m_start.end():]
    m_next = NEXT_H2.search(after)
    section = after[:m_next.start()] if m_next else after

    # Walk H3 boundaries; each H3 is a question, <p>s until the next H3 are the answer
    questions = []
    h3s = list(H3_OPEN.finditer(section))
    for i, m_h3 in enumerate(h3s):
        q_text = _visible(m_h3.group(1))
        ans_start = m_h3.end()
        ans_end = h3s[i + 1].start() if i + 1 < len(h3s) else len(section)
        answer_html = section[ans_start:ans_end]
        parts = [_visible(m.group(1)) for m in P_BLOCK.finditer(answer_html)]
        a_text = ' '.join(p for p in parts if p)
        if q_text and a_text:
            questions.append({
                "@type": "Question",
                "name": q_text,
                "acceptedAnswer": {"@type": "Answer", "text": a_text},
            })

    if not questions:
        return ""

    return json.dumps({
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": questions,
    }, indent=2, ensure_ascii=False)
```

Drop this into `scripts/repair_template.py` with `SOURCE_FIELD = "body-2"` (or your collection's body slug) and `DEST_FIELD = "faq-schema"`. The harness handles audit, snapshot, diff, stage, structural verify, and resume.

For `structural_markers()` on this transform, count what should appear in the output:

```python
def structural_markers(value: str) -> dict:
    return {
        "question_count": value.count('"@type": "Question"'),
        "answer_count": value.count('"@type": "Answer"'),
        "is_faqpage": int('"@type": "FAQPage"' in value),
    }
```

Empty-string output (article without an FAQ section) is a legitimate no-op result; the harness's "skip if new == dest" check handles it.

## When NOT to use this pattern

- **The primary schema template already includes FAQPage.** Some Webflow site templates inject FAQPage from a different mechanism (a Designer FAQ component, a JSON-LD generator script). Check the rendered HTML first; don't add a second source.
- **The article has no visible FAQ section.** Don't fabricate one for schema; FAQPage on a non-FAQ page is a Rich Results violation.
- **Q&As are dynamic** (user-submitted, paginated, lazy-loaded). FAQPage expects a static list rendered with the initial page response; don't try to inject post-load.
- **One-off FAQ on a single article.** Open in Designer, fill the field by hand; the harness is for batches.
