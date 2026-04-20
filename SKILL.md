---
name: webflow-cms-ops
description: Production-tested skill for bulk-publishing and editorial fix passes on Webflow CMS. Handles the known gotchas — macOS SSL certs (certifi), the RichText whitespace-between-tags parser bug, resume-safe progress tracking, and 0.5s rate limiting. Use when pushing 20+ items, running editorial sweeps across a collection, or running any headless Webflow CMS op where the MCP or Designer are impractical. Triggers bulk publish Webflow, push markdown to Webflow CMS, sync content to Webflow, bulk edit CMS items, strip phrase across collection, editorial fix pass, CMS content sweep, programmatic Webflow content ops.
---

# Webflow CMS Ops

Bulk push and editorial fix patterns for Webflow CMS at scale. Built from production use pushing 281 articles with 796 API writes and zero failures.

## Which pattern does the user need?

Route based on the request. Read only the reference(s) needed for the specific task; keep context clean.

- **User wants to push content TO Webflow** (new content, updated content, from markdown/DB/CSV) → read `references/push-pattern.md`.
- **User wants to run an editorial FIX across existing content** (strip a phrase, remove meta leaks, swap headings, bulk regex rewrite) → read `references/fix-pass-pattern.md`.
- **User hits a weird Webflow RichText behavior** (empty sections, stripped content, parser mysteries, list items that vanish) → read `references/webflow-gotchas.md`.
- **User wants to BULK-GENERATE content from binaries via Claude** (alt text from images, summaries from PDFs, image categorization, screenshot QA — anything where Claude must SEE the file to produce the output) → read `references/vision-pipeline.md`.
- **User needs to populate or update alt text on a Webflow multi-image field** (set-of-images, gallery, carousel — each image in the array has its own alt) → read `references/vision-pipeline.md` if alts need to be generated from looking at the images, OR `references/push-pattern.md#patching-multi-image-fields` if alts already exist and only need pushing.
- **User has a heavy Claude batch that won't fit in one session, OR wants the batch to run async while they do other work** → read `references/session-handoff.md`.

Multiple references may apply to one task. For example, running a fix pass uses both `fix-pass-pattern.md` and `push-pattern.md` (the fix pass ends with a push step).

## Principles that apply to every push and every fix pass

All eight are non-negotiable. Each exists because skipping it caused a production failure we've hit.

### 1. `certifi.where()` for SSL context

macOS Python ships without a system cert bundle. The default `ssl.create_default_context()` fails with `CERTIFICATE_VERIFY_FAILED` on the first push. Always:

```python
import ssl, certifi
ctx = ssl.create_default_context(cafile=certifi.where())
```

Harmless on Linux. Required on macOS.

### 2. Compact HTML before pushing to RichText

The Python `markdown` library outputs `<ul>\n<li>...</li>\n</ul>`. Webflow's RichText parser silently drops list children when whitespace separates the tags. The Data API GET echoes back the original HTML, so the bug is invisible through automated checks — it only shows up in the CMS editor or rendered page.

Always route HTML through `scripts/compact.py` before pushing. See `references/webflow-gotchas.md` for the full diagnosis.

### 3. Absolute DB paths

Background shells and spawned processes reset `cwd`. Relative paths work locally and fail in production. Use absolute paths everywhere:

```python
DB_PATH = "/Users/name/project/content.db"  # good
DB_PATH = "content.db"                       # will bite you
```

### 4. 0.5s delay between API calls

Webflow allows 150 req/min. `time.sleep(0.5)` between requests = 120 req/min with headroom for burst traffic from other clients sharing the token.

### 5. Resume-safe progress file

Track pushed slugs in `/tmp/<task>_progress.txt`. If the script dies at item 87, restart picks up at 88. Never retry the whole batch.

```python
done = set()
if os.path.exists(PROGRESS_FILE):
    with open(PROGRESS_FILE) as f:
        done = set(l.strip() for l in f if l.strip())
# ... skip items in `done`
with open(PROGRESS_FILE, "a") as f:
    f.write(slug + "\n")
```

### 6. Visual verification after every push

The Data API GET echoes back the HTML you pushed, which is NOT proof the CMS editor renders it correctly. Webflow RichText has two representations — the HTML source (what you pushed) and the internal node tree (what the editor renders). If the parser fails to build nodes from your HTML, the GET still returns your original payload.

Verify at least 3 items per push:

- Open in Webflow CMS editor and look for the expected content.
- Or fetch the live URL and grep for expected elements.

### 7. Never run pushes from a background Claude Code agent

Permission prompts for MCP tool calls cannot reach background agents; they deadlock. Run push scripts from the foreground, a terminal, or a `bash` invocation with `run_in_background` for the Python script itself (not the agent).

### 8. Estimate context budget before starting; never inline a vision-batch above 100 items

Reading binary files (images, PDFs) into the conversation embeds the bytes permanently into history. Every subsequent turn's API request re-sends the full history. Around 200 binary Reads, the cumulative payload exceeds Anthropic's 32MB per-request cap and any further tool call fails — even one that doesn't read a file. The wall is invisible until it hits, and partial work is wasted unless you had per-item resume tracking from the start. Disk writes do not free the bytes; splitting into more user messages does not help. See `references/webflow-gotchas.md#8` for the full diagnosis.

Routing for batches where Claude GENERATES content from binaries (vision-based alt text, image classification, PDF summarization):

- **< 100 items:** inline is fine, one item per turn (`vision-pipeline.md` Pattern A)
- **100–800 items:** parallel subagents — each gets a fresh 32MB budget, returns text-only summaries to parent (`vision-pipeline.md` Pattern B)
- **> 800 items, OR user wants to step away while it runs, OR simplicity matters more than speed:** hand off to a fresh chat via `.handoff/` files (`session-handoff.md`)

Estimate before starting: `total_binaries × average_size_KB`. If that product exceeds 25MB (32MB minus safety margin), do NOT inline. Pick the next-larger pattern.

## Files in this skill

```
SKILL.md                              ← this file (always loaded)
references/
  push-pattern.md                     ← bulk push pattern, full push loop, multi-image field PATCH
  fix-pass-pattern.md                 ← six-step editorial fix pattern
  webflow-gotchas.md                  ← the eight gotchas with symptoms and fixes
  vision-pipeline.md                  ← bulk content generation from binaries (alt text, summaries, categorization)
  session-handoff.md                  ← split a heavy batch across two chats via filesystem
scripts/
  compact.py                          ← HTML compact helper (required before every push)
  push_template.py                    ← standalone runnable push script, edit config and run
examples/
  minimal-example.md                  ← end-to-end walkthrough for 10 markdown files
```

## Rules

1. Read only the reference(s) matching the user's task. Do not read all three upfront.
2. Follow the eight principles regardless of which pattern you're running.
3. Verify visually after every push. The API will lie to you otherwise.
4. One fix per fix-pass, never batch multiple fixes into a single pass.

---

**Task:** $ARGUMENTS
