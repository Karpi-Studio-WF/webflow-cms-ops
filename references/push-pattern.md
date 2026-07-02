# Push Pattern: Bulk Content to Webflow CMS

Use this when pushing 20+ items from a local source (SQLite DB, markdown files, CSV) to a Webflow CMS collection.

For the non-negotiable principles (certifi, compact HTML, absolute paths, rate limit, resume, visual verify, no background agents), see the parent `SKILL.md`. This reference assumes you've read those.

## Before running

You need:

- Webflow API token with CMS read/write scope. Generate at Site Settings → Apps & Integrations → API Access.
- Collection ID — from the Designer URL (`?collection=...`) or `GET /v2/sites/{id}/collections`.
- **Exact** field slugs for this collection (NOT display names). For RichText body, the slug is often `body` but may be `body-2` depending on when the field was created. Verify by fetching one item and inspecting `fieldData` keys:

```python
import urllib.request, ssl, certifi, json
ctx = ssl.create_default_context(cafile=certifi.where())
req = urllib.request.Request(
    f"https://api.webflow.com/v2/collections/{COLLECTION_ID}/items?limit=1",
    headers={"Authorization": f"Bearer {API_TOKEN}", "Accept": "application/json"},
)
with urllib.request.urlopen(req, context=ctx) as resp:
    item = json.loads(resp.read())["items"][0]
    print(list(item["fieldData"].keys()))
```

## Step 1: Confirm scope

Count affected items before any push. Never push blindly.

```bash
sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM my_items WHERE webflow_id IS NOT NULL AND body_html IS NOT NULL"
```

If 0, stop and investigate. If surprisingly high or low, sanity-check before proceeding.

## Step 2: Regenerate HTML from source (if needed)

If content lives as markdown, regenerate HTML first. The Webflow RichText field has two known parser quirks (full diagnosis in `references/webflow-gotchas.md`):

1. Bare `<table>` tags render broken on the live page (flattened, or surviving but unstyled). Wrap tables in `<div data-rt-embed-type="true">...</div>` and make sure the site CSS targets tables inside the rich-text wrapper (see `references/webflow-richtext-tables.md`), or convert to bullet lists.
2. Whitespace between `<ul>`, `<li>`, `</ul>` silently drops list children. Compact HTML before pushing.

Use `scripts/compact.py`:

```python
import sys, sqlite3, re
sys.path.insert(0, "<path-to>/webflow-cms-ops/scripts")
from compact import to_compact_html

conn = sqlite3.connect(DB_PATH, timeout=30)
c = conn.cursor()
c.execute("SELECT id, body_md FROM my_items")
for fid, md in c.fetchall():
    c.execute("UPDATE my_items SET body_html = ? WHERE id = ?", (to_compact_html(md), fid))
conn.commit()
```

## Step 3: Push loop

Use this exact pattern. Every element exists to prevent a failure mode we have hit.

```python
import sqlite3, json, time, urllib.request, ssl, os, certifi

API_TOKEN = "<YOUR_TOKEN>"
COLLECTION_ID = "<YOUR_COLLECTION_ID>"
BODY_FIELD = "body"  # or body-2 — verify first
DB_PATH = "<ABSOLUTE_PATH_TO_DB>"
PROGRESS_FILE = "/tmp/webflow_push_progress.txt"

ctx = ssl.create_default_context(cafile=certifi.where())

done = set()
if os.path.exists(PROGRESS_FILE):
    with open(PROGRESS_FILE) as f:
        done = set(l.strip() for l in f if l.strip())

conn = sqlite3.connect(DB_PATH, timeout=30)
c = conn.cursor()
c.execute(
    "SELECT slug, webflow_id, body_html, meta_title, meta_description "
    "FROM my_items ORDER BY slug"
)
rows = [r for r in c.fetchall() if r[0] not in done]
print(f"{len(rows)} items to push ({len(done)} already done)")

pushed, failed = 0, []
for slug, wf_id, html, mt, md in rows:
    if not wf_id or not html or len(html) < 100:
        print(f"  SKIP {slug}: missing webflow_id or body too short")
        continue
    try:
        data = json.dumps({
            "fieldData": {
                BODY_FIELD: html,
                "meta-title": mt or "",
                "meta-description": md or "",
            }
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.webflow.com/v2/collections/{COLLECTION_ID}/items/{wf_id}",
            data=data,
            headers={
                "Authorization": f"Bearer {API_TOKEN}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="PATCH",
        )
        with urllib.request.urlopen(req, context=ctx) as resp:
            json.loads(resp.read().decode("utf-8"))
        pushed += 1
        with open(PROGRESS_FILE, "a") as f:
            f.write(slug + "\n")
        if pushed % 25 == 0 or pushed == len(rows):
            print(f"  {pushed}/{len(rows)}: {slug}")
        time.sleep(0.5)
    except Exception as e:
        print(f"  FAIL {slug}: {e}")
        failed.append(slug)

conn.close()
print(f"\nPushed {pushed}/{len(rows)}, failed {len(failed)}")
```

Or use `scripts/push_template.py` — edit the CONFIG block and run directly. The template additionally retries transient failures (429 rate limit, 5xx) with backoff honoring `Retry-After`, reads the token from the `WEBFLOW_API_TOKEN` env var, and can create missing items via POST (`CREATE_MISSING = True`).

## Step 4: Verify visually

Mandatory. See principle 6 in `SKILL.md`. If any of the 3 spot-check items show empty sections or missing content:

