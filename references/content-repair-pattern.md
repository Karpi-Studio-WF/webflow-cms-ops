# Content Repair Pattern: Reshape Legacy CMS Content at Scale

Use this when the source of truth lives in the Webflow CMS and a stored field's current shape is wrong: legacy markup that needs to be converted to a new shape across many items. The mechanics generalize past the original example. Some shapes this pattern handles:

- Legacy `<p><code>` code blocks converted to the round-trip-safe `<pre><code class="language-X">` shape (`SKILL.md` "Code block formatting in rich text").
- Bare `<table>` blocks restored as embed-wrapped tables (`references/webflow-richtext-tables.md`).
- Brand suffix stripped from `meta-title` across a collection.
- Deprecated schema property names renamed (e.g., `founders` to `founder`).
- Old domain rewritten to new domain in `href` values.
- HTML entity double-encoding (`&amp;amp;`) corrected to single encoding.

It complements the other patterns:

| Pattern | Source of truth | When to use |
|---|---|---|
| `push-pattern.md` | Local DB / markdown / CSV | New content or full re-push from outside |
| `fix-pass-pattern.md` | Local markdown | Editorial change to markdown, then regenerate HTML and push |
| `content-repair-pattern.md` | The Webflow CMS itself | Reshape stored field values directly, no local canonical |

Content repair pulls the current value from the CMS, derives the new value purely from it, and writes it back. No local source-of-truth is required.

## The seven-step pattern

### 1. Define the target shape

Write the exact new shape down. Verify it against one live item (e.g., the Schema Glossary `book` item for the code-block shape, or the live `/blog/webflow-pricing` tables for the embed-wrapper shape). Capture attribute-quoting style, entity escaping, internal whitespace, and any required wrappers.

If a Webflow Designer round-trip is part of the workflow (the human opens, eyeballs, publishes), confirm the target shape survives a Designer open + publish round-trip. Non-conforming variants get silently rewritten back to legacy.

### 2. Write the transformer as a pure function

```python
def transform(field_value: str) -> str:
    """Pure: current field value -> new field value. Idempotent."""
```

Rules:

- **Pure.** No I/O, no DB, no API calls. String in, string out.
- **Idempotent.** Running twice produces the same output as running once. Required for resume safety and safe re-pushes.
- **Conservative.** Match only the specific legacy shape. Leave everything else (other elements, inline content, prose) untouched.
- **Testable.** Easy to call on 5 to 10 sample strings with assertions; assert on at least one already-converted input to confirm idempotency.

The transformer is the only project-specific part of the workflow. The rest of the harness is reusable across repairs.

### 3. Audit the scope

Count first, always. Before any push:

```python
items = list_collection_items_all(COLLECTION_ID)
affected = [it for it in items if transform(it["fieldData"][FIELD_SLUG]) != it["fieldData"][FIELD_SLUG]]
print(f"{len(affected)} of {len(items)} items would change")
for it in affected:
    print(f"  {it['fieldData']['slug']}")
```

If the count is surprisingly high or low, stop and investigate. Do not push.

### 4. Snapshot every body to disk

Before any push, save the current value of every affected item to disk. This is your revert source:

```python
os.makedirs(SNAPSHOT_DIR, exist_ok=True)
for it in affected:
    slug = it["fieldData"]["slug"]
    body = it["fieldData"][FIELD_SLUG]
    open(f"{SNAPSHOT_DIR}/{slug}.html", "w").write(body)
```

Do this for every repair pass, even small ones. If something corrupts mid-batch, revert from disk.

### 5. Diff the first item, get human approval

Apply the transformer to the first affected item. Show a structural diff (heading counts, target-shape counts, byte size delta) plus per-block before/after previews truncated to ~140 chars. Do not dump 30 KB of HTML; signal-to-noise.

The human approves the shape on the first item. The rest of the collection gets batched after that approval. Per-collection gate: if a second collection is in scope, the first item there gets the same diff-and-approve treatment.

### 6. Stage push (NEVER publish)

For each approved item, PATCH the field via `update_collection_items`. Do NOT call `publish_collection_items`. Do NOT set `isDraft: true` on the update (that would unpublish the live item; the published version stays live until the human publishes the staged change from the Designer).

After each PATCH, run a structural verification: same heading counts as expected, expected target-shape count, ZERO legacy-shape remaining, expected language-class count (or whatever markers your transform changes). If verification fails, stop the batch and investigate; do not continue.

DON'T byte-compare the API echo to your local expected value. Webflow normalizes some attribute quotes (double to single) and whitespace on ingest, so byte equality fails routinely even on correct pushes. Structural integrity is the real check.

### 7. Human publishes, verifies live

After the staged push, the human opens each item in the Webflow Designer, eyeballs the change, and publishes from there. Per-collection gate: don't move to the next collection's audit until the first collection's items have been confirmed rendering correctly on the live page.

## Non-negotiables

1. **NEVER call publish from the API.** The human publishes in the Designer. Repairs touch live-rendered content; this gate is firmer than for `fix-pass-pattern.md`.
2. **Don't set `isDraft: true` on update.** The item is published; flipping `isDraft` would unpublish it from the live site. Just call `update_collection_items` and skip publish.
3. **Snapshot before push, every time.** Disk-revert capability is non-optional.
4. **Idempotent transformer.** Re-running on already-converted content must be a no-op.
5. **Structural verification, not byte equality.** Webflow normalizes.
6. **Per-collection approval gate.** First item in each collection: full per-block diff. After approval, batch the rest.

