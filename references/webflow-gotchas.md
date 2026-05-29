# Webflow CMS Data API: Known Gotchas

Read this when:

- A push succeeds at the API level but content looks wrong in the editor or on the rendered page.
- The Data API returns success codes but an automated check flags content as missing.
- You're about to start a bulk operation and want to avoid known failure modes.

Each entry below is a production failure we hit. Symptoms, cause, fix.

## 1. Markdown table syntax doesn't work, and a bare HTML `<table>` renders broken

**Symptom:** Markdown tables (`| col | col |` syntax) show as empty blank space on the rendered page. Bare HTML `<table>` pushes look fine in the GET response but render broken live — either flattened to a run-on paragraph (cell text concatenated, no row/column boundaries) or, in the current blog collection, the grid survives but renders completely unstyled (no borders, no padding, "looks broken on the front end").

**Cause:** The Python `markdown` library does not convert GFM pipe tables to HTML by default, so they pass through as raw text. Separately, Webflow does not treat a bare `<table>` in rich text as first-class: depending on the path it either drops the grid tags on ingest (leaving cell text in a single `<p>`) or keeps them but applies no styling. Two things fix it together — the embed wrapper makes the markup passthrough, and a site CSS rule scoped to the rich-text wrapper gives the table styling.

**Fix:** Wrap the HTML `<table>` in a Rich Text HTML-Embed div (passthrough), and ensure the site has CSS targeting tables inside the rich-text wrapper:

```html
<div data-rt-embed-type="true">
<table>
  <thead><tr><th>Field</th><th>Description</th></tr></thead>
  <tbody><tr><td>name</td><td>What it does</td></tr></tbody>
</table>
</div>
```

No class on the `<table>`. Style via one site-wide rule scoped to the rich-text wrapper, targeting the bare tags (e.g. `.rich-text-body table { ... }`); an unstyled table is the #1 "table looks broken" cause even when the wrapper is correct. `compact.py` is fine but not required inside the embed.

**See also:** `references/webflow-richtext-tables.md` for the full pattern, the scoped-CSS styling block, the class-less migration sequence, exact API call structure, and a list of mistakes other agents make.

## 2. Whitespace between list tags drops children

**Symptom:** `<ul>`/`<ol>` headings appear on the page but the list items are missing. Sections under `### Required`, `### Recommended`, etc., look empty. API GET echoes back the HTML with the list items present, making the bug invisible through automated checks.

**Cause:** Webflow's RichText parser treats whitespace between `<ul>`, `<li>`, and `</ul>` as content boundaries and silently drops the list children. The Python `markdown` library's default output has these newlines, so every HTML push produced by it will trigger this bug.

The two HTML variants:

```html
<!-- What Python markdown produces — BREAKS -->
<ul>
<li>Item one</li>
<li>Item two</li>
</ul>

<!-- What Webflow expects — WORKS -->
<ul><li>Item one</li><li>Item two</li></ul>
```

**How to diagnose:** Open the affected item in the Webflow CMS editor. If the editor shows empty sections for lists, you have this bug. Confirm by manually typing a bullet list in the editor, saving, then GET'ing the item — Webflow's stored HTML has no whitespace between tags.

**Fix:** Run every HTML payload through a compact helper before pushing:

```python
import re

def compact(html):
    """Strip whitespace between block tags; preserve <pre> block contents."""
    out, i = [], 0
    while i < len(html):
        pre = re.search(r'<pre[^>]*>[\s\S]*?</pre>', html[i:])
        if pre:
            out.append(re.sub(r'>\s+<', '><', html[i:i + pre.start()]))
            out.append(pre.group(0))
            i += pre.end()
        else:
            out.append(re.sub(r'>\s+<', '><', html[i:]))
            break
    return ''.join(out)
```

The `<pre>` preservation matters — JSON-LD code examples need their internal whitespace intact for readability.

This bug is NOT documented in Webflow's API docs. We found it by manually typing content in the editor, inspecting the API response, and comparing to what we had been pushing.

## 3. macOS Python has no system cert bundle

**Symptom:** Every Webflow API call fails with `urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1002)`.

**Cause:** Python installed via the official installer, Homebrew, or pyenv on macOS does not ship with the system's CA certificates. The default `ssl.create_default_context()` can't verify HTTPS certs.

**Fix:** Install `certifi` and point the SSL context at its bundle:

```bash
pip3 install certifi
```

```python
import ssl, certifi
ctx = ssl.create_default_context(cafile=certifi.where())
```

Use `ctx` on every `urlopen()` call. Harmless on Linux where the default context already works.

## 4. Soft-deleted slugs reserve permanently

**Symptom:** You delete a CMS item in the Designer, then try to import or create a new item with the same slug. Webflow creates it with a suffixed slug like `product-62276` or rejects the operation.

**Cause:** Webflow's "delete" is a soft-delete. The item moves to a trash state but its slug remains reserved indefinitely. There is no UI or API call to release the slug.

**Fix if already hit:** Create a new collection with final names and slugs, migrate items via API, update every internal link in every article that referenced the old URLs.

**Avoid:** Lock the collection structure before any bulk content import. Choose production names and slugs on day one. Do not rename collections mid-project.

## 5. MultiReference fields can't change their target collection

**Symptom:** You created a MultiReference field on Collection A pointing to Collection B. You need to replace B with B'. The reference field still points to B.

**Cause:** Webflow's API does not allow retargeting a reference field. The Designer doesn't either.

**Fix:** Delete the MultiReference field. Create a new one pointing to B'. Re-populate every item's references.

**Avoid:** Same as #4. Design the collection graph before content creation.

## 6. Background Claude Code agents deadlock on permission prompts

**Symptom:** A background agent using the Webflow MCP stops responding. The foreground session shows no errors. Logs are empty.

