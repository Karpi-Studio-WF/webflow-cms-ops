# Glossary Pattern: Build a Glossary as a Linked Network (AEO)

Use this when planning, writing, extending or pushing a glossary: a CMS collection where each item defines one term. It works for your own site and for a client's AEO engagement; nothing below is tied to one project. To audit and clean up a glossary that already exists, read `references/glossary-sweep.md`. For the decisions that differ per project (tools, owners, voice, field slugs), copy `references/glossary-positions-template.md` into the project first.

This reference governs **architecture**: which entry owns which concept, what an entry contains, how entries link. It sits between two other layers:

| Layer | Decides | Where it lives |
|---|---|---|
| Architecture | Ownership, entry types, linking, schema | This file |
| Topic and voice | Entry template for the subject, house style, positions | The project's positions file, or a topic skill |
| Mechanics | How content reaches Webflow safely | `push-pattern.md`, `content-repair-pattern.md`, `faqpage-schema.md`, the scripts |

## Why this shape

A glossary is a **network**, not a pile of articles. Each concept lives in exactly one entry. Every other entry that touches the concept links to that home and spends its own words only on what is unique to it.

What that buys, and how sure each claim is:

- **A quotable passage per concept.** Answer engines lift short, self-contained passages. A 40 to 60 word answer block directly under a question H1 is written to be lifted whole. (Design choice based on how answer engines quote; the 40 to 60 range is a working convention, not a published threshold.)
- **One page per query.** Two entries explaining the same thing compete for the same query and split links and relevance between them. (Standard SEO reasoning about cannibalization; not measured here.)
- **One place per fact.** A price, threshold or fix stated in one entry and linked from the rest is updated by editing one page. (Mechanical; certain.)
- **An explicit entity graph.** In-text links and related terms tell crawlers and readers how terms relate: parent, child, synonym, deliberate split.
- **Structured data is hygiene, not the lever.** `DefinedTerm` has no Google rich result. Google has limited FAQ rich results to well-known government and health sites since August 2023. The markup gives machines an unambiguous name, definition and Q&A list; its effect on AI citation is not publicly measured. It is cheap to add (see "Schema"), so add it, but the levers are the four points above.

Where the rules came from: a sweep of a 71-entry CRO glossary found the same platform how-to (Webflow form tracking) written 16 times, entries naming sibling terms 72 times without linking them, 361 of 610 glossary-to-glossary links coming only from the related-terms block, and zero links into the glossary from the rest of the site. None of it was visible from inside any single entry. Every rule below exists to stop one of those.

## The six rules

1. **One home per concept.** Before writing anything about a concept, decide which entry (or which live guide) owns it. Only the owner explains it. Ownership tests are below.
2. **Link the mention, do not re-explain it.** When an entry mentions a sibling term, link the term where it appears. Do not scatter "X is explained in Y" sentences; that meta-sentence belongs only in synonym entries and in an opener where the whole entry builds on another one.
3. **Each entry covers only what is unique to it,** plus one line on how it differs from its nearest sibling (the differs line). A platform-specific entry ("A/B testing on Webflow") does not explain the general method; it links the general entry and covers only what changes on the platform.
4. **Synonyms get short pointer entries.** A synonym with its own search demand gets an entry that catches the query, says it is the same thing as the owner, and routes. It explains nothing itself.
5. **Umbrella entries are signposts.** A parent entry defines the category and routes to its children. Each child opens with "a type of [parent]" (linked) and covers only its own type. The parent owns what is genuinely shared by all children; it never absorbs a child's mechanics.
6. **One story across the site.** Tools, methods and numbers the glossary states must match what the business actually uses and what its live articles say. Record these in the project's positions file and check entries against it.

## Page roles

| Page type | Job | Links to |
|---|---|---|
| Glossary entry | Defines one term, answers "what is X", covers what is unique to X | The owner of every concept it mentions; the parent guide for depth; the service page once |
| Guide / how-to article | Goes deep on method and execution | The glossary entry for every term it uses |
| Service page | Sells | Down to supporting guides and glossary entries |

A glossary entry that starts teaching the full method is competing with the guide. A guide that re-defines terms is competing with the glossary. In both cases, link instead.

## Entry types

Decide the type before outlining.

### 1. Standard entry (most entries)

