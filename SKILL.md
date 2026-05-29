---
name: webflow-cms-ops
description: Production-tested skill for bulk-publishing, editorial fix passes, and content shape repair on Webflow CMS. Handles the known gotchas — macOS SSL certs (certifi), the RichText whitespace-between-tags parser bug, resume-safe progress tracking, and 0.5s rate limiting. Use when pushing 20+ items, running editorial sweeps across a collection, or running any headless Webflow CMS op where the MCP or Designer are impractical. Triggers bulk publish Webflow, push markdown to Webflow CMS, sync content to Webflow, bulk edit CMS items, strip phrase across collection, editorial fix pass, CMS content sweep, programmatic Webflow content ops.
---

# Webflow CMS Ops

Bulk push and editorial fix patterns for Webflow CMS at scale. Built from production use pushing 281 articles with 796 API writes and zero failures.

## Which pattern does the user need?

Route based on the request. Read only the reference(s) needed for the specific task; keep context clean.

- **User wants to push content TO Webflow** (new content, updated content, from markdown/DB/CSV) → read `references/push-pattern.md`.
- **User wants to run an editorial FIX across existing content** (strip a phrase, remove meta leaks, swap headings, bulk regex rewrite) → read `references/fix-pass-pattern.md`.
- **User wants to REPAIR a legacy content shape across existing items** (convert old code blocks to a new shape, strip a brand suffix from `meta-title`, rename deprecated schema properties, restore tables stripped by Webflow ingest, rewrite an old domain in `href` values, any "convert shape A to shape B" job on stored CMS field values) → read `references/content-repair-pattern.md`.
- **User hits a weird Webflow RichText behavior** (empty sections, stripped content, parser mysteries, list items that vanish) → read `references/webflow-gotchas.md`.
- **User wants to BULK-GENERATE content from binaries via Claude** (alt text from images, summaries from PDFs, image categorization, screenshot QA — anything where Claude must SEE the file to produce the output) → read `references/vision-pipeline.md`.
- **User needs to populate or update alt text on a Webflow multi-image field** (set-of-images, gallery, carousel — each image in the array has its own alt) → read `references/vision-pipeline.md` if alts need to be generated from looking at the images, OR `references/push-pattern.md#patching-multi-image-fields` if alts already exist and only need pushing.
- **User has a heavy Claude batch that won't fit in one session, OR wants the batch to run async while they do other work** → read `references/session-handoff.md`.

Multiple references may apply to one task. For example, running a fix pass uses both `fix-pass-pattern.md` and `push-pattern.md` (the fix pass ends with a push step).

## Principles that apply to every push, fix pass, and content repair

All nine are non-negotiable. Each exists because skipping it caused a production failure we've hit.

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

### Code block formatting in rich text (inline `<code>` vs block `<pre><code>`)

Same RichText parser family as principle 2 above. The site's code highlighting styles target `<pre><code>` only. When a multi-line code block (JSON-LD, an HTML snippet, a script, a full code example) is pushed as `<p><code>...</code></p>`, the highlighting breaks and the block renders as plain text. Inline code references inside a sentence are fine as `<code>` within `<p>`.

**The rule:**

- Single token or inline reference inside a sentence stays inline: `<code>` within `<p>`. Example: `<p>use the <code>display: flex</code> property</p>` is correct.
- Multi-line code, a full HTML element, a JSON-LD block, a script tag, or anything that should visually render as a code block must be `<pre><code>...</code></pre>` at the root of the rich text. Never wrap it in `<p>`.

**Detection logic.** Treat code content as block level (needs `<pre><code>`) if ANY of these hold:

- contains a newline character (`\n`)
- starts with `<script`, `<style`, `<!--`, `<html`, or `<!DOCTYPE`
- is valid JSON or JSON-LD
- exceeds 120 characters
- contains more than one HTML tag

Otherwise treat it as inline and leave it as `<code>` inside `<p>`.

**Pre-upload check.** Run this transform on every rich text payload as the last step before pushing (after `compact.py`, so the `<pre>` blocks it creates are not re-compacted). It promotes any `<p><code>...</code></p>` whose inner content classifies as block level into a root level `<pre><code>...</code></pre>`, and leaves inline `<code>` alone:

```python
import json, re
from html import unescape

BLOCK_START = re.compile(r'\s*<(script|style|!--|html|!DOCTYPE)', re.IGNORECASE)
TAG = re.compile(r'<[a-zA-Z/!]')

def is_block_code(text):
    """True if this code content should render as a block (<pre><code>)."""
    t = unescape(text)
    if "\n" in t:
        return True
    if BLOCK_START.match(t):
        return True
    if len(t) > 120:
        return True
    if len(TAG.findall(t)) > 1:
        return True
    s = t.strip()
    if s[:1] in "{[":
        try:
            json.loads(s)
            return True
        except ValueError:
            pass
    return False

def promote_code_blocks(html):
    """Rewrite <p><code>...</code></p> to <pre><code>...</code></pre> when the
    inner content is block level. Inline <code> inside prose is left alone.
    Idempotent: existing <pre><code> is not matched."""
    def repl(m):
        inner = m.group(1)
        if is_block_code(inner):
            return "<pre><code>" + inner + "</code></pre>"
        return m.group(0)
    return re.sub(r'<p><code>(.*?)</code></p>', repl, html, flags=re.DOTALL)
```

