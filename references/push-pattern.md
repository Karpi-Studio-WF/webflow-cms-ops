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

1. `<table>` tags are silently stripped. Convert tables to bullet lists before rendering.
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

Or use `scripts/push_template.py` — edit the CONFIG block and run directly.

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

## Publishing

PATCH updates go to the staged draft. To publish items to the live site:

- **Via Designer:** click Publish in the UI. Publishes all staged drafts for the site.
- **Via API:** `POST /v2/collections/{id}/items/publish` with `{"itemIds": [...]}`. Up to 100 item IDs per request.

The `.webflow.io` URL serves the last-published version of each item. If content looks stale on the live URL but correct in the editor, the item needs publishing.
