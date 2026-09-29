#!/usr/bin/env python3
"""
snapshot_collections.py — read-only pull of Webflow CMS collections into SQLite.

    python3 snapshot_collections.py --site-domain example.com --out /abs/path/cms-snapshot \\
        --collection <glossary-collection-id>:glossary:/glossary/ \\
        --collection <blog-collection-id>:blog:/blog/

Each --collection is  <collection_id>:<short-name>:<url-prefix>. The url-prefix is the
path the collection's template pages live under on the site (check a live URL).

Token: WEBFLOW_API_TOKEN in the environment, or in a file passed with --env
(`WEBFLOW_API_TOKEN=...`, optional `export ` prefix and quotes are fine). CMS read scope
is enough. Never writes to Webflow.

Pulls every item (drafts and archived included), flattens RichText to plain text,
extracts every link, and resolves Reference / MultiReference fields to slugs, so the
overlap and link-graph analysis in audit_glossary.py can run offline. Snapshot every
collection that links to the glossary or competes with it (blog, guides, other glossaries),
not just the glossary itself; inbound links are only visible if the source is snapshotted.

Tables:
  collections(id, name, url_prefix, fields_json)
  items(collection, id, slug, url, name, h1, is_draft, is_archived,
        last_published, last_updated, word_count, body_text, field_data_json)
  links(from_collection, from_slug, field, href, anchor, to_path, is_internal)
  references(from_collection, from_slug, field, to_collection, to_slug)
Also writes text/<collection>/<slug>.txt for easy reading and grepping.

The DB is named cms-<YYYY-MM-DD>.db; a second run on the same day replaces it.
Requires: pip3 install certifi (optional on Linux).
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import os
import pathlib
import re
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.request

try:
    import certifi
except ImportError:
    certifi = None

API = "https://api.webflow.com/v2"
REQUEST_DELAY_SECONDS = 0.5  # Webflow allows 150 req/min; 0.5s = 120 req/min
HREF = re.compile(r'<a\b[^>]*?\bhref=(["\'])(.*?)\1[^>]*>(.*?)</a>', re.S | re.I)


def ssl_context() -> ssl.SSLContext:
    """SSL_CERT_FILE wins (proxied sandboxes); else certifi (macOS); else system default."""
    cafile = os.environ.get("SSL_CERT_FILE") or (certifi.where() if certifi else None)
    return ssl.create_default_context(cafile=cafile)


def load_env(path: str) -> None:
    for line in open(path):
        m = re.match(r"^(?:export\s+)?([A-Z_][A-Z0-9_]*)=(.*)$", line.strip())
        if m:
            os.environ.setdefault(m.group(1), m.group(2).strip().strip('"').strip("'"))


def make_getter(token: str, ctx: ssl.SSLContext):
    def get(path: str) -> dict:
        req = urllib.request.Request(API + path, headers={
            "Authorization": f"Bearer {token}", "accept": "application/json"})
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503) and attempt < 4:
                    time.sleep(2 ** attempt)
                    continue
                raise
    return get


def to_text(h: str | None) -> str:
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h or "", flags=re.S | re.I)
    h = re.sub(r"</(p|h[1-6]|li|tr|div|pre)>", "\n", h, flags=re.I)
    return re.sub(r"[ \t]+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()


SCHEMA = """
CREATE TABLE collections(id TEXT PRIMARY KEY, name TEXT, url_prefix TEXT, fields_json TEXT);
CREATE TABLE items(collection TEXT, id TEXT, slug TEXT, url TEXT, name TEXT, h1 TEXT,
  is_draft INT, is_archived INT, last_published TEXT, last_updated TEXT,
  word_count INT, body_text TEXT, field_data_json TEXT, PRIMARY KEY(collection, id));
CREATE TABLE links(from_collection TEXT, from_slug TEXT, field TEXT, href TEXT, anchor TEXT,
  to_path TEXT, is_internal INT);