Wire it into the push as the final transform: `html = promote_code_blocks(compact(html))` right before the PATCH.

**Audit existing content.** To find items already pushed with block code trapped in `<p><code>`, page through the collection and flag any `<p><code>...</code></p>` whose inner content trips the block test. The Data API GET returns the HTML as pushed (see principle 6 and `references/webflow-gotchas.md`), so the stored shape is exactly what you inspect here:

```python
import urllib.request, ssl, certifi, json, re

ctx = ssl.create_default_context(cafile=certifi.where())
PCODE = re.compile(r'<p><code>(.*?)</code></p>', re.DOTALL)

offenders, offset = [], 0
while True:
    req = urllib.request.Request(
        f"https://api.webflow.com/v2/collections/{COLLECTION_ID}/items?limit=100&offset={offset}",
        headers={"Authorization": f"Bearer {API_TOKEN}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, context=ctx) as resp:
        items = json.loads(resp.read()).get("items", [])
    if not items:
        break
    for it in items:
        body = it["fieldData"].get(BODY_FIELD, "") or ""
        if any(is_block_code(inner) for inner in PCODE.findall(body)):
            offenders.append(it["fieldData"].get("slug", it["id"]))
    offset += 100

print(f"{len(offenders)} items need code-block repair:")
for s in offenders:
    print(f"  {s}")
```

Repair each offender by running its body through `promote_code_blocks` and pushing the result with the normal loop (see `references/push-pattern.md`). Then verify visually: open three repaired items and confirm the code blocks render with highlighting. Per principle 6, the API GET alone is not proof.

**Round-trip-safe shape (when a syntax highlighter is wired up).** Sites with highlight.js (or a similar highlighter in custom code) target `<pre><code class="language-X">` precisely, and the Webflow Designer silently reverts non-conforming `<pre><code>` variants back to the legacy `<p><code>` shape the next time the article is opened. Push code blocks in this exact shape to survive both:

```html
<pre><code class="language-X">CONTENT
</code></pre>
```

- `class="language-X"` matches the content type: `language-json` for JSON / JSON-LD, `language-html` for HTML / script snippets, `language-python` for Python. `language-html` is the safe catch-all when detection is ambiguous; it also shows as the language pill in the Designer.
- CONTENT uses real `\n` newlines (not `<br>`), real spaces for indentation (not `&nbsp;`), and `&quot;` for `"` inside the code. Leave `&lt;`, `&gt;`, `&amp;` as-is.
- One trailing `\n` before the closing `</code>`.
- The wrapping `<p>` is dropped; `<pre>` sits directly in the rich text body.

Verified on the Karpi Studio Schema Glossary `book` item: this exact shape survives a Designer open + publish round-trip; variants do not. When running `promote_code_blocks` above on a site with a highlighter, augment its output line to include the detected language class and a trailing `\n` before `</code>`.

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

### 9. Re-fetch the live value immediately before every write — and validate it

Never build an edit on a stale or assumed copy. State drifts between the fetch and a later write: a teammate republishes, or the Webflow Designer rewrites the item out from under you — opening a page in the Designer editor silently reverts **every** `<pre><code>` block back to the legacy `<p><code>` shape (with `<br>`/`&nbsp;`). Immediately before any PATCH or create, GET the exact item(s) and field(s) you are about to change, derive the new value from that just-fetched value, and gate the write on a document-level integrity check: expected `<pre>`/heading/block counts, required markers present, `isDraft` as expected, no known corruption signature. If the fetched document doesn't match expectations, STOP and surface it — do not write.

```python
cur  = http("GET", f".../items/{item_id}")              # re-fetch NOW, not earlier
body = cur["fieldData"][FIELD]
assert len(re.findall(r"<pre[^>]*>", body)) >= EXPECTED_MIN_BLOCKS  # integrity gate
assert "<br><br></code></p>" not in body                            # abort on known corruption
new = transform(body)                                               # build from the fresh value
# ...only PATCH after the gate passes
```

A guardrail that validates only the few bytes you're touching, while ignoring whether the surrounding document is intact, will happily publish corruption. This exists because an edit was once pushed onto a draft the Designer had silently reverted: the write checked only its two target lines and propagated the reverted state to the rest of the page.

## Files in this skill

```
SKILL.md                              ← this file (always loaded)
references/
  push-pattern.md                     ← bulk push pattern, full push loop, multi-image field PATCH
  fix-pass-pattern.md                 ← six-step editorial fix pattern
  content-repair-pattern.md           ← shape repair on stored CMS field values (legacy markup migration)
  webflow-gotchas.md                  ← the gotchas with symptoms and fixes
  webflow-richtext-tables.md          ← HTML <table> in RichText (markdown tables don't work)
  vision-pipeline.md                  ← bulk content generation from binaries (alt text, summaries, categorization)
  session-handoff.md                  ← split a heavy batch across two chats via filesystem
scripts/
  compact.py                          ← HTML compact helper (required before every push)
  push_template.py                    ← standalone runnable push script, edit config and run
  repair_template.py                  ← standalone runnable repair script (content-repair-pattern), edit config and run
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
