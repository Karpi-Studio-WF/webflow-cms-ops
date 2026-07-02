# Fix Pass Pattern: Editorial Sweep Across a Collection

Use this when you discover a systemic content issue post-publish — a formulaic phrase, a meta-content leak, a rendering bug, a deprecated reference, a placeholder brand name — that affects 10+ items across a Webflow CMS collection.

For the non-negotiable principles, see parent `SKILL.md`. For the push mechanics used in step 5, see `references/push-pattern.md`.

## Why a dedicated pattern

Editorial fixes at scale look like they should be "write a regex, apply, push." They aren't. A fix applied at scale without the right discipline will:

- Change content where it shouldn't (regex edge cases you didn't consider).
- Corrupt content inside code blocks where the pattern happens to match.
- Fail mid-batch with no resume path.
- Produce a non-idempotent result so rerunning amplifies the damage.
- Push changes before you visually verify a sample.

The pattern below prevents all of these.

## The six-step pattern

### Step 1: Identify scope

Count first. Always.

```python
import sqlite3
conn = sqlite3.connect(DB_PATH, timeout=30)
c = conn.cursor()
c.execute("SELECT COUNT(*) FROM my_items WHERE body_md LIKE '%problem-pattern%'")
print(f"Affected: {c.fetchone()[0]}")
c.execute("SELECT slug FROM my_items WHERE body_md LIKE '%problem-pattern%' LIMIT 5")
for (s,) in c.fetchall():
    print(f"  {s}")
conn.close()
```

If the count is surprisingly high or low, stop and investigate before writing the transform.

### Step 2: Write the transform as a pure function

```python
def fix(md):
    """Takes markdown, returns markdown. No side effects."""
    return md.replace("old phrase", "new phrase")
```

Rules for the transform:

