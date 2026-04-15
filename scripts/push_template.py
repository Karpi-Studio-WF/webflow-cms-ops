"""
push_template.py — bulk-push content from a SQLite DB to a Webflow CMS collection.

Copy this file, edit the CONFIG block, and run with:
    python3 push_template.py

Requires:
    pip3 install certifi

This script has been used in production to push 281+ articles across 6+ fix passes
with 796+ Webflow API writes and zero failures. Every design choice exists to
prevent a specific failure mode we've hit. See references/webflow-gotchas.md for
the full catalog.

The expected DB schema has at minimum:
    CREATE TABLE my_items (
        slug              TEXT UNIQUE,
        webflow_id        TEXT,          -- Webflow item ID for the PATCH target
        body_html         TEXT,          -- compact HTML (use compact.py)
        meta_title        TEXT,
        meta_description  TEXT
    );

Adjust the SELECT and fieldData mapping if your schema differs.
"""

import json
import os
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.request

try:
    import certifi
except ImportError:
    sys.exit("certifi is required. Install with: pip3 install certifi")


# ============================================================================
# CONFIG — edit these five values, then run the script
# ============================================================================

API_TOKEN = "<YOUR_WEBFLOW_API_TOKEN>"
COLLECTION_ID = "<YOUR_COLLECTION_ID>"
BODY_FIELD = "body"  # or "body-2" — verify by fetching one item first
DB_PATH = "/absolute/path/to/your.db"
PROGRESS_FILE = "/tmp/webflow_push_progress.txt"

# Optional: restrict push to specific slugs (leave None to push everything)
ONLY_SLUGS = None  # e.g., {"slug-1", "slug-2"}

# Rate limiting. Webflow allows 150 req/min. 0.5s = 120 req/min with burst headroom.
REQUEST_DELAY_SECONDS = 0.5

# Sanity threshold. Items with HTML shorter than this are skipped.
MIN_HTML_LENGTH = 100


# ============================================================================
# Push loop — don't edit unless you know what you're doing
# ============================================================================


def main() -> int:
    if API_TOKEN.startswith("<") or COLLECTION_ID.startswith("<"):
        sys.exit(
            "Config not filled in. Edit API_TOKEN, COLLECTION_ID, BODY_FIELD, "
            "and DB_PATH at the top of this file before running."
        )
    if not os.path.isabs(DB_PATH):
        sys.exit(f"DB_PATH must be absolute, got: {DB_PATH}")
    if not os.path.exists(DB_PATH):
        sys.exit(f"DB not found at: {DB_PATH}")

    # macOS Python has no system cert bundle; certifi bridges the gap.
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())

    # Resume support: skip items already pushed on a prior run.
    done: set[str] = set()
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            done = {line.strip() for line in f if line.strip()}

    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()
    c.execute(
        "SELECT slug, webflow_id, body_html, meta_title, meta_description "
        "FROM my_items ORDER BY slug"
    )
    rows = list(c.fetchall())
    conn.close()

    # Filter: skip already-done items; optionally restrict to specific slugs.
    todo = [
        r for r in rows
        if r[0] not in done and (ONLY_SLUGS is None or r[0] in ONLY_SLUGS)
    ]
    print(
        f"{len(todo)} items to push "
        f"({len(done)} already done, {len(rows)} total in DB)"
    )
    if not todo:
        print("Nothing to push.")
        return 0

    pushed = 0
    failed: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []

    for slug, wf_id, html, meta_title, meta_desc in todo:
        if not wf_id:
            skipped.append((slug, "no webflow_id"))
            continue
        if not html or len(html) < MIN_HTML_LENGTH:
            skipped.append((slug, f"html too short ({len(html) if html else 0} chars)"))
            continue

        payload = {
            "fieldData": {
                BODY_FIELD: html,
                "meta-title": meta_title or "",
                "meta-description": meta_desc or "",
            }
        }
        data = json.dumps(payload).encode("utf-8")
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
        try:
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=30) as resp:
                json.loads(resp.read().decode("utf-8"))
            pushed += 1
            with open(PROGRESS_FILE, "a") as f:
                f.write(slug + "\n")
            if pushed % 25 == 0 or pushed == len(todo):
                print(f"  {pushed}/{len(todo)}: {slug}")
            time.sleep(REQUEST_DELAY_SECONDS)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            failed.append((slug, f"HTTP {e.code}: {body}"))
            print(f"  FAIL {slug}: HTTP {e.code}")
        except Exception as e:
            failed.append((slug, str(e)))
            print(f"  FAIL {slug}: {e}")

    print()
    print(f"Pushed: {pushed}/{len(todo)}")
    print(f"Failed: {len(failed)}")
    for slug, err in failed:
        print(f"  {slug}: {err[:200]}")
    print(f"Skipped: {len(skipped)}")
    for slug, reason in skipped:
        print(f"  {slug}: {reason}")

    print()
    print("=== NEXT STEP: visual verification ===")
    print("The Data API echoes back the HTML you pushed, which is NOT proof")
    print("that content rendered correctly. Verify at least 3 items visually:")
    print("  1. Open the item in Webflow CMS editor")
    print("  2. Or fetch a rendered live page and grep for expected elements")
    print()
    print("If content looks empty but the API GET shows HTML, the whitespace-")
    print("between-tags bug is the most likely cause. See")
    print("references/webflow-gotchas.md entry #2.")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
