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

Multiple references may apply to one task. For example, running a fix pass uses both `fix-pass-pattern.md` and `push-pattern.md` (the fix pass ends with a push step).

## Principles that apply to every push and every fix pass

All seven are non-negotiable. Each exists because skipping it caused a production failure we've hit.

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

## Files in this skill

```
SKILL.md                              ← this file (always loaded)
references/
  push-pattern.md                     ← bulk push pattern, full push loop
  fix-pass-pattern.md                 ← six-step editorial fix pattern
  webflow-gotchas.md                  ← the seven gotchas with symptoms and fixes
scripts/
  compact.py                          ← HTML compact helper (required before every push)
  push_template.py                    ← standalone runnable push script, edit config and run
examples/
  minimal-example.md                  ← end-to-end walkthrough for 10 markdown files
```

## Rules

1. Read only the reference(s) matching the user's task. Do not read all three upfront.
2. Follow the seven principles regardless of which pattern you're running.
3. Verify visually after every push. The API will lie to you otherwise.
4. One fix per fix-pass, never batch multiple fixes into a single pass.

---

**Task:** $ARGUMENTS