| Part | Rule | Why |
|---|---|---|
| **Name** (CMS `name`) | The bare term, first letter capitalized: `Rage click`, `CRO audit`. No "What is", no article, no question mark. | Clean listing pages; clean entity name for `DefinedTerm.name`. |
| **H1** (a dedicated field, e.g. `h1-heading`) | The literal question: `What is a rage click?` | Matches how people and answer engines phrase the query. |
| **Slug** | Clean noun: `rage-click`. Never changes after publish. | Every inbound link and the schema `@id` depend on it. Webflow also reserves deleted slugs (`webflow-gotchas.md` #4). |
| **Answer block** | 40 to 60 words, self-contained, complete with no preamble. A child links its parent here ("a type of [heatmap]"). | The passage answer engines quote, and the `DefinedTerm.description`. |
| **Body H2s** | Each H2 is a question a buyer would type, and only a question this entry owns. | If the answer lives in another entry, it is a link, not an H2. |
| **Differs line** | One sentence naming the nearest sibling and the axis of difference: "A scroll map is the visualization; [scroll depth] is the per-session metric it aggregates." | Stops the two entries competing and tells the reader where to go. |
| **Platform section** | Only what is specific to this term on the platform. Shared platform how-tos (install a script, track a form) have one owner; everyone else links it. | Shared how-tos were the most duplicated content in the sweep, repeated in 7 to 16 entries. |
| **Related terms** | 3 to 5 closest siblings, including every deliberate split partner; symmetric for splits and parent/child pairs. | Navigation. The in-text links carry the meaning. |
| **FAQ** | 2 to 3 questions this entry owns, under an `<h2>FAQ</h2>` with one `<h3>` per question. Never a question that is another entry's H2 or another entry's FAQ. | Duplicate FAQs are the easiest duplication to miss. The audit checks both. |
| **Sources** | A primary source for every number. No number without one. | One guessed benchmark copied into five entries is five things to fix. |

### 2. Synonym (pointer) entry

For a term that means the same as an existing entry and has its own search demand (`A/B testing` → `split testing`).

- H1: the question (`What is A/B testing?`).
- Answer block: a one-line definition, then "A/B testing and [split testing] are the same method."
- Body: a short routing list ("For the method, see [split testing]. For Webflow, see [Webflow A/B testing]."), plus one line on the near-siblings that are *not* the same thing, linked.
- No explanation of the method. Short is correct: the entry catches the query and routes it.
- The answer-block length check will flag short synonym entries. That finding is expected; record synonym slugs in the positions file and skip them when reading the audit.

### 3. Umbrella (hub) entry

For a parent concept with several children (website heatmap → click map, scroll map, attention map).

- Defines the category and what the children have in common.
- One short paragraph per child, each linking the child. Never the child's mechanics.
- Owns what is shared by every child (e.g. a sample-size table that applies to all heatmap types), so children link up instead of repeating it.

Do not confuse the umbrella entry with the glossary's index page (the page listing every term). The index page carries the `DefinedTermSet` schema; umbrella entries are ordinary entries.

## Choosing the owner of a concept

When several entries touch the same concept, apply these tests in order:

1. **Is the concept the entry's own term?** Peeking is the core of sequential testing, so sequential testing owns peeking, even though statistical significance mentions it.
2. **Is it category-wide?** It goes to the umbrella.
3. **Is it an implementation fix?** It goes to the entry about that implementation (a form success state that does not load a new page → the event-tracking entry, not every form-related entry).
4. **Is a live guide already the deep version?** The guide owns the depth; the entry defines and links up.
5. **Tie-break:** the entry where a reader searching for that concept would land.

Write the ownership map down (concept | owner | entries that currently re-explain it) before editing anything, and keep it in the positions file. Reviewers will disagree about owners; resolve disagreements with the tests above and record the decision.

## Linking rules

- **Link the mention itself,** inline, the first time the term appears in the body. Not a separate "see also" sentence.
- **One link per target per entry** in body text. Repeating the same link is noise.
- **Anchor text = the term as the reader sees it,** matching the target's name. Stale anchors ("Value proposition clarity" pointing at landing page optimization) mislead readers and dilute the target.
- **Children link parents** in the answer block or first paragraph.
- **Deliberate splits link each other** in text and in related terms, and the differs line names the axis.
- **Related terms are navigation, not a substitute for in-text links.** Every term named in body text is linked where it is named.
- **Direction across the site:** glossary → guide for depth; guide/blog → glossary every time a post uses a defined term (this is where a glossary earns its authority); everything → the service page, once per entry.
- **Link from live posts only after the glossary is live on production.** Check first: `curl -s -o /dev/null -w "%{http_code}" <url>`. A link to a 404 costs more than no link.
- **Hygiene:** no links to slugs that do not exist, to drafts, or to URLs that 301 (link the final URL); no malformed absolute links (`https://glossary/...`), empty anchors, or raw markdown links in rich text. `scripts/audit_glossary.py` checks all of these.

## Writing rules (defaults)

Project voice rules override these; record them in the positions file.

- Reference register: clear, specific, no storytelling, no marketing.
- Never invent a statistic or a source. If support is missing, write a qualitative statement or flag the sentence for verification.
- Meta title: the page-specific title only. Subtract whatever the template appends from the length budget, and never store the appended suffix in the field (`webflow-gotchas.md` #9). Meta description ≤155 characters.

## Recommended CMS fields

| Field | Slug (suggested) | Type | Notes |
|---|---|---|---|
| Name | `name` | PlainText | Bare term. |
| Slug | `slug` | Slug | Never changed after publish. |
| H1 | `h1-heading` | PlainText | The question. The template's H1 binds to this, not to `name`. |
| Answer | `answer` (optional) | PlainText | If present, the template renders it under the H1 and the tools read it; if absent, the tools use the body's first `<p>`. |
| Body | `body` (verify; may be `body-2`) | RichText | Everything after the answer block. |
| Meta title / description | `meta-title`, `meta-description` | PlainText | See writing rules. |
| Related terms | `related-terms` | MultiReference → same collection | 3 to 5 items. |
| Schema | `term-schema` | PlainText, **multi-line** | JSON-LD written by `glossary_schema.py`. The API creates PlainText fields single-line; toggle to multi-line in the Designer (`faqpage-schema.md`). |

Verify the actual slugs on one live item before running anything (`push-pattern.md`, "Before running").

## Workflows

### A. Plan a new glossary

1. **Research the term list:** volume, difficulty, and whether the bare term means something else. A term whose bare form is ambiguous, or owned by a much bigger meaning, is a **rejected head**; record it with the reason.
2. **Cluster** the terms. Pick one umbrella per cluster, mark synonyms, and mark deliberate splits (two entries that must stay separate, each with its axis).
3. **Write the ownership map before the first entry.** Deciding ownership after 70 drafts exist is what creates the duplication.
4. **Fill the positions file** (tools, methods, numbers the glossary will state), and get the owner of the business to confirm it.
5. **Set up the collection** with the fields above, and the template (H1 from `h1-heading`, answer block, related terms, the schema embed below).

### B. Add terms from a keyword list

For each term, decide one of: **already covered** (name the entry), **synonym** (pointer entry), **new concept** (new entry, with its owner decisions), **how-to intent** (a blog post or guide, not a glossary entry), **reject** (rejected head). Show the classification table before creating anything.

### C. Write one entry

1. Decide the entry type.
2. **Ownership check:** list every concept the outline touches. For each, find the owner in the ownership map or the snapshot DB:
   ```sql
   SELECT collection, slug, name FROM items WHERE body_text LIKE '%event tracking%';
   ```
   Owned elsewhere → a link at the mention, not a section. Unowned and belongs to this term → write it fully. Unowned and belongs to another term → flag it as a gap; do not absorb it.
3. Draft: answer block, question H2s this entry owns, differs line, platform section, FAQ, sources. Link every sibling term at its first mention.
4. Check against the positions file (tools, numbers, methods) and the voice rules.

### D. Push to Webflow

- **New glossary, content authored locally** (markdown or SQLite): `push-pattern.md`. Order matters:
  1. POST every entry as a draft first (`push-pattern.md`, "First-time upload"), saving each item ID. In-text links are URL-based (`/glossary/<slug>`), so they can be written before their targets exist.
  2. Second pass: set `related-terms`. MultiReference takes **item IDs**, and a PATCH replaces the whole array, so send all of them:
     ```python
     ids = dict(conn.execute("SELECT slug, webflow_id FROM my_items"))
     payload = {"fieldData": {"related-terms": [ids[s] for s in related_slugs]}}
     ```
  3. Run the audit on a fresh snapshot (section 2 reports links to drafts; before launch every in-cluster link is a draft link, which is expected).
  4. Publish the whole cluster together, so no live entry links to an unpublished one.
- **Changes to live entries** (dedup trims, added links, schema): the CMS is the source of truth, so use `content-repair-pattern.md` with `scripts/repair_template.py`: snapshot, diff the first item, human approval, staged push, human publishes.
- **HTML caveat:** `scripts/compact.py` removes *all* whitespace between tags, including the space between two adjacent inline elements (`<a>x</a> <a>y</a>` becomes `<a>x</a><a>y</a>`, rendered "xy"). Link-dense glossary text hits this more than most content. Until that is fixed, check compacted output for adjacent inline elements separated only by a space.

### E. Schema: DefinedTerm + FAQPage per entry, DefinedTermSet on the index

This reuses the one-field-plus-one-embed mechanism from `faqpage-schema.md`.

**One-time setup:**

1. Create the `term-schema` PlainText field (multi-line) on the glossary collection.
2. In the collection template, Page Settings → Custom Code → inside `<head>`:
   ```html
   <script type="application/ld+json">
   {{wf {&quot;path&quot;:&quot;term-schema&quot;,&quot;type&quot;:&quot;PlainText&quot;\} }}
   </script>
   ```
3. If the template or a separate `faq-schema` field already emits FAQPage for these entries, build without FAQ (`include_faq=False`) so the page does not carry two FAQPage blocks.

**Per entry:** run `scripts/repair_template.py` in cross-field mode with the transform from `scripts/glossary_schema.py`:

```python
# In your copy of repair_template.py
SOURCE_FIELD = "body"          # the glossary body field (verify)
DEST_FIELD = "term-schema"

from glossary_schema import make_transform
transform = make_transform(
    site_url="https://www.example.com",
    url_prefix="/glossary/",
    set_url="https://www.example.com/glossary",
    set_name="Example Glossary",
    answer_field=None,          # or "answer" if the collection has an answer field
    include_faq=True,
)

def structural_markers(value: str) -> dict:
    return {
        "defined_term": value.count('"@type": "DefinedTerm"'),
        "questions": value.count('"@type": "Question"'),
    }

MUST_BE_ZERO_AFTER_PUSH = set()
```

The harness passes the whole item to a two-argument transform, so the transform can read `name` and `slug`. The field then holds:

```json
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "DefinedTerm",
      "@id": "https://www.example.com/glossary/click-map#term",
      "name": "Click map",
      "description": "<the answer block>",
      "url": "https://www.example.com/glossary/click-map",
      "inDefinedTermSet": {"@type": "DefinedTermSet", "@id": "https://www.example.com/glossary#set", "name": "Example Glossary", "url": "https://www.example.com/glossary"}
    },
    {"@type": "FAQPage", "@id": "https://www.example.com/glossary/click-map#faq", "mainEntity": ["..."]}
  ]
}
```

Rules:

- The schema is **derived** from the visible content: name from `name`, description from the answer block, Q&As from the FAQ section. It is never written by hand, so it cannot drift from what readers see. After any content change, re-run the repair; the transform is idempotent, so unchanged entries are skipped.
- An entry with no answer block gets no schema (the transform returns "" and the harness skips it).
- `</` is escaped as `<\/`, so answer text cannot close the `<script>` tag.

**Index page:** the page listing every term carries the `DefinedTermSet`. Generate it from a fresh snapshot and paste it into that page's custom code:

```bash
python3 scripts/glossary_schema.py set --db /abs/cms-snapshot/cms-<date>.db --glossary glossary \
  --site-url https://www.example.com --set-url https://www.example.com/glossary --set-name "Example Glossary"
```

It lists published, non-archived entries only. Regenerate it whenever entries are added, renamed or removed. The `@id` values match the per-entry nodes, so the set and the entries resolve to the same entities.

**Verify:** view source on one published entry (one `DefinedTerm`, at most one `FAQPage`), run it through the [Schema.org Validator](https://validator.schema.org/), and run `audit_glossary.py --schema-field term-schema` for the whole collection.

### F. Link back from the rest of the site

After the glossary is live: for every blog post and guide, link the first mention of each defined term to its entry. This is a `fix-pass-pattern.md` (local markdown source) or `content-repair-pattern.md` (CMS source) pass. Check each target with `curl` first. The audit's section 1 ("Links into the glossary from other collections") is the number this pass moves.

### G. Re-audit

After every batch of changes: re-snapshot, re-run `audit_glossary.py`, and compare the numbers with the previous run. Keep each audit output next to the change table it belongs to.

## Non-negotiables

1. **Ownership map before drafting.** No entry is written before its concepts have owners.
2. **Nothing goes to the CMS without an explicit approval** of a shown change table or diff.
3. **Slugs never change** after publish unless changing the URL is the task.
4. **Schema is derived, never hand-written.**
5. **No number without a primary source.**
6. **Link from the rest of the site only after the glossary is live.**
