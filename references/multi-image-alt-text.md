# Multi-Image Alt Text — End-to-End Pattern + Local Runbook (Webflow)

**Status:** Validated — first production run 2026-07-24 (a duplicated dealer site, 8 items / 34 gallery images, 0 write failures).
**Version:** 1.0
**Last updated:** 2026-07-24
**Applies to:** any Webflow CMS collection with a **Multi-image** field (gallery / "set of images") — or a single **Image** field — whose images need alt text.
**Two ways to read this doc:** sections 1–3 are the *shareable spec* (hand them to a reviewer to approve the approach); sections 4 onward are the *copy-paste runbook* (run it locally, unchanged, on any project by editing one config block).

This pattern follows the skill's eight principles (see `SKILL.md`): `certifi` SSL, 0.5s rate limiting, resume-safe progress, absolute paths, and visual verification. It is the end-to-end, runnable companion to `references/vision-pipeline.md` (which covers vision batching in general) and `references/push-pattern.md#patching-multi-image-fields` (which covers the field PATCH schema).

---

## 1. What this does

Adds descriptive alt text to every image inside a Webflow **Multi-image** field, across many CMS items, **without re-uploading, replacing, or reordering any image.** Only a small config block changes per project.

The key idea: an image in a Multi-image field is **a reference, not a file.** Webflow stores it as a small object — `fileId` + `url` + `alt` — pointing at an asset already hosted on Webflow. This pattern reads those references, generates an `alt` for each by **looking at the actual photo**, and writes the same list back with only the `alt` filled in. The image files are never touched.

## 2. Guarantees (what a reviewer can rely on)