## The transformer interface

The harness in `scripts/repair_template.py` expects:

```python
def transform(field_value: str) -> str:
    """Pure: current field value -> new field value. Idempotent."""
```

That's the only project-specific code. The harness handles audit, snapshot, diff, stage, verify, and the human-publish gate. Swap `transform` for a different transformation and the same harness handles a different repair.

## Worked example: code-block migration

The Schema Glossary code-block migration. Replaces legacy `<p><code>...with <br>/&nbsp;...</code></p>` with the round-trip-safe `<pre><code class="language-X">CONTENT\n</code></pre>` shape from `SKILL.md`.

```python
import re
from html import unescape

BR_RE    = re.compile(r'<br\s*/?>', re.IGNORECASE)
NBSP_RE  = re.compile(r'&nbsp;')
ZWJ      = chr(0x200D)
P_CODE_RE = re.compile(r'<p>\s*<code>(.*?)</code>[^<]*</p>', re.DOTALL)

def _detect_language(text_decoded: str) -> str:
    s = text_decoded.lstrip()
    if not s:
        return "language-html"
    if s.startswith(("<script", "<style", "<html", "<!DOCTYPE", "<!--")):
        return "language-html"
    if re.search(r'\bdef \w|\bimport \w|^class \w', s, re.MULTILINE):
        return "language-python"
    if s[:1] in "{[" and re.search(r'"[\w@$-]+"\s*:', s):
        return "language-json"
    return "language-html"

def _is_legacy(inner: str) -> bool:
    return bool(BR_RE.search(inner) or NBSP_RE.search(inner))

def transform(field_value: str) -> str:
    """Rewrite legacy <p><code>...</code></p> blocks (with <br>/&nbsp;) to the
    round-trip-safe <pre><code class="language-X">CONTENT\n</code></pre> shape.
    Idempotent: <p><code> without <br>/&nbsp; is left alone; existing <pre><code>
    is not matched at all."""
    def repl(m):
        inner = m.group(1)
        if not _is_legacy(inner):
            return m.group(0)
        inner = BR_RE.sub("\n", inner)
        inner = NBSP_RE.sub(" ", inner)
        inner = inner.replace(ZWJ, "").rstrip()
        inner = inner.replace('"', '&quot;')
        lang = _detect_language(unescape(inner))
        return f'<pre><code class="{lang}">{inner}\n</code></pre>'
    return P_CODE_RE.sub(repl, field_value)
```

Verified against the Schema Glossary `book` item with 6 unit tests: legacy-to-target conversion, idempotency, inline `<code>` untouched, no-op on non-legacy `<p><code>`, language detection across json / html / python / fallback, exact-shape match. The harness in `scripts/repair_template.py` drives audit through stage with this transform plugged in.

## Other transforms the same harness drives

One-liners showing the framework's reach. Same audit / snapshot / diff / stage / verify loop, different transformer.

**Strip brand suffix from `meta-title`:**

```python
def transform(v: str) -> str:
    return re.sub(r'\s*\|\s*Karpi Studio\s*$', '', v)
```

**Rename deprecated schema property `founders` to `founder`:**

```python
def transform(v: str) -> str:
    return re.sub(r'&quot;founders&quot;\s*:', '&quot;founder&quot;:', v)
```

**Rewrite old domain to new in `href` values:**

```python
def transform(v: str) -> str:
    return v.replace('href="https://oldsite.com', 'href="https://newsite.com')
```

**Correct double-encoded HTML entities:**

```python
def transform(v: str) -> str:
    return v.replace('&amp;amp;', '&amp;').replace('&amp;lt;', '&lt;').replace('&amp;gt;', '&gt;')
```

**Restore tables flattened by the bare-`<table>` ingest behavior:** more involved (detect a `<p>` whose content concatenates `<th>`-like sequences, parse cell text, rebuild as the embed-wrapped table from `webflow-richtext-tables.md`). Same harness, more complex transform.

## When NOT to use this pattern

- **Single-item fix.** Open in the Designer, edit by hand.
- **Content lives outside Webflow.** Use `push-pattern.md` to push from the source.
- **The transform requires editing markdown source.** Use `fix-pass-pattern.md`: edit markdown, regenerate HTML through `compact.py`, push.
- **The transform touches multiple fields per item.** Run multiple repair passes back to back, one field per pass. Easier to reason about and easier to revert.
- **The transform creates new content from external data.** Not a repair; use `push-pattern.md`.

## Multiple repairs in sequence

Never batch multiple unrelated repairs into one pass. One pass per logical shape change:

```
Pass 1: code blocks legacy -> round-trip-safe   (Schema Glossary Types + Terms)
Pass 2: brand suffix strip on meta-title        (Blog + AEOs + CROs)
Pass 3: founders -> founder rename              (Schema Glossary Types subset)
```

Each pass owns its progress file (`/tmp/repair_<pass>_progress.txt`) for resume safety. If pass 2 breaks mid-batch, you don't need to rerun pass 1.

If two passes target the same field on overlapping items, run pass A completely (audit + stage + human-publish + live verify) before starting pass B. Sequential composition beats parallel editing.
