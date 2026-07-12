"""
wrap_bare_tables.py — wrap bare <table> elements in a Webflow RichText field with
the Rich Text HTML-Embed wrapper + a styling class, so they render correctly.

WHY THIS EXISTS
    A bare <table> pushed into a Webflow RichText field renders broken on the live
    page (flattened to a paragraph, or surviving but unstyled). The correct shape is:

        <div data-rt-embed-type="true"><table class="ks-pricing-table">...</table></div>

    The embed wrapper makes the markup passthrough (grid survives); the class is what
    the site CSS targets (so it isn't unstyled). See references/webflow-richtext-tables.md.

    This script finds every bare <table> in the target items and rewrites it to that
    shape. It is IDEMPOTENT — a table already wrapped and already classed is left
    untouched — so re-running is safe.

USAGE
    1. pip3 install certifi
    2. Edit the CONFIG block below: paste your API_TOKEN.
    3. Run once as a DRY RUN (default) to see exactly what would change:
           python3 scripts/wrap_bare_tables.py
    4. Review the printed before/after. When happy, set DRY_RUN = False and run again
       to write the changes (as drafts).
    5. Verify visually in the Webflow editor (principle #6 — the API GET will echo your
       HTML back whether or not it rendered). Then publish (set PUBLISH_AFTER = True, or
       publish from the Designer).

This targets the 4 bare tables found in 3 items of the Karpi blog collection as of
2026-05-29, but works for any items you list in TARGET_ITEM_IDS.
"""

import json
import os
import re
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
# CONFIG
# ============================================================================
# Credentials come from a .env file or environment variables via wf_config
# (run scripts/setup_env.py to create the .env). The values below are used only
# as a fallback if the corresponding env key is unset — so you can still edit
# them directly if you prefer.

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wf_config import load_config  # noqa: E402

_cfg = load_config(require=())  # don't fail here; we validate what we need below

API_TOKEN = _cfg.get("WEBFLOW_API_TOKEN", "<YOUR_WEBFLOW_API_TOKEN>")
COLLECTION_ID = _cfg.get("WEBFLOW_COLLECTION_ID", "67756fb6c22d9437aa3af048")  # Karpi blog collection
BODY_FIELD = _cfg.get("WEBFLOW_BODY_FIELD", "article-text")                     # RichText field slug
TABLE_CLASS = "ks-pricing-table"               # class added to each <table>; matches the live site CSS

# The items to fix. Pre-filled with the 3 items that have bare tables (4 tables total).
# Any already-correct table inside these items is skipped (idempotent), so listing an
# item that is already fine is harmless.
TARGET_ITEM_IDS = [
    "6a14eb253e19f360942d3c5e",  # webflow-team-plan-vs-enterprise-b2b   (1 bare table)
    "69e7c6693fad9d42bd12e5d2",  # webflow-multi-image-alt-text-claude   (1 bare table)
    "69d809aecbcc7543259e029d",  # 223-schema-articles-claude-code       (2 bare tables)
]

# Safety switches
DRY_RUN = True          # True = show what would change, write nothing. Set False to apply.
PUBLISH_AFTER = False   # True = publish the items live after patching. Leave False to verify first.

PROGRESS_FILE = "/tmp/wrap_bare_tables_progress.txt"  # absolute path (principle #3)
REQUEST_DELAY_SECONDS = 0.5                            # 120 req/min (principle #4)

API_BASE = "https://api.webflow.com/v2"


# ============================================================================
# The transform — idempotent: wrap bare <table>, add class if missing
# ============================================================================

TABLE_BLOCK = re.compile(r"<table\b[^>]*>[\s\S]*?</table>", re.IGNORECASE)
OPEN_TAG = re.compile(r"<table\b([^>]*)>", re.IGNORECASE)


def fix_tables(html: str):
    """Return (new_html, stats). Wrap each <table>...</table> in a
    <div data-rt-embed-type="true"> and add class="TABLE_CLASS" when absent.

    Idempotent:
      - a table already immediately inside a data-rt-embed-type div is not re-wrapped
      - a table that already has a class attribute keeps it (no second class added)
    """
    out = []
    idx = 0
    found = wrapped = classed = already_ok = 0

    for m in TABLE_BLOCK.finditer(html):
        found += 1
        start, end = m.start(), m.end()
        block = m.group(0)

        # Is this table already inside an embed wrapper? Look at the short run of
        # markup immediately before it (allowing an HTML-comment banner in between).
        before = html[max(0, start - 80):start]
        already_wrapped = "data-rt-embed-type" in before

        # Add the class to the <table> tag if it has none.
        open_m = OPEN_TAG.match(block)
        attrs = open_m.group(1)
        if "class=" in attrs.lower():
            new_block = block
        else:
            new_block = '<table class="%s"%s>%s' % (TABLE_CLASS, attrs, block[open_m.end():])
            classed += 1

        out.append(html[idx:start])
        if already_wrapped:
            out.append(new_block)
            if "class=" in attrs.lower():
                already_ok += 1
        else:
            out.append('<div data-rt-embed-type="true">%s</div>' % new_block)
            wrapped += 1
        idx = end

    out.append(html[idx:])
    new_html = "".join(out)

    # Sanity: we must never lose or add a <table>, and every table must end up wrapped.
    assert new_html.count("<table") == html.count("<table"), "table count changed!"
    assert new_html.count("data-rt-embed-type") >= new_html.count("<table"), "not every table wrapped!"

    stats = {"found": found, "wrapped": wrapped, "classed": classed, "already_ok": already_ok}
    return new_html, stats