- **Photos are never re-uploaded or replaced.** Only the `alt` metadata changes.
- **Order is preserved.** Each image's position is recorded and rebuilt in the same order.
- **Identity is preserved.** Each image's `fileId` and `url` are carried through unchanged — no duplicates, no rejected writes.
- **Nothing is written before human review** (Step 4 is an approval gate).
- **Resume-safe.** A crash mid-run resumes where it stopped; no image is written twice.
- **Rate-limited** (0.5s between calls ≈ 120 req/min, under Webflow's 150/min).
- **Reversible.** The pull stores a snapshot of the original arrays; reverting is symmetric because only `alt` ever changed.
- **Verified against the live CMS**, not just the API echo.

## 3. Prerequisites (per project)

| Item | Notes |
|---|---|
| Webflow Data API token | **Scopes:** CMS **read + write**, Assets **read + write**, Sites **read + write**. (CMS write performs the field update; Assets read/write covers asset metadata and optional asset-level alt; Sites read/write covers listing the site and publishing.) Supplied via an environment variable — never hardcoded, never committed. **Revoke it after the run.** |
| Anthropic API key | For the vision step — a script calls Claude to caption each image. Set `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` (any current Claude vision model). Cost is trivial (a few dozen small images). Skip only if you caption by hand or via another tool. |
| Network egress to the asset CDN | The machine running the scripts must reach Webflow's **asset CDN** to download image bytes — hosts like `uploads-ssl.webflow.com` and `*.website-files.com` (e.g. `cdn.prod.website-files.com`). A normal laptop reaches these fine. In a **locked-down / proxied sandbox** they are often blocked (Step 2 fails with a `403` at the proxy even though `api.webflow.com` works) — a token scope change does **not** fix that; it is a network-policy block. If you can't allow-list the host, run this locally, fetch images server-side (e.g. a Webflow MCP asset-preview), or supply them from a folder. |
| Python 3.9+ and deps | `pip3 install certifi anthropic`. |
| IDs to target | Site ID, collection ID, and the Multi-image field **slug** — discover them in Step 0. |

---

## 4. Setup (one-time)

```bash
pip3 install certifi anthropic
mkdir -p ~/wf-alt-text && cd ~/wf-alt-text     # scripts + gallery.db live here

# secrets + config — do NOT commit these
export WF_TOKEN="paste-your-webflow-data-api-token"      # scopes: CMS r/w, Assets r/w, Sites r/w
export ANTHROPIC_API_KEY="paste-your-anthropic-key"
export ANTHROPIC_MODEL="paste-a-current-claude-vision-model-id"

# project config — fill these in after Step 0
export WF_SITE_ID="your-site-id"
export WF_COLLECTION_ID="your-collection-id"
export WF_FIELD_SLUG="your-multi-image-field-slug"       # e.g. other-images, gallery, images
export ITEM_KIND="product"                               # captioning hint: "product", "vehicle", "property", ...
```

Save each script below into `~/wf-alt-text/` and run them in order. Every script derives its paths from its own location, so it is safe to run from any working directory.

---

## Step 0 — Discover your IDs · `0_discover.py`

Lists your sites, then the chosen site's collections, then a collection's fields — flagging every **Image** and **MultiImage** field so you can read off the exact `WF_COLLECTION_ID` and `WF_FIELD_SLUG`.

```python
#!/usr/bin/env python3
"""List sites -> collections -> fields; flags Image / MultiImage fields."""
import os, json, ssl, urllib.request, certifi

WF_TOKEN = os.environ["WF_TOKEN"]
SITE     = os.environ.get("WF_SITE_ID", "").strip()
COLL     = os.environ.get("WF_COLLECTION_ID", "").strip()
ctx = ssl.create_default_context(cafile=certifi.where())

def get(path):
    req = urllib.request.Request("https://api.webflow.com/v2" + path,
        headers={"Authorization": f"Bearer {WF_TOKEN}", "accept": "application/json"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        return json.load(r)

if not SITE:
    for s in get("/sites")["sites"]:
        print(f"SITE  {s['id']}  {s['displayName']}  ({s.get('shortName','')})")
    print("\nSet WF_SITE_ID and rerun.")
elif not COLL:
    for c in get(f"/sites/{SITE}/collections")["collections"]:
        print(f"COLLECTION  {c['id']}  {c['displayName']}  (slug: {c['slug']})")
    print("\nSet WF_COLLECTION_ID and rerun.")
else:
    for f in get(f"/collections/{COLL}")["fields"]:
        mark = "  <-- IMAGE FIELD" if f["type"] in ("Image", "MultiImage") else ""
        print(f"{f['type']:<12} slug: {f['slug']:<24} {f['displayName']}{mark}")
    print("\nUse the MultiImage field's slug as WF_FIELD_SLUG (or an Image field for a single hero).")
```

Run it up to three times, filling in one env var each pass: `python3 0_discover.py`.

---

## Step 1 — Pull the field into SQLite · `1_pull.py` · read-only

Reads every item in the collection and writes **one row per image**, recording the item, the image's `fileId`/`url`, and its **position** in the gallery. Also snapshots the raw arrays for rollback. Webflow is not modified.

```python
#!/usr/bin/env python3
import os, json, ssl, sqlite3, time, urllib.request, certifi

WF_TOKEN      = os.environ["WF_TOKEN"]
COLLECTION_ID = os.environ["WF_COLLECTION_ID"]
FIELD_SLUG    = os.environ["WF_FIELD_SLUG"]
HERE          = os.path.dirname(os.path.abspath(__file__))
DB            = os.path.join(HERE, "gallery.db")
BASE          = f"https://api.webflow.com/v2/collections/{COLLECTION_ID}/items"
ctx = ssl.create_default_context(cafile=certifi.where())

def api_get(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {WF_TOKEN}",
                                               "accept": "application/json"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        return json.load(r)

items, offset = [], 0
while True:
    data  = api_get(f"{BASE}?limit=100&offset={offset}")
    batch = data.get("items", [])
    items.extend(batch)
    total = data.get("pagination", {}).get("total", len(items))
    offset += len(batch)
    if offset >= total or not batch:
        break
    time.sleep(0.5)

con = sqlite3.connect(DB)
con.execute("""CREATE TABLE IF NOT EXISTS gallery_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT, item_slug TEXT, item_name TEXT,
    position INTEGER, file_id TEXT, url TEXT,
    current_alt TEXT, generated_alt TEXT, pushed INTEGER DEFAULT 0,
    UNIQUE(item_id, file_id))""")
con.execute("""CREATE TABLE IF NOT EXISTS item_snapshot (
    item_id TEXT PRIMARY KEY, item_slug TEXT, item_name TEXT,
    is_draft INTEGER, raw_field TEXT)""")

rows = items_with = 0
for it in items:
    fd   = it.get("fieldData", {})
    val  = fd.get(FIELD_SLUG)
    imgs = val if isinstance(val, list) else ([val] if val else [])   # supports single Image too
    if not imgs:
        continue
    items_with += 1
    con.execute("INSERT OR REPLACE INTO item_snapshot VALUES (?,?,?,?,?)",
                (it["id"], fd.get("slug"), fd.get("name"),
                 1 if it.get("isDraft") else 0, json.dumps(val)))
    for pos, img in enumerate(imgs):
        con.execute("""INSERT OR IGNORE INTO gallery_images
            (item_id,item_slug,item_name,position,file_id,url,current_alt)
            VALUES (?,?,?,?,?,?,?)""",
            (it["id"], fd.get("slug"), fd.get("name"), pos,
             img.get("fileId"), img.get("url"), img.get("alt")))
        rows += 1
con.commit()
print(f"Items fetched: {len(items)} | with '{FIELD_SLUG}': {items_with} | image rows: {rows}")
for r in con.execute("SELECT item_name, COUNT(*) FROM gallery_images GROUP BY item_id ORDER BY item_name"):
    print(f"  {r[0]:<40} {r[1]} imgs")
con.close()
```

Run: `python3 1_pull.py`. Note the image-row count — that's your batch size.

---

## Step 2 — Download + caption

### 2a. Download the image files · `2a_download.py`

```python
#!/usr/bin/env python3
import os, ssl, sqlite3, urllib.request, certifi

HERE = os.path.dirname(os.path.abspath(__file__))
DB, OUT = os.path.join(HERE, "gallery.db"), os.path.join(HERE, "binaries")
os.makedirs(OUT, exist_ok=True)
ctx = ssl.create_default_context(cafile=certifi.where())

def ext_of(head):
    h = head.hex()
    if h.startswith("ffd8ff"):   return "jpg"
    if h.startswith("89504e47"): return "png"
    if h.startswith("52494646"): return "webp"
    if "66747970" in h and "617669" in h: return "avif"
    return "bin"

con  = sqlite3.connect(DB)
rows = con.execute("SELECT file_id,url,item_slug,position FROM gallery_images ORDER BY item_slug,position").fetchall()
con.close()

summary = {}
for file_id, url, slug, pos in rows:
    existing = [f for f in os.listdir(OUT) if f.startswith(file_id + ".")]
    if existing:
        path = os.path.join(OUT, existing[0])
    else:
        req  = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, context=ctx, timeout=90).read()
        path = os.path.join(OUT, f"{file_id}.{ext_of(data[:16])}")
        open(path, "wb").write(data)
    e = path.rsplit(".", 1)[-1]
    summary[e] = summary.get(e, 0) + 1
    print(f"{slug:<40} pos{pos}  {e:>4}  {os.path.getsize(path)//1024:>5} KB")
print("Formats:", summary, "| files:", len(os.listdir(OUT)))
```

Run: `python3 2a_download.py`. If `Formats` shows any **`avif`**, convert them first (see Troubleshooting — Anthropic's vision API needs jpg/png/webp/gif).

### 2b. Caption each image with Claude · `2b_caption.py`

```python
#!/usr/bin/env python3
import os, sqlite3, base64
from anthropic import Anthropic

HERE = os.path.dirname(os.path.abspath(__file__))
DB, OUT   = os.path.join(HERE, "gallery.db"), os.path.join(HERE, "binaries")
MODEL     = os.environ["ANTHROPIC_MODEL"]
ITEM_KIND = os.environ.get("ITEM_KIND", "product")
client    = Anthropic()  # reads ANTHROPIC_API_KEY

MEDIA = {"jpg":"image/jpeg","jpeg":"image/jpeg","png":"image/png","webp":"image/webp","gif":"image/gif"}
PROMPT = (
    "Write concise, factual alt text for this photo on a {kind} website.\n"
    "Context: the image belongs to the item named '{name}'.\n"
    "Describe what is actually visible — for a product/vehicle include make/model, colour, and the "
    "camera angle (front, side, rear, three-quarter, dashboard, detail).\n"
    "Rules: max 125 characters; no 'image of'/'photo of' prefix; specific, not generic.\n"
    "Return ONLY the alt text, nothing else."
)

con  = sqlite3.connect(DB)
todo = con.execute("SELECT id, item_name, file_id FROM gallery_images WHERE generated_alt IS NULL OR generated_alt=''").fetchall()
print(f"{len(todo)} images to caption")
for rid, name, file_id in todo:
    files = [f for f in os.listdir(OUT) if f.startswith(file_id + ".")]
    if not files:
        print(f"  MISSING file for {file_id}"); continue
    ext   = files[0].rsplit(".", 1)[-1].lower()
    media = MEDIA.get(ext)
    if not media:
        print(f"  SKIP {file_id}: unsupported .{ext}"); continue
    b64 = base64.standard_b64encode(open(os.path.join(OUT, files[0]), "rb").read()).decode()
    msg = client.messages.create(model=MODEL, max_tokens=120, messages=[{"role":"user","content":[
        {"type":"image","source":{"type":"base64","media_type":media,"data":b64}},
        {"type":"text","text":PROMPT.format(kind=ITEM_KIND, name=name)}]}])
    alt = msg.content[0].text.strip().strip('"').strip()
    con.execute("UPDATE gallery_images SET generated_alt=? WHERE id=?", (alt, rid)); con.commit()
    print(f"  {name[:22]:<22} -> {alt}")
con.close()
```

Run: `python3 2b_caption.py`. **Resume-safe** — rerun and it only processes rows still missing alt.
*(No Anthropic key? Caption by hand instead: write each alt into the `generated_alt` column, e.g. via the CSV round-trip in Step 3.)*

---

## Step 3 — Review · `3_report.py` · the approval gate

Nothing has touched Webflow's writable state yet (only the read-only pull). Build the report, read every line, approve or edit.

```python
#!/usr/bin/env python3
import os, sqlite3, csv
HERE = os.path.dirname(os.path.abspath(__file__))
con  = sqlite3.connect(os.path.join(HERE, "gallery.db"))
rows = con.execute("SELECT item_name,item_slug,position,file_id,url,generated_alt FROM gallery_images ORDER BY item_slug,position").fetchall()
con.close()
with open(os.path.join(HERE, "report.md"), "w") as f:
    f.write("# Alt-text review\n\n| Item | Pos | File | Proposed alt | Len |\n|---|--:|---|---|--:|\n")
    for name, slug, pos, fid, url, alt in rows:
        f.write(f"| {name} | {pos} | {url.rsplit('/',1)[-1][:28]} | {alt or ''} | {len(alt or '')} |\n")
with open(os.path.join(HERE, "report.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["file_id","item_name","position","proposed_alt"])
    for name, slug, pos, fid, url, alt in rows:
        w.writerow([fid, name, pos, alt or ""])
print(f"Wrote report.md and report.csv ({len(rows)} rows)")
```

Run `python3 3_report.py`, open `report.md`, read every line. **To edit an alt:** change the `proposed_alt` column in `report.csv`, then run the importer once and regenerate the report.

```python
# 3b_import_edits.py  (only if you edited report.csv)
import os, sqlite3, csv
HERE = os.path.dirname(os.path.abspath(__file__))
con  = sqlite3.connect(os.path.join(HERE, "gallery.db"))
for row in csv.DictReader(open(os.path.join(HERE, "report.csv"))):
    con.execute("UPDATE gallery_images SET generated_alt=? WHERE file_id=?", (row["proposed_alt"].strip(), row["file_id"]))
con.commit(); con.close(); print("edits imported")
```

---

## Step 4 — Write the alt back · `4_push.py` · the only write step

For each item it re-reads the **live** array, rebuilds it in `position` order, and overrides **only** `alt`. Resume-safe (`pushed` flag) and rate-limited.

```python
#!/usr/bin/env python3
import os, json, ssl, sqlite3, time, urllib.request, certifi

WF_TOKEN      = os.environ["WF_TOKEN"]
COLLECTION_ID = os.environ["WF_COLLECTION_ID"]
FIELD_SLUG    = os.environ["WF_FIELD_SLUG"]
HERE = os.path.dirname(os.path.abspath(__file__))
ctx  = ssl.create_default_context(cafile=certifi.where())

def api(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req  = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {WF_TOKEN}", "accept": "application/json", "content-type": "application/json"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        return json.load(r)

con      = sqlite3.connect(os.path.join(HERE, "gallery.db"))
item_ids = [r[0] for r in con.execute(
    "SELECT DISTINCT item_id FROM gallery_images WHERE generated_alt IS NOT NULL AND generated_alt!='' AND pushed=0")]
print(f"{len(item_ids)} items to update")
for item_id in item_ids:
    amap = {fid: alt for fid, alt in con.execute(
        "SELECT file_id, generated_alt FROM gallery_images WHERE item_id=? AND generated_alt IS NOT NULL AND generated_alt!=''", (item_id,))}
    it   = api("GET", f"https://api.webflow.com/v2/collections/{COLLECTION_ID}/items/{item_id}")
    val  = it["fieldData"].get(FIELD_SLUG)
    if isinstance(val, list):
        # CRITICAL: spread each existing image (keep fileId+url+order), override ONLY alt
        new_val = [{**img, "alt": amap.get(img.get("fileId"), img.get("alt", ""))} for img in val]
    elif val:                                            # single Image field
        new_val = {**val, "alt": amap.get(val.get("fileId"), val.get("alt", ""))}
    else:
        print(f"  skip {item_id}: field empty on live item"); continue
    api("PATCH", f"https://api.webflow.com/v2/collections/{COLLECTION_ID}/items/{item_id}",
        {"fieldData": {FIELD_SLUG: new_val}})
    con.execute("UPDATE gallery_images SET pushed=1 WHERE item_id=?", (item_id,)); con.commit()
    print(f"  pushed {item_id}")
    time.sleep(0.5)
con.close()
```

Run: `python3 4_push.py`.

---

## Step 5 — Publish · `5_publish.py` (and `5b_publish_site.py` fallback)

```python
#!/usr/bin/env python3
import os, json, ssl, sqlite3, urllib.request, certifi
WF_TOKEN, COLLECTION_ID = os.environ["WF_TOKEN"], os.environ["WF_COLLECTION_ID"]
HERE = os.path.dirname(os.path.abspath(__file__))
ctx  = ssl.create_default_context(cafile=certifi.where())
con  = sqlite3.connect(os.path.join(HERE, "gallery.db"))
ids = [r[0] for r in con.execute("""SELECT DISTINCT g.item_id FROM gallery_images g
    JOIN item_snapshot s ON s.item_id=g.item_id WHERE g.pushed=1 AND s.is_draft=0""")]
drafts = [r[0] for r in con.execute("""SELECT DISTINCT g.item_id FROM gallery_images g
    JOIN item_snapshot s ON s.item_id=g.item_id WHERE g.pushed=1 AND s.is_draft=1""")]
con.close()
if ids:
    req = urllib.request.Request(f"https://api.webflow.com/v2/collections/{COLLECTION_ID}/items/publish",
        data=json.dumps({"itemIds": ids}).encode(), method="POST",
        headers={"Authorization": f"Bearer {WF_TOKEN}", "accept":"application/json","content-type":"application/json"})
    print(json.loads(urllib.request.urlopen(req, context=ctx, timeout=60).read().decode()))
print(f"Published {len(ids)} items." + (f"  ({len(drafts)} drafts left unpublished.)" if drafts else ""))
```

Run: `python3 5_publish.py`. Webflow never publishes drafts — draft items keep their new alt saved but stay draft until you publish them yourself.

If item-publish fails with **`Invalid locale <id>`** (see Troubleshooting — happens on duplicated sites), use the site-level fallback instead:

```python
#!/usr/bin/env python3
# 5b_publish_site.py
import os, json, ssl, urllib.request, certifi
WF_TOKEN, SITE_ID = os.environ["WF_TOKEN"], os.environ["WF_SITE_ID"]
ctx  = ssl.create_default_context(cafile=certifi.where())
body = {"publishToWebflowSubdomain": True}   # add "customDomains": ["www.example.com"] for production
req  = urllib.request.Request(f"https://api.webflow.com/v2/sites/{SITE_ID}/publish",
    data=json.dumps(body).encode(), method="POST",
    headers={"Authorization": f"Bearer {WF_TOKEN}", "accept":"application/json","content-type":"application/json"})
print("HTTP", urllib.request.urlopen(req, context=ctx, timeout=60).status)   # 202 = accepted
```

Site publish pushes **all** staged site content and returns `202` (async) — confirm nothing else is half-finished first.

---

## Step 6 — Verify & clean up · `verify.py`

Confirm the alt is actually stored live, then revoke the token.

```python
#!/usr/bin/env python3
import os, json, ssl, time, urllib.request, certifi
WF_TOKEN, COLLECTION_ID, FIELD_SLUG = os.environ["WF_TOKEN"], os.environ["WF_COLLECTION_ID"], os.environ["WF_FIELD_SLUG"]
BASE = f"https://api.webflow.com/v2/collections/{COLLECTION_ID}/items"
ctx  = ssl.create_default_context(cafile=certifi.where())
def get(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {WF_TOKEN}", "accept":"application/json"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r: return json.load(r)
items, offset = [], 0
while True:
    d = get(f"{BASE}?limit=100&offset={offset}"); b = d.get("items", []); items += b
    offset += len(b)
    if offset >= d.get("pagination",{}).get("total", len(items)) or not b: break
    time.sleep(0.5)
ti = ta = 0
for it in items:
    val = it.get("fieldData", {}).get(FIELD_SLUG)
    imgs = val if isinstance(val, list) else ([val] if val else [])
    if not imgs: continue
    w = sum(1 for i in imgs if (i.get("alt") or "").strip()); ti += len(imgs); ta += w
    tag = "DRAFT" if it.get("isDraft") else "live"
    print(f"[{tag:>5}] {it['fieldData'].get('name'):<36} {w}/{len(imgs)} alt  pub:{(it.get('lastPublished') or 'never')[:16]}")
print(f"=== {ta}/{ti} images have alt ===")
```

Run `python3 verify.py`. Then:
- Open **3+ items** in the Webflow editor (or the live detail page) and confirm the alt shows on the right images. The API echoes back whatever you send — only a visual check proves the live result. (If the collection's **detail template isn't published**, no page renders the gallery — see Troubleshooting; the GET above is then your proof.)
- **Revoke / regenerate the Webflow API token.**
- Keep `gallery.db` — `item_snapshot.raw_field` is your rollback.

---

## SQLite schema (created by Step 1)

```sql
CREATE TABLE gallery_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT, item_slug TEXT, item_name TEXT,
    position INTEGER,       -- index in the array — preserves gallery order
    file_id TEXT,           -- Webflow asset ID — STABLE, never changed
    url TEXT,               -- asset URL — preserved exactly (validator requires it)
    current_alt TEXT,       -- existing alt (often empty)
    generated_alt TEXT,     -- the new alt (Step 2)
    pushed INTEGER DEFAULT 0 -- resume-safe flag (Step 4)
);
CREATE TABLE item_snapshot (item_id TEXT PRIMARY KEY, item_slug TEXT, item_name TEXT, is_draft INTEGER, raw_field TEXT);
```

## The one critical safety rule

Rebuild the array — **never replace an image object wholesale.** Spread the existing image, override only `alt`:

```python
new_val = [{**img, "alt": amap.get(img["fileId"], img.get("alt", ""))} for img in existing]  # in position order
```

- Changing/dropping `fileId` → Webflow may create a **duplicate**. Dropping `url` → the write **fails validation**.
- Rebuild in `position` order → the gallery sequence stays identical.
- Key the alt lookup by `fileId`, **not array index** (stable if images are later added/removed/reordered).
- A **single Image** field is the same rule without the loop: `new_val = {**existing, "alt": ...}`.

## Scaling (by batch size)

| Images | Approach |
|---|---|
| < 100 | Caption inline, one pass (the scripts above). |
| 100–800 | Split into chunks; caption in parallel workers; merge. See `references/vision-pipeline.md` Pattern B. |
| > 800 | Hand off to a dedicated worker session. See `references/session-handoff.md`. |

Only Step 2 changes with scale; pull/push/publish are identical.

## Rollback

`item_snapshot.raw_field` holds each item's original field value. Because only `alt` ever changed, reverting is symmetric — push the stored snapshot back through the same PATCH. No image, ID, URL, or order is ever at risk.

---

## Troubleshooting & gotchas

- **`avif` in the download formats.** Anthropic's vision API accepts jpg/png/webp/gif, not avif. Convert first:
  ```bash
  pip3 install pillow pillow-avif-plugin
  python3 - <<'PY'
  import os, pillow_avif  # noqa: registers AVIF
  from PIL import Image
  d = "binaries"
  for f in os.listdir(d):
      if f.endswith(".avif"):
          Image.open(os.path.join(d, f)).convert("RGB").save(os.path.join(d, f[:-5] + ".jpg"), quality=88)
          os.remove(os.path.join(d, f))
  print("converted avif -> jpg")
  PY
  ```
- **Image too large for the API (>5 MB).** Downscale before captioning (`pip3 install pillow`), longest edge ~1600px: `from PIL import Image; im = Image.open(p); im.thumbnail((1600,1600)); im.save(p)`.
- **`CERTIFICATE_VERIFY_FAILED` on macOS.** That is why every script uses `certifi.where()`. Ensure `pip3 install certifi` succeeded.
- **HTTP 429 from Webflow.** The 0.5s delay keeps you under 150 req/min; raise `time.sleep` if a shared token still trips it.
- **Publish fails with `Invalid locale <id>` (duplicated sites).** A site created by duplicating another ("Copy of …") can have every CMS item tagged with a `cmsLocaleId` for a locale that no longer exists on the copy (`site.locales` is `null`). The **item-level** publish endpoint then rejects *all* items. The PATCH write is unaffected — alt is saved. Fix: publish at the **site level** (`5b_publish_site.py`), which bypasses per-item locale resolution. Verify via the items' `lastPublished` timestamp, not just the publish response.
- **Nothing renders even after publish.** A Multi-image gallery only appears on the CMS item's **detail page**. If that template isn't published (common on staging copies), the alt is live in the CMS data but no page displays it — a page fetch will 404. Trust the `verify.py` GET in that case.
- **`403` on the image download in a sandbox.** Not a Webflow/token problem — the environment's egress policy is blocking the asset CDN. Run locally, allow-list `uploads-ssl.webflow.com` / `*.website-files.com`, or fetch images server-side. See the "Network egress" prerequisite.

## Reuse on any project

Change only these, then run Step 0 → Step 6:

```bash
export WF_SITE_ID="..."          # the site
export WF_COLLECTION_ID="..."    # the collection with the image field
export WF_FIELD_SLUG="..."       # the MultiImage (or Image) field slug — confirm via Step 0
export ITEM_KIND="..."           # captioning hint for the domain
```

Everything else — schema, safety rules, resume logic, gotchas — is identical.

---

## Appendix — validation run (illustration only)

> One real run, here only to make the numbers concrete. The pattern above is the reusable part.

- **Project:** a duplicated motorcycle-dealer site.
- **Collection / field:** `Bikes` / `other-images` (Multi-image).
- **Scope:** 12 items; 8 had galleries; **34 images**, all with empty alt.
- **Result:** 34/34 captioned (make/model, colour, angle, details like exhaust brand and dashboards), 57–89 chars each; all 8 items written; 6 live items published; 2 drafts left unpublished by design.
- **Gotchas surfaced:** sandbox egress blocked the asset CDN (ran locally instead); item-publish hit `Invalid locale` (used site-level publish); the detail template wasn't published on the copy (verified via GET rather than a page fetch). All three are documented above.

## Changelog

- **1.0 (2026-07-24):** First validated release. Generalized from the initial project-specific runbook; added Step 0 discovery, single-Image-field support, and the duplicated-site publish / egress / detail-template gotchas.
