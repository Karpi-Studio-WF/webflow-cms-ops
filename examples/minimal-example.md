# Minimal Example: Push 10 Markdown Files to Webflow

End-to-end walkthrough of pushing content from a folder of markdown files to a Webflow CMS collection.

## Setup

```bash
pip3 install certifi markdown
```

## 1. Create a local SQLite staging DB

Store content in a DB before pushing. Even for 10 items, this pays off the first time you need to regenerate HTML, retry a failed push, or apply a fix pass.

```python
# setup_db.py
import sqlite3, os, re

conn = sqlite3.connect("content.db")
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS my_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE,
    webflow_id TEXT,
    body_md TEXT,
    body_html TEXT,
    meta_title TEXT,
    meta_description TEXT
)""")

for fname in os.listdir("articles"):
    if not fname.endswith(".md"):
        continue
    slug = fname[:-3]
    with open(f"articles/{fname}") as f:
        md = f.read()

    # Extract YAML frontmatter for meta title/description (if present)
    frontmatter_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', md, re.DOTALL)
    meta_title = meta_desc = ""
    if frontmatter_match:
        for line in frontmatter_match.group(1).split("\n"):
            if line.startswith("title:"):
                meta_title = line.split(":", 1)[1].strip().strip('"\'')
            elif line.startswith("description:"):
                meta_desc = line.split(":", 1)[1].strip().strip('"\'')

    c.execute(
        "INSERT OR REPLACE INTO my_items (slug, body_md, meta_title, meta_description) "
        "VALUES (?, ?, ?, ?)",
        (slug, md, meta_title, meta_desc)
    )

conn.commit()
conn.close()
print("DB seeded.")
```

## 2. Create CMS items in Webflow (first time only)

Webflow requires an existing item ID before you can PATCH. For first-time upload, POST to create and capture the returned IDs:

```python
# create_items.py
import sqlite3, json, time, urllib.request, ssl, certifi

API_TOKEN = "YOUR_TOKEN"
COLLECTION_ID = "YOUR_COLLECTION_ID"
ctx = ssl.create_default_context(cafile=certifi.where())

conn = sqlite3.connect("content.db")
c = conn.cursor()
c.execute("SELECT slug FROM my_items WHERE webflow_id IS NULL")
for (slug,) in c.fetchall():
    payload = {
        "fieldData": {
            "name": slug.replace("-", " ").title(),
            "slug": slug,
        },
        "isDraft": True,
    }
    req = urllib.request.Request(
        f"https://api.webflow.com/v2/collections/{COLLECTION_ID}/items",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, context=ctx) as resp:
        item = json.loads(resp.read())
    c.execute("UPDATE my_items SET webflow_id = ? WHERE slug = ?", (item["id"], slug))
    print(f"  created {slug}: {item['id']}")
    time.sleep(0.5)

conn.commit()
conn.close()
```

## 3. Generate compact HTML from markdown

```python
# regen_html.py
import sys, sqlite3
sys.path.insert(0, "../scripts")  # wherever compact.py lives
from compact import to_compact_html

conn = sqlite3.connect("content.db")
c = conn.cursor()
c.execute("SELECT id, body_md FROM my_items")
for fid, md in c.fetchall():
    html = to_compact_html(md)
    c.execute("UPDATE my_items SET body_html = ? WHERE id = ?", (html, fid))
conn.commit()
conn.close()
print("HTML regenerated.")
```

## 4. Push to Webflow

Copy `scripts/push_template.py` next to `content.db`, edit the CONFIG block:

```python
API_TOKEN = "YOUR_TOKEN"
COLLECTION_ID = "YOUR_COLLECTION_ID"
BODY_FIELD = "body"  # verify: GET one item, check fieldData keys
DB_PATH = "/absolute/path/to/content.db"
PROGRESS_FILE = "/tmp/example_push_progress.txt"
```

Run:

```bash
python3 push_template.py
```

Output:

```
10 items to push (0 already done, 10 total in DB)
  10/10: my-last-slug

Pushed: 10/10
Failed: 0
Skipped: 0

=== NEXT STEP: visual verification ===
...
```

## 5. Verify visually

Open any item in Webflow CMS editor. Confirm:

- Bullet lists render with bullets (not as plain text with dashes).
- Code blocks show with monospace formatting.
- Headings are visible and sections have content beneath them.

If sections look empty despite the push reporting success, the whitespace-between-tags bug is the likely cause. See `references/webflow-gotchas.md` entry #2. Double-check `regen_html.py` imports `to_compact_html`, not raw `markdown.markdown()`.

## 6. Publish (via Webflow Designer or API)

Items are staged as drafts. To publish:

- **Via Designer:** click Publish on the site.
- **Via API:** `POST /v2/collections/{id}/items/publish` with `{"itemIds": [...]}`.

Rendered pages at `<site>.webflow.io/<collection-slug>/<item-slug>` will then reflect the pushed content.

## That's it

You now have a pattern that scales from 10 items to 10,000. Every step is resume-safe, every HTML push protects against the known Webflow RichText parser bugs, and the local DB stays as your source of truth.

If you later need to run an editorial fix across all items (strip a phrase, swap a heading, remove a meta-content leak), see `references/fix-pass-pattern.md`.