CREATE TABLE "references"(from_collection TEXT, from_slug TEXT, field TEXT, to_collection TEXT, to_slug TEXT);
"""


def snapshot(specs: list[str], site_domain: str, out_dir: str, h1_field: str, get, delay: float = REQUEST_DELAY_SECONDS) -> pathlib.Path:
    dom = re.escape(site_domain)
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    db = out / f"cms-{datetime.date.today()}.db"
    if db.exists():
        db.unlink()
    c = sqlite3.connect(db)
    c.executescript(SCHEMA)

    refs = []  # (collection short name, field slug)
    for spec in specs:
        cid, cname, prefix = spec.split(":", 2)
        if not prefix.endswith("/"):
            prefix += "/"
        meta = get(f"/collections/{cid}")
        c.execute("INSERT INTO collections VALUES(?,?,?,?)", (cid, cname, prefix, json.dumps(meta["fields"])))
        rich = [f["slug"] for f in meta["fields"] if f["type"] == "RichText"]
        refs += [(cname, f["slug"]) for f in meta["fields"] if f["type"] in ("Reference", "MultiReference")]

        items, off = [], 0
        while True:
            d = get(f"/collections/{cid}/items?limit=100&offset={off}")
            time.sleep(delay)
            items += d["items"]
            off += len(d["items"])
            if off >= d.get("pagination", {}).get("total", off) or not d["items"]:
                break

        tdir = out / "text" / cname
        tdir.mkdir(parents=True, exist_ok=True)
        for it in items:
            fd = it["fieldData"]
            slug = fd.get("slug") or it["id"]
            text = "\n\n".join(to_text(fd.get(f)) for f in rich if fd.get(f))
            c.execute("INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                cname, it["id"], slug, prefix + slug, fd.get("name"), fd.get(h1_field),
                int(bool(it.get("isDraft"))), int(bool(it.get("isArchived"))), it.get("lastPublished"),
                it.get("lastUpdated"), len(text.split()), text, json.dumps(fd)))
            (tdir / f"{slug}.txt").write_text(
                f"NAME: {fd.get('name')}\nH1: {fd.get(h1_field)}\nURL: {prefix}{slug}\n\n{text}")
            for f in rich:
                for _q, href, anchor in HREF.findall(fd.get(f) or ""):
                    internal = int(href.startswith("/") or bool(re.search(rf"//(www\.)?{dom}(/|$)", href)))
                    path = None
                    if internal:
                        path = re.sub(rf"^https?://(www\.)?{dom}", "", href).split("#")[0].split("?")[0].rstrip("/")
                    c.execute("INSERT INTO links VALUES(?,?,?,?,?,?,?)",
                              (cname, slug, f, href, to_text(anchor), path, internal))
        print(f"{cname:16} {len(items):>4} items")

    # Resolve reference fields (item IDs) to slugs. Targets outside the snapshot keep the raw ID.
    by_id = {row[0]: (row[1], row[2]) for row in c.execute("SELECT id, collection, slug FROM items")}
    for cname, field in refs:
        for slug, fdj in c.execute("SELECT slug, field_data_json FROM items WHERE collection=?", (cname,)).fetchall():
            v = json.loads(fdj).get(field) or []
            for rid in (v if isinstance(v, list) else [v]):
                tc, ts = by_id.get(rid, (None, rid))
                c.execute('INSERT INTO "references" VALUES(?,?,?,?,?)', (cname, slug, field, tc, ts))
    c.commit()
    print("links:", c.execute("SELECT count(*) FROM links").fetchone()[0],
          "| reference edges:", c.execute('SELECT count(*) FROM "references"').fetchone()[0])
    c.close()
    return db


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--collection", action="append", required=True, help="id:short-name:/url-prefix/")
    ap.add_argument("--site-domain", required=True, help="domain whose links count as internal, e.g. example.com")
    ap.add_argument("--out", required=True, help="output directory (absolute path recommended)")
    ap.add_argument("--env", help="optional .env file containing WEBFLOW_API_TOKEN")
    ap.add_argument("--h1-field", default="h1-heading", help="field slug holding the page H1 (default: h1-heading)")
    a = ap.parse_args(argv)
    if a.env:
        load_env(a.env)
    token = os.environ.get("WEBFLOW_API_TOKEN")
    if not token:
        sys.exit("WEBFLOW_API_TOKEN not set (environment or --env file).")
    db = snapshot(a.collection, a.site_domain, a.out, a.h1_field, make_getter(token, ssl_context()))
    print("wrote", db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
