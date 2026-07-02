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

from __future__ import annotations

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
# CONFIG — edit these values, then run the script
# ============================================================================

# Prefer the env var so the token never lives in a file that could be committed:
#     export WEBFLOW_API_TOKEN="..."
API_TOKEN = os.environ.get("WEBFLOW_API_TOKEN", "<YOUR_WEBFLOW_API_TOKEN>")
COLLECTION_ID = "<YOUR_COLLECTION_ID>"
BODY_FIELD = "body"  # or "body-2" — verify by fetching one item first
DB_PATH = "/absolute/path/to/your.db"

# /tmp is wiped on reboot. For a batch that spans days (or a machine that may
# restart mid-run), point this at a durable path instead, e.g. next to the DB.
PROGRESS_FILE = "/tmp/webflow_push_progress.txt"

# Optional: restrict push to specific slugs (leave None to push everything)
ONLY_SLUGS = None  # e.g., {"slug-1", "slug-2"}

# First-time upload: when True, rows with no webflow_id are created via POST
# (as drafts) and the new item ID is written back to the DB, so future runs
# PATCH them. When False (default), such rows are skipped with a warning.
# The POST payload needs a `name`; this template derives it from meta_title,
# falling back to the slug. Adjust `create_item()` if your collection differs.
CREATE_MISSING = False

# Rate limiting. Webflow allows 150 req/min. 0.5s = 120 req/min with burst headroom.
REQUEST_DELAY_SECONDS = 0.5

# Transient failures (429 rate limit, 5xx) are retried this many times with
# backoff, honoring the Retry-After header when Webflow sends one.
MAX_RETRIES = 3

# Sanity threshold. Items with HTML shorter than this are skipped.
MIN_HTML_LENGTH = 100


# ============================================================================
# Push loop — don't edit unless you know what you're doing
#
# Failure philosophy: items are independent, so a per-item HTTP failure is
# recorded and the loop continues; failures are reported at the end and the
# exit code is non-zero. (Contrast repair_template.py, which halts on the
# first failure — there, a structural mismatch means the transform itself is
# suspect for every remaining item.)
# ============================================================================


API_BASE = "https://api.webflow.com/v2"


def request_json(
    url: str, ssl_ctx: ssl.SSLContext, method: str = "GET", body: dict | None = None
) -> dict:
    """One API call with retry on 429/5xx. Other HTTP errors raise immediately."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    for attempt in range(MAX_RETRIES + 1):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == MAX_RETRIES:
                raise
            retry_after = e.headers.get("Retry-After", "")
            delay = float(retry_after) if retry_after.isdigit() else 2.0 ** (attempt + 1)
            print(f"    HTTP {e.code}, retrying in {delay:.0f}s (attempt {attempt + 1}/{MAX_RETRIES})")
            time.sleep(delay)
    raise AssertionError("unreachable")


def create_item(
    ssl_ctx: ssl.SSLContext, slug: str, html: str, meta_title: str, meta_desc: str
) -> str:
    """First-time POST. Creates the item as a draft and returns its Webflow ID."""
    payload = {
        "isDraft": True,
        "fieldData": {
            "name": meta_title or slug,
            "slug": slug,
            BODY_FIELD: html,
            "meta-title": meta_title or "",
            "meta-description": meta_desc or "",
        },
    }
    created = request_json(
        f"{API_BASE}/collections/{COLLECTION_ID}/items", ssl_ctx, "POST", payload
    )
    return created["id"]


def main() -> int:
    if API_TOKEN.startswith("<") or COLLECTION_ID.startswith("<"):
        sys.exit(
            "Config not filled in. Set the WEBFLOW_API_TOKEN env var (or edit "
            "API_TOKEN), and edit COLLECTION_ID, BODY_FIELD, and DB_PATH at the "
            "top of this file before running."
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

    # Connection stays open through the loop: a first-time POST writes the new
    # webflow_id back to the row so future runs PATCH it.
    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()
    c.execute(
        "SELECT slug, webflow_id, body_html, meta_title, meta_description "
        "FROM my_items ORDER BY slug"
    )
    rows = list(c.fetchall())

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
        conn.close()
        return 0

    pushed = 0
    created = 0
    failed: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []

    for slug, wf_id, html, meta_title, meta_desc in todo:
        if not wf_id and not CREATE_MISSING:
            skipped.append((slug, "no webflow_id (set CREATE_MISSING = True to POST it)"))
            continue
        if not html or len(html) < MIN_HTML_LENGTH:
            skipped.append((slug, f"html too short ({len(html) if html else 0} chars)"))
            continue

        try:
            if not wf_id:
                new_id = create_item(ssl_ctx, slug, html, meta_title, meta_desc)
                c.execute(
                    "UPDATE my_items SET webflow_id = ? WHERE slug = ?", (new_id, slug)
                )
                conn.commit()
                created += 1
            else:
                payload = {
                    "fieldData": {
                        BODY_FIELD: html,
                        "meta-title": meta_title or "",
                        "meta-description": meta_desc or "",
                    }
                }
                request_json(
                    f"{API_BASE}/collections/{COLLECTION_ID}/items/{wf_id}",
                    ssl_ctx,
                    "PATCH",
                    payload,
                )
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

    conn.close()

    print()
    print(f"Pushed: {pushed}/{len(todo)}" + (f" ({created} created via POST)" if created else ""))
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
