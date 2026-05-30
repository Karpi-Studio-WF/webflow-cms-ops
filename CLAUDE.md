# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

A skill bundle for bulk Webflow CMS operations — pushing articles, running editorial fix passes, and generating content via vision. Production-tested across 281 articles with 796 API writes. It is a reference skill with patterns and scripts, not a deployable application. There is no build step, no test suite, and no CI.

## Running the Scripts

Install Python dependencies for the helper scripts:

```bash
pip3 install certifi markdown
```

Run a bulk push (after editing the CONFIG block in the script):

```bash
python3 scripts/push_template.py
```

Use `compact.py` as a library, not a standalone command. It exposes two entry points: `to_compact_html(markdown)` renders markdown to push-ready HTML; `compact(html)` compacts already-rendered HTML (this is the one fix passes call after regenerating from `body_md`):

```python
from compact import to_compact_html, compact
html = to_compact_html(markdown_string)   # markdown → push-ready HTML
html = compact(existing_html)             # already HTML → push-ready
```

## Architecture

```
SKILL.md                     # Entry point — routes tasks to reference patterns
references/
  push-pattern.md            # Bulk push workflow (20+ items)
  fix-pass-pattern.md        # Editorial sweep workflow (10+ items)
  content-repair-pattern.md  # Shape repair on stored CMS field values (legacy markup migration)
  vision-pipeline.md         # Vision batch generation (alt text, summaries)
  webflow-gotchas.md         # known failure modes with fixes
  webflow-richtext-tables.md # HTML <table> in RichText (markdown tables don't work)
  session-handoff.md         # Multi-chat batching for large jobs
scripts/
  compact.py                 # HTML whitespace stripper (required for all RichText pushes)
  code_block_repair.py       # Pure code-block transforms — promote legacy code blocks, add language- classes (library)
  push_template.py           # Standalone push script (edit CONFIG block then run)
  repair_template.py         # Standalone repair script (content-repair-pattern); edit CONFIG block then run
examples/
  minimal-example.md         # End-to-end walkthrough for 10 markdown files
```

**How the skill routes:** When invoked, Claude reads `SKILL.md` to identify which pattern matches the task, then reads only the relevant reference document(s).

**Scripts are executed, not read into context.** `compact.py` and `push_template.py` are production utilities — edit the CONFIG block in `push_template.py` and run directly. Do not summarize or inline them.

## The 8 Non-Negotiable Principles

Every push, fix pass, and vision batch follows these. Each exists because it prevented a real production failure:

1. **`certifi.where()` for SSL context** — macOS Python lacks system certs. Always use `ssl.create_default_context(cafile=certifi.where())`.
2. **Compact HTML before RichText push** — Python's `markdown` outputs `<ul>\n<li>`, and Webflow's parser silently drops list children when whitespace separates block tags. Route all HTML through `compact.py`.
3. **Absolute DB paths** — Background shells reset `cwd`. Relative paths fail silently in production.
4. **0.5s delay between API calls** — Webflow allows 150 req/min; 0.5s = 120 req/min with burst headroom.
5. **Resume-safe progress file** — Track pushed slugs in `/tmp/<task>_progress.txt`. A crash at item 87 restarts at item 88.
6. **Visual verification after every push** — API GET echoes your HTML back; it does not confirm Webflow rendered it correctly. Open 3+ items in the Webflow editor or on the live page.
7. **Never run pushes from background Claude Code agents** — Permission prompts cannot reach background agents; they deadlock.
8. **Estimate context budget before vision batches** — Reading binaries embeds bytes permanently in history. Over ~200 binaries, cumulative payload exceeds Anthropic's 32MB per-request cap.

## Key Patterns

### Bulk Push (push-pattern.md)
Scope → compact HTML → push loop with resume → visual verify → publish.

### Editorial Fix Pass (fix-pass-pattern.md)
Identify affected items → write pure `fix(markdown) → markdown` transform → apply to DB → regen HTML for touched items only → push filtered slugs → spot-check 3–5 items.

### Vision Pipeline (vision-pipeline.md)
Choose pattern by batch size:
- **< 100 items:** Inline, one per turn.
- **100–800 items:** Parallel subagents, each processing a chunk in isolated context.
- **> 800 items:** Handoff to new chat via `.handoff/task.md` and `.handoff/progress.md`.

### Session Handoff (session-handoff.md)
Split heavy batches across two chat sessions when the 32MB request cap is near. Worker reads `.handoff/task.md`, writes progress to `.handoff/progress.md`, outputs to `.handoff/results.json`.

## Webflow API Details

- **API version:** Data API v2
- **Auth:** Bearer token — never commit tokens; set in the CONFIG block of scripts
- **Rate limit:** 150 req/min; scripts enforce 0.5s delay
- **RichText field slug:** Often `body`, but may be `body-2` — verify by fetching one live item and inspecting `fieldData` keys
- **Tables:** markdown table syntax doesn't work, AND a bare `<table>` renders broken on the live page (flattened, or surviving but unstyled — the API GET hides it). A table needs BOTH: the `<div data-rt-embed-type="true">...</div>` embed wrapper (passthrough so the grid survives) AND a site CSS rule scoped to the rich-text wrapper targeting the bare tags (e.g. `.rich-text-body table`). Tables carry no class; styling hooks the tags. Verified against a live item with 12 embed-wrapped tables (see `references/webflow-richtext-tables.md`)
- **Code blocks:** block-level code must be `<pre><code>` at the RichText root, never `<p><code>` (which breaks highlighting and renders as plain text). Single inline tokens stay as `<code>` inside `<p>`. Run `promote_code_blocks()` (defined in `SKILL.md`) as the final transform *after* `compact.py`. On sites with a syntax highlighter, push the exact shape `<pre><code class="language-X">…\n</code></pre>` or the Designer silently reverts it on the next open (see `SKILL.md`, "Code block formatting in rich text")
- **Multi-image field PATCH:** Must spread `**img` to preserve `fileId` and `url`; only override the target field

## Expected SQLite Schema

The local SQLite DB is the staging source of truth. `body_md` is the authored markdown; `body_html` is a derived artifact regenerated from it through `compact.py` and is the value actually pushed to the RichText field. A fix pass edits `body_md`, regenerates `body_html` for touched rows only, then pushes.

```sql
CREATE TABLE my_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE,
    webflow_id TEXT,         -- Webflow item ID; the PATCH target. NULL until a first-time POST creates the item.
    body_md TEXT,            -- markdown source of truth
    body_html TEXT,          -- compact HTML regenerated from body_md; the value pushed to RichText
    meta_title TEXT,
    meta_description TEXT
);
```

`push_template.py` reads the `my_items` table and SELECTs only the columns it pushes (`slug`, `webflow_id`, `body_html`, `meta_title`, `meta_description`). Adapt the table name and SELECT for your schema.