- Most likely cause: the whitespace-between-tags bug. See `references/webflow-gotchas.md#2-whitespace-between-listtags-drops-children`.
- Second most likely: wrong field slug. Confirm `BODY_FIELD` matches the collection.
- Third: content shorter than `MIN_HTML_LENGTH` got skipped. Check stdout for SKIP lines.

## Step 5: Report

Produce:

- Items attempted / pushed / failed / skipped (with slug + reason for each)
- Spot-check results (3 slugs + render confirmation)

## First-time upload (POST before PATCH)

The push pattern above uses PATCH, which requires existing item IDs. For first-time upload of a collection:

```python
payload = {
    "fieldData": {
        "name": display_name,
        "slug": slug,
        # other required fields
    },
    "isDraft": True,
}
req = urllib.request.Request(
    f"https://api.webflow.com/v2/collections/{COLLECTION_ID}/items",
    data=json.dumps(payload).encode("utf-8"),
    headers={...},
    method="POST",
)
with urllib.request.urlopen(req, context=ctx) as resp:
    item = json.loads(resp.read())
# Save item["id"] back to your DB as webflow_id for future PATCH calls
```

Then use the PATCH loop for all subsequent content updates.

`scripts/push_template.py` implements this: set `CREATE_MISSING = True` and rows without a `webflow_id` are POSTed as drafts, with the returned item ID written back to the DB so subsequent runs PATCH them.

## PATCHing multi-image fields

The PATCH examples above target flat fields: `meta-title`, `meta-description`, `body`. Multi-image fields are different — they store an array of image objects, each with its own metadata (`fileId`, `url`, `alt`, optionally dimensions and other attributes).

### The schema

A multi-image field's value is an array:

```json
[
  {"fileId": "abc123", "url": "https://uploads-ssl.webflow.com/...", "alt": "first image alt"},
  {"fileId": "def456", "url": "https://uploads-ssl.webflow.com/...", "alt": "second image alt"}
]
```

When you PATCH this field, you must send the WHOLE array — Webflow does not merge per-element. If you send only the items you want to update, the rest get deleted.

### The pattern: GET, modify, PATCH (preserve everything except your target field)

The safest update is a read-modify-write cycle that preserves every existing key on every image except the one you're changing. Use spread to guarantee preservation:

```python
# 1. GET the current item to read existing array
req = urllib.request.Request(
    f"https://api.webflow.com/v2/collections/{COLLECTION_ID}/items/{wf_id}",
    headers={"Authorization": f"Bearer {API_TOKEN}", "Accept": "application/json"},
)
with urllib.request.urlopen(req, context=ctx) as resp:
    item = json.loads(resp.read())

existing_images = item["fieldData"]["set-of-images"]  # adjust slug for your field

# 2. Build new array — spread each existing image, override only `alt`
new_images = []
for img in existing_images:
    file_id = img["fileId"]
    new_alt = new_alts_by_file_id.get(file_id, img.get("alt", ""))
    new_images.append({**img, "alt": new_alt})

# 3. PATCH with the rebuilt array (rest of PATCH as in Step 3 above)
payload = {"fieldData": {"set-of-images": new_images}}
```

Why the spread (`**img`) matters:

- **Preserves `fileId`.** Webflow uses `fileId` to identify the asset. A new or changed `fileId` may be treated as a new image and create a duplicate.
- **Preserves `url`.** Required by Webflow's validator.
- **Preserves any field we don't know about.** Webflow may add fields in the future; spread is forward-compatible.
- **Override happens left-to-right.** In `{**img, "alt": new_alt}`, the spread populates first, then `"alt"` overrides. This is the only key-override semantics that's safe across Python dict literal evaluations.

### Key by fileId, not by index

Webflow returns images in a stable order, but build your alt-text map keyed by `fileId`, not array index. If a future operator adds, deletes, or reorders an image, your index-based alts shift to the wrong images. `fileId` is stable.

```python
# In your alts data file, key by fileId:
new_alts_by_file_id = {
    "abc123": "Description of first image",
    "def456": "Description of second image",
}
```

### Single-image fields

Some collections have a single-image field (e.g., `main-image`, `thumbnail`), not multi-image. The shape is one object, not an array:

```json
{"fileId": "abc123", "url": "https://uploads-ssl.webflow.com/...", "alt": "single image alt"}
```

Same spread pattern, no loop:

```python
existing_main = item["fieldData"]["main-image"]
new_main = {**existing_main, "alt": new_alt_for_main}
payload = {"fieldData": {"main-image": new_main}}
```

### What if a fileId in your data is missing from the current item?

Skip it with a warning. The image was probably removed from the item after your data was generated:

```python
existing_file_ids = {img["fileId"] for img in existing_images}
missing = [fid for fid in new_alts_by_file_id if fid not in existing_file_ids]
if missing:
    print(f"  WARN {slug}: {len(missing)} fileIds not in item, skipping: {missing}")
```

### Verify visually after push

Same rule as flat-field PATCHes (see principle #6 in `SKILL.md`). The Data API GET will echo back what you sent. Open at least 3 items in the Webflow editor and confirm the alt text appears on the right images.

### Generating the alt text in the first place

If you're populating these fields from scratch (no existing alts), the inputs come from a vision-batch job. See `references/vision-pipeline.md` for the full four-phase pipeline (download, normalize, vision, push).

## Publishing

PATCH updates go to the staged draft. To publish items to the live site:

- **Via Designer:** click Publish in the UI. Publishes all staged drafts for the site.
- **Via API:** `POST /v2/collections/{id}/items/publish` with `{"itemIds": [...]}`. Up to 100 item IDs per request.

The `.webflow.io` URL serves the last-published version of each item. If content looks stale on the live URL but correct in the editor, the item needs publishing.