# ============================================================================
# API helpers
# ============================================================================


def _request(method, url, ctx, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Authorization": "Bearer %s" % API_TOKEN,
        "Accept": "application/json",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_item(cid, iid, ctx):
    return _request("GET", "%s/collections/%s/items/%s" % (API_BASE, cid, iid), ctx)


def patch_item(cid, iid, field_data, ctx):
    payload = {"fieldData": field_data}
    return _request("PATCH", "%s/collections/%s/items/%s" % (API_BASE, cid, iid), ctx, payload)


def publish_items(cid, item_ids, ctx):
    payload = {"itemIds": item_ids}
    return _request("POST", "%s/collections/%s/items/publish" % (API_BASE, cid), ctx, payload)


def _ctx_before(html, start, n=60):
    return html[max(0, start - n):start]


# ============================================================================
# Main
# ============================================================================


def main() -> int:
    if API_TOKEN.startswith("<"):
        sys.exit("Fill in API_TOKEN at the top of this file before running.")
    if not os.path.isabs(PROGRESS_FILE):
        sys.exit("PROGRESS_FILE must be absolute, got: %s" % PROGRESS_FILE)

    ctx = ssl.create_default_context(cafile=certifi.where())  # principle #1

    done = set()
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            done = {line.strip() for line in f if line.strip()}

    mode = "DRY RUN (no writes)" if DRY_RUN else "LIVE (writing drafts)"
    print("=== wrap_bare_tables — %s ===" % mode)
    print("Collection: %s   Field: %s   Class: %s\n" % (COLLECTION_ID, BODY_FIELD, TABLE_CLASS))

    patched, unchanged, failed = [], [], []

    for iid in TARGET_ITEM_IDS:
        if iid in done and not DRY_RUN:
            print("SKIP %s (already done on a prior run)" % iid)
            continue
        try:
            item = get_item(COLLECTION_ID, iid, ctx)
        except urllib.error.HTTPError as e:
            failed.append((iid, "GET HTTP %s" % e.code))
            print("FAIL %s: GET HTTP %s" % (iid, e.code))
            continue

        fd = item.get("fieldData", {})
        slug = fd.get("slug", iid)
        body = fd.get(BODY_FIELD, "") or ""
        new_body, stats = fix_tables(body)

        print("--- %s (%s) ---" % (slug, iid))
        print("    tables found: %d | to-wrap: %d | to-class: %d | already-ok: %d"
              % (stats["found"], stats["wrapped"], stats["classed"], stats["already_ok"]))

        if new_body == body:
            print("    no change needed.\n")
            unchanged.append(slug)
            continue

        # Show a before/after context snippet for each newly-wrapped table.
        for m in TABLE_BLOCK.finditer(body):
            b = _ctx_before(body, m.start(), 40)
            if "data-rt-embed-type" in body[max(0, m.start() - 80):m.start()]:
                continue
            print("    BEFORE …%s<table>…" % b[-40:].replace("\n", " "))
            print("    AFTER  …%s<div data-rt-embed-type=\"true\"><table class=\"%s\">…"
                  % (b[-40:].replace("\n", " "), TABLE_CLASS))

        if DRY_RUN:
            print("    [dry run] would PATCH %s (%+d chars)\n" % (slug, len(new_body) - len(body)))
            patched.append(slug)
            continue

        try:
            patch_item(COLLECTION_ID, iid, {BODY_FIELD: new_body}, ctx)
            with open(PROGRESS_FILE, "a") as f:
                f.write(iid + "\n")
            patched.append(slug)
            print("    PATCHED %s (%+d chars)\n" % (slug, len(new_body) - len(body)))
            time.sleep(REQUEST_DELAY_SECONDS)
        except urllib.error.HTTPError as e:
            body_txt = ""
            try:
                body_txt = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            failed.append((slug, "PATCH HTTP %s: %s" % (e.code, body_txt)))
            print("    FAIL %s: PATCH HTTP %s\n" % (slug, e.code))

    print("=== summary ===")
    print("%s: %d  |  unchanged: %d  |  failed: %d"
          % ("would patch" if DRY_RUN else "patched", len(patched), len(unchanged), len(failed)))
    for slug, err in failed:
        print("  FAIL %s: %s" % (slug, err[:200]))

    if not DRY_RUN and PUBLISH_AFTER and patched and not failed:
        ids = [i for i in TARGET_ITEM_IDS if i not in {f[0] for f in failed}]
        print("\nPublishing %d items..." % len(ids))
        try:
            publish_items(COLLECTION_ID, ids, ctx)
            print("Published.")
        except urllib.error.HTTPError as e:
            print("Publish failed: HTTP %s" % e.code)

    if DRY_RUN:
        print("\nThis was a DRY RUN. Set DRY_RUN = False and re-run to apply.")
    else:
        print("\n=== NEXT: visual verification (principle #6) ===")
        print("Open each patched item in the Webflow editor (or the live page after")
        print("publish) and confirm the table renders as a styled grid, not a run-on")
        print("paragraph. The API GET alone is NOT proof.")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