- **Pure.** No file I/O, no DB calls, no API calls.
- **Testable.** Easy to call on 3-5 sample strings.
- **Conservative.** Protect content inside fenced code blocks (` ``` `), inline code, and block tags where whitespace matters. Use `\b` word boundaries over broad substitutions.
- **Idempotent.** Running `fix()` twice produces the same output as running it once.

Test before applying:

```python
c.execute("SELECT slug, body_md FROM my_items WHERE body_md LIKE '%problem-pattern%' LIMIT 3")
for slug, md in c.fetchall():
    print(f"=== {slug} ===")
    print(f"BEFORE: {md[:500]}")
    print(f"AFTER:  {fix(md)[:500]}")
```

Verify each sample's rewrite is correct. If anything looks wrong, revise the transform before touching the DB.

### Step 3: Apply the transform

```python
conn = sqlite3.connect(DB_PATH, timeout=30)
c = conn.cursor()
c.execute("SELECT id, slug, body_md FROM my_items WHERE body_md LIKE '%problem-pattern%'")
touched = []
for fid, slug, md in c.fetchall():
    new_md = fix(md)
    if new_md != md:
        c.execute("UPDATE my_items SET body_md = ? WHERE id = ?", (new_md, fid))
        touched.append(slug)
conn.commit()
print(f"Updated {len(touched)} items")

with open("/tmp/fix_touched.txt", "w") as f:
    for s in touched:
        f.write(s + "\n")
conn.close()
```

Key details:

- **Only write when `new_md != md`.** Prevents re-touching items the transform didn't actually change.
- **Track touched slugs in `/tmp/fix_touched.txt`.** Next steps read from this file.
- **Commit per-pass, not per-row.** One commit at the end keeps the DB fast.

### Step 4: Regenerate HTML for touched items only

```python
import sys, sqlite3
sys.path.insert(0, "<path-to>/webflow-cms-ops/scripts")
from compact import to_compact_html  # strips frontmatter, renders, compacts

with open("/tmp/fix_touched.txt") as f:
    touched_slugs = [l.strip() for l in f if l.strip()]

conn = sqlite3.connect(DB_PATH, timeout=30)
c = conn.cursor()
for slug in touched_slugs:
    c.execute("SELECT id, body_md FROM my_items WHERE slug = ?", (slug,))
    row = c.fetchone()
    if not row: continue
    fid, md = row
    c.execute("UPDATE my_items SET body_html = ? WHERE id = ?", (to_compact_html(md), fid))
conn.commit()
conn.close()
print(f"HTML regenerated for {len(touched_slugs)} items")
```

Regen only touched items. Full corpus regen is wasteful and slow.

### Step 5: Push to Webflow

Follow `references/push-pattern.md` Step 3. Filter to only slugs in `/tmp/fix_touched.txt`. Use a separate progress file for the fix push: `/tmp/fix_push_progress.txt`.

### Step 6: Spot-check

Pick 3-5 slugs from `/tmp/fix_touched.txt` at random and verify across three layers:

1. **DB:** `body_md` shows the expected content (the transform ran correctly).
2. **Webflow CMS editor:** the item renders as expected (not just the API GET — open the item in the editor or fetch the live page).
3. **Live page:** rendered HTML shows the change end-to-end (requires publish step).

If the editor or live page shows empty sections, the whitespace-between-tags bug is the most likely cause. See `references/webflow-gotchas.md#2-whitespace-between-listtags-drops-children`.

## Report template

```
=== Fix Pass Report ===
Pattern:       <description of problem>
Transform:     <description of fix>
Scope:         <N> items identified
Touched:       <N> items modified in DB
HTML regen:    <N> items regenerated
Pushed:        <N>/<N> to Webflow (0 failures expected)
Spot-checks:   <3 slugs>: all rendered correctly
STATUS:        CLEAN | NEEDS REVIEW
```

## Alt text on images inside a RichText body

Alt text lives in two different places on a Webflow item, and they need different treatment:

- **Image FIELDS** (main-image, thumbnail, set-of-images galleries): the alt is metadata on the field value. Use the read-modify-write PATCH in `references/push-pattern.md#patching-multi-image-fields` — this fix-pass pattern does not apply.
- **`<img>` tags embedded in the body markup**: the alt is just an attribute in the content. That makes it an ordinary fix pass — this section.

The transform depends on how images appear in `body_md`:

```python
# Markdown image syntax: ![old alt](https://.../hero.png)
# HTML img tags in the source: <img src="https://.../hero.png" alt="old alt">
# Either way, key the new alts by src URL (or a stable filename suffix),
# never by position — reordered images would shift positional alts.
import re

NEW_ALTS = {  # src substring -> new alt
    "hero.png": "Dashboard overview with the export button highlighted",
    "step-2.png": "The collection settings panel, slug field selected",
}

def fix(md):
    def md_img(m):
        alt, src = m.group(1), m.group(2)
        for key, new_alt in NEW_ALTS.items():
            if key in src:
                return f"![{new_alt}]({src})"
        return m.group(0)
    md = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)[^)]*\)", md_img, md)

    def html_img(m):
        tag = m.group(0)
        src = re.search(r'src="([^"]*)"', tag)
        if not src:
            return tag
        for key, new_alt in NEW_ALTS.items():
            if key in src.group(1):
                if 'alt="' in tag:
                    return re.sub(r'alt="[^"]*"', f'alt="{new_alt}"', tag)
                return tag[:-1] + f' alt="{new_alt}">'
        return tag
    return re.sub(r"<img\b[^>]*>", html_img, md)
```

The usual transform rules apply unchanged: pure, idempotent (keyed replacement satisfies this — running twice writes the same alt), conservative (images referenced inside fenced code blocks will also match; if your corpus has any, protect fenced regions first). Then continue with steps 3–6 as normal: apply to `body_md`, regenerate HTML for touched slugs, push, spot-check. On the live page, confirm the alt landed by inspecting the rendered `<img>` element — alt text is invisible in a normal visual check.

## When NOT to use this pattern

- **Single-item fixes.** Open the item in the Webflow editor and fix manually.
- **Cross-collection fixes.** Run a separate pass per collection. Don't batch.
- **Fact errors.** If the transform changes factual claims, go through a research phase first. Don't push unverified facts at scale.
- **Structural changes to the collection schema** (renaming fields, changing types). That's Designer work.

## Multiple passes in sequence

Never batch multiple unrelated fixes into one pass. One pass per logical issue:

```
Pass 1: strip disclaimer phrases           (scope: ~50 items)
Pass 2: convert em dashes to commas        (scope: ~15 items)
Pass 3: fix heading doubling               (scope: ~200 items)
Pass 4: rewrite formulaic openers          (scope: ~200 items)
```

Each pass owns its `/tmp/<pass-name>_progress.txt` for resume safety. If pass 3 breaks mid-push, you don't need to rerun passes 1 and 2.

If passes 3 and 4 both touch the same slugs, run pass 3 completely (DB + HTML + push + spot-check) before starting pass 4. Sequential composition beats parallel editing.

## Idempotence check

Before running a pass on production content, verify the transform is idempotent on a sample:

```python
sample = "A string containing the problem-pattern and other content."
assert fix(fix(sample)) == fix(sample), "Transform is not idempotent"
```

If this fails, the transform changes its own output on repeat application. Fix the regex before touching the DB.