**Cause:** The Webflow MCP requires user approval for tool calls. The approval dialog can only reach the foreground Claude Code session. A background agent has no UI surface to prompt into. The tool call hangs forever, the agent halts.

**Fix:** Never run Webflow MCP operations from a background agent. Run them from:

- A foreground agent (the agent the user is actively chatting with).
- A Python script (no MCP involvement).
- A `bash` invocation with `run_in_background` for the Python script, not the agent itself.

## 7. The Data API GET lies about RichText

**Symptom:** You push HTML to a RichText field. The API returns 200. A subsequent GET returns the HTML you pushed. You assume content landed correctly. But the CMS editor and the live page show empty sections.

**Cause:** Webflow RichText has two internal representations:

- **HTML source:** what you pushed. Returned on API GET.
- **Node tree:** Webflow's internal block structure. What the editor edits and the rendered page serves.

When Webflow's parser fails to build nodes from your HTML (due to #1 or #2 above, or any other unsupported construct), the HTML source is retained but the node tree is empty. The API GET still returns your pushed HTML, so automated checks pass. Visual inspection fails.

**Fix:** Always verify visually after a push. Minimum:

- Open 3 affected items in the CMS editor and confirm content renders.
- Or fetch the rendered live URL and grep for expected elements.

Do not trust the API response as evidence that the editor or live page shows the content.

This is the most expensive gotcha in the set. It wasted one debugging session where an automated pipeline reported success while the rendered site was empty.

## 8. The 32MB request cap when reading binaries in-session

**Symptom:** A long-running batch task that reads many binary files (images, PDFs) succeeds for the first ~200 items, then any further tool call — even one that doesn't read a file — fails with `Request too large (max 32MB). Try with a smaller file.` The script's results on disk up to that point are intact, but the agent in the session cannot make any further requests.

**Cause:** Anthropic's API enforces a 32MB cap on the size of a single request payload. Every Claude tool call sends a request that includes the entire conversation history up to that point — every prior message, every prior tool result. When a tool result contains a binary (e.g., a 150KB JPEG read via the Read tool), that binary embeds permanently into history. Each subsequent turn's request re-sends every prior binary. At ~200 binaries × 150KB = 30MB, the next request crosses the cap.

The wall is invisible until it hits. Saving intermediate results to disk does NOT free the bytes — disk writes do not shrink conversation history. Splitting the work into more user messages does NOT help — every message's request still carries every binary previously Read in this session.

**Diagnosis:**

- The error message says `Request too large` or `max 32MB`
- You've Read more than ~150 binary files larger than 100KB each in the current session

**Fix (after hitting the wall):**

1. Existing results in your output file are intact. The resume mechanism (if any) can pick up.
2. Open a fresh Claude chat — the new session has a fresh budget.
3. For the rest of the batch, switch to one of:
   - `references/vision-pipeline.md` Pattern B (parallel subagents) for medium batches
   - `references/session-handoff.md` for large batches or when you want to step away

**Avoid (before starting):**

- Estimate the batch size: `total_binaries × average_size_KB`. If the product exceeds 25MB (32MB minus safety margin), do NOT inline.
- For batches > 100 binaries, use subagents or the handoff pattern from the start.
- See principle #8 in `SKILL.md` for the routing logic.

This is the most expensive gotcha in the set when you're new to vision-batch work — partial runs of 200+ items can take an hour to discover the wall, and the partial work is wasted unless you had resume tracking in place from the start.

## 9. Brand suffix doubled in the rendered page title

**Symptom:** The live page `<title>` shows the brand twice, like `Some Page | Example Co | Example Co`. The stored field and the API GET look correct; only the rendered page is wrong, so it surfaces in Google results, browser tabs, and social shares.

**Cause:** The collection's page template (or the page SEO settings) already appends a fixed brand suffix to the title field. If the stored `meta-title` also contains that suffix, it renders twice.

**Fix:** Store only the page-specific title in `meta-title`. Never include text the template already injects (brand name, trailing pipe, agency name); let the template add it. The general rule: do not duplicate anything the template or page settings already inject into the title.

**Verify per collection, do not assume.** Templates differ between collections and change over time, so there is no reliable static list. Before writing titles to a collection, confirm whether it auto-appends: fetch one existing item and compare its stored `meta-title` against the live `<title>`, or open a published page and read the title. For instance, on one site some collection templates auto-append a ` | Brand` suffix while others do not. Treat that as a snapshot to re-check, not a fixed rule.

**Check after publishing, not before.** A PATCH updates only the draft. The live domain and the `.webflow.io` URL serve the last-published version (see "Item publish state" below), so a title check right after a push reads the stale value. Publish the item or site first, then:

```bash
curl -sL "<published-page-url>" | grep -oiE '<title>[^<]*</title>'
```

The brand should appear exactly once. If it appears twice, the suffix is stored in the field: strip it and re-push. If the old title lingers, let the CDN catch up and re-check before assuming a failure.

## Related behaviors (not quite gotchas)

### Rate limiting

150 req/min hard cap per token. Using `time.sleep(0.5)` between requests = 120 req/min with headroom. If the token is shared with other clients (e.g., a production app), reduce to 0.75s or 1s.

### Item publish state

PATCH updates go to the staged draft. The item's `lastPublished` timestamp updates only when the site is published (via Designer) or items are published via `POST /v2/collections/{id}/items/publish`. The `.webflow.io` URL serves the last-published version, so unpublished changes won't appear there until a publish event.

### Field slug mismatches

Field slugs differ from display names: "Meta Description" → `meta-description`. "Body" may be `body` or `body-2` depending on when it was created. Pushing to a non-existent field slug returns 200 but does nothing. Verify slugs by GET'ing one item and inspecting `fieldData` keys before pushing.
