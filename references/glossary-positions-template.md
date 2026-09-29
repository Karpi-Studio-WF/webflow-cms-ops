# Glossary Positions: <Project name>

Copy this file into the project (not into this skill), fill it in, and keep it current. It holds every decision that differs between projects, so `glossary-pattern.md` and `glossary-sweep.md` stay generic. Anything a glossary entry states as fact about the business (a tool, a method, a price) must agree with this file. When the site owner says something that contradicts it, the owner wins; update the file right away.

Last confirmed with the site owner: <YYYY-MM-DD>

## Site and collections

| Collection | Collection ID | Short name (snapshot) | URL prefix |
|---|---|---|---|
| Glossary | `<id>` | `glossary` | `/glossary/` |
| Guides | `<id>` | `guides` | `/guides/` |
| Blog | `<id>` | `blog` | `/blog/` |

Site domain (for `--site-domain`): `<example.com>`
Glossary index page URL (the `DefinedTermSet` page): `<https://www.example.com/glossary>`
DefinedTermSet name: `<Example Glossary>`

## Field slugs (verified on a live item, <YYYY-MM-DD>)

| Role | Slug |
|---|---|
| Name (bare term) | `name` |
| H1 (question) | `<h1-heading>` |
| Answer block | `<answer>` or "first paragraph of body" |
| Body (RichText) | `<body or body-2>` |
| Meta title / description | `meta-title` / `meta-description` |
| Related terms (MultiReference) | `<related-terms>` |
| Schema (PlainText, multi-line) | `<term-schema>` |

Title suffix the template appends: `< | Example Co>` → meta title budget: `<N>` characters.

## Tools, methods, numbers

What the business actually uses and recommends. Entries must match.

| Job | Position | Notes / open questions |
|---|---|---|
| <e.g. Session recordings> | <Tool> | <scope limits, e.g. "used for recordings only"> |
| <e.g. Test prioritization> | <Method> | <alternatives presented as alternatives> |

Open questions (ask the site owner before writing about these):

- <question> (raised <date>)

## Ownership map

| Concept | Owner (entry slug or guide URL) | Notes |
|---|---|---|
| <concept> | `<slug>` | <why, which test in glossary-pattern.md decided it> |

## Synonym entries

`<synonym-slug>` → `<owner-slug>` (short by design; ignore the answer-block length finding)

## Deliberate splits (never merge)

`<slug-a>` (<axis a>) / `<slug-b>` (<axis b>)

## Deliberate SERP cuts

`<slug>` → covered only in the context of <context>, not generalized.

## Rejected heads

Terms not targeted, with the reason:

| Term | Reason |
|---|---|
| <term> | <the bare term means something else / owned by a bigger meaning / how-to intent> |

## Voice rules

<House style for this site: register, banned words or punctuation, spelling variant, person.>

## Write log and evidence

Every CMS write is logged in: `<path to write log>`
Sweep evidence (audits, lane reports, change tables): `<path>`
