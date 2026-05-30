"""
repair_template.py — content repair / legacy shape migration on a Webflow CMS field.

Copy this file, fill in the CONFIG block, drop your transformer into `transform()`,
adjust `structural_markers()` for your target shape, and run:

    python3 repair_template.py

Performs the pattern documented in `references/content-repair-pattern.md`:

    fetch -> audit -> snapshot -> diff first -> human approve -> stage push -> structural verify -> resume-safe progress

DOES NOT publish. The staged change sits on top of the published version; the human
reviews each item in the Webflow Designer and publishes from there.

Supports two modes:
  - **In-place repair** (default): SOURCE_FIELD == DEST_FIELD. Read a field, transform,
    write back to the same field. Use for code-block migrations, meta-title cleanups,
    deprecated property renames, etc.
  - **Cross-field repair**: SOURCE_FIELD != DEST_FIELD. Read from one field, transform,
    write to a different field. Use for derived-content jobs like extracting Q&As from
    the body and writing FAQPage JSON-LD to a dedicated `faq-schema` field
    (see `references/faqpage-schema.md`).

Requires:
    pip3 install certifi

Inside the Claude Code on the web sandbox: `SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt`
is needed instead of certifi's bundle. The script honors that env var automatically by
calling ssl.create_default_context() with no cafile argument.
"""

import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request


# ============================================================================
# CONFIG: edit these values, then drop in your transformer below
# ============================================================================

API_TOKEN = "<YOUR_WEBFLOW_API_TOKEN>"     # CMS read/write scope only
COLLECTION_ID = "<YOUR_COLLECTION_ID>"
SOURCE_FIELD = "body-2"                     # field the transformer reads (verify by GETting one item)
DEST_FIELD = SOURCE_FIELD                   # field the result is written to; defaults to SOURCE_FIELD (in-place)
SNAPSHOT_DIR = "/tmp/repair_snapshots"      # absolute path; per-item DEST_FIELD values written here (revert source)
PROGRESS_FILE = "/tmp/repair_progress.txt"  # resume-safe; skip slugs already pushed

# Webflow allows 150 req/min; 0.5s = 120 req/min with burst headroom.
REQUEST_DELAY_SECONDS = 0.5


# ============================================================================
# TRANSFORMER — replace this body with your project-specific transformation
# ============================================================================

def transform(source_value: str) -> str:
    """Pure: SOURCE_FIELD value -> DEST_FIELD value. Idempotent.

    Replace this body with your transformation logic. Rules:
      - Pure: no I/O.
      - Idempotent: running twice equals running once.
      - Conservative: only touch your target shape.
      - Testable: easy to assert on sample inputs.

    For an in-place repair (DEST_FIELD == SOURCE_FIELD), return the reshaped value.
    For a cross-field repair (DEST_FIELD != SOURCE_FIELD), return the derived value
    for the destination field (e.g., extracted JSON-LD).
    Return "" if this item produces no destination value (the harness skips it).

    Worked examples in references/content-repair-pattern.md and
    references/faqpage-schema.md. A ready-made multi-language code-block
    transform (drop-in for the in-place case) lives in scripts/code_block_repair.py."""
    raise NotImplementedError("Replace transform() with your transformation logic.")


# ============================================================================
# STRUCTURAL VERIFICATION: customize for the shape your transform produces
# ============================================================================

def structural_markers(value: str) -> dict:
    """Counts used for pre/post structural verification on the DEST_FIELD value.

    The harness checks that the API echo's markers match the local expected markers
    after each PATCH. Customize the keys to match what your transformation produces.
    Defaults below are reasonable for code-block migrations on a rich-text body;
    adjust freely for other repairs."""
    return {
        "h2": len(re.findall(r"<h2[^>]*>", value)),
        "h3": len(re.findall(r"<h3[^>]*>", value)),
        "h4": len(re.findall(r"<h4[^>]*>", value)),
        "pre": len(re.findall(r"<pre[^>]*>", value)),
        # legacy <p><code> with <br> or &nbsp; (the shape this template targets by default)
        "legacy_p_code": sum(
            1 for m in re.finditer(r"<p>\s*<code>(.*?)</code>", value, re.DOTALL)
            if re.search(r"<br|&nbsp;", m.group(1))
        ),
    }


# After verification, these keys MUST be zero on the post-push echo or the push
# is treated as failed. Add markers that should disappear entirely after a successful
# repair (e.g., the legacy shape your transform converts away).
MUST_BE_ZERO_AFTER_PUSH = {"legacy_p_code"}


# ============================================================================
# HARNESS — don't edit unless you know what you're doing
# ============================================================================

CTX = ssl.create_default_context()  # honors SSL_CERT_FILE env var; certifi if needed too
HDR = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def http(method: str, url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=HDR, method=method)
    with urllib.request.urlopen(req, context=CTX, timeout=60) as resp:
        return json.loads(resp.read().decode())


def list_all_items(collection_id: str) -> list[dict]:
    items: list[dict] = []
    offset = 0
    while True:
        page = http(
            "GET",
            f"https://api.webflow.com/v2/collections/{collection_id}/items"
            f"?limit=100&offset={offset}",
        )
        chunk = page.get("items", [])
        items.extend(chunk)
        if len(chunk) < 100:
            break
        offset += 100
        time.sleep(REQUEST_DELAY_SECONDS)
    return items


def patch_item(collection_id: str, item_id: str, field_data: dict) -> dict:
    return http(
        "PATCH",
        f"https://api.webflow.com/v2/collections/{collection_id}/items/{item_id}",
        {"fieldData": field_data},
    )


def _read_source(item: dict) -> str:
    return item["fieldData"].get(SOURCE_FIELD, "") or ""


def _read_dest(item: dict) -> str:
    return item["fieldData"].get(DEST_FIELD, "") or ""


def audit(items: list[dict]) -> list[dict]:
    """An item is affected if transform(source) differs from current dest AND is non-empty."""
    affected = []
    for it in items:
        src = _read_source(it)
        dst = _read_dest(it)
        try:
            new = transform(src)
        except Exception as e:
            sys.exit(f"transform() raised on item {it['fieldData'].get('slug', it['id'])}: {e}")
        if new and new != dst:
            affected.append(it)
    return affected


def snapshot_all(items: list[dict]) -> None:
    """Save current DEST_FIELD value to disk for every affected item. Revert source."""
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    for it in items:
        slug = it["fieldData"]["slug"]
        dst = _read_dest(it)
        with open(f"{SNAPSHOT_DIR}/{slug}.html", "w") as f:
            f.write(dst)


def diff_summary(slug: str, before_dest: str, after_dest: str) -> None:
    om = structural_markers(before_dest)
    nm = structural_markers(after_dest)
    print(f"\n=== Diff for {slug} (DEST_FIELD={DEST_FIELD}) ===")
    print(f"Size: {len(before_dest):,} -> {len(after_dest):,} ({len(after_dest)-len(before_dest):+d})")
    for k in om:
        flag = "  <- CHANGED" if om[k] != nm[k] else ""
        print(f"  {k}: {om[k]} -> {nm[k]}{flag}")


def verify_after_push(local_new: str, api_echo: str, slug: str) -> list[str]:
    """Return a list of structural issues, empty if push is clean."""
    issues = []
    expected = structural_markers(local_new)
    actual = structural_markers(api_echo)
    for k, v in expected.items():
        if actual.get(k) != v:
            issues.append(f"{slug}: {k} mismatch expected={v} actual={actual.get(k)}")
    for k in MUST_BE_ZERO_AFTER_PUSH:
        if actual.get(k, 0) != 0:
            issues.append(f"{slug}: {k} remaining after push = {actual.get(k)}")
    return issues


def load_progress() -> set[str]:
    if os.path.exists(PROGRESS_FILE):
        return {line.strip() for line in open(PROGRESS_FILE) if line.strip()}
    return set()


def record_progress(slug: str) -> None:
    with open(PROGRESS_FILE, "a") as f:
        f.write(slug + "\n")


def main() -> int:
    if API_TOKEN.startswith("<") or COLLECTION_ID.startswith("<"):
        sys.exit("Fill in API_TOKEN, COLLECTION_ID, SOURCE_FIELD, DEST_FIELD in the CONFIG block first.")
    try:
        transform("")  # smoke check: did the user override transform()?
    except NotImplementedError:
        sys.exit("Implement transform() in the script before running.")
    except Exception:
        pass  # other errors on empty input are fine

    mode = "in-place" if SOURCE_FIELD == DEST_FIELD else f"cross-field ({SOURCE_FIELD} -> {DEST_FIELD})"
    print(f"Mode: {mode}")
    print(f"Fetching all items in collection {COLLECTION_ID}...")
    items = list_all_items(COLLECTION_ID)
    print(f"  {len(items)} items total\n")

    affected = audit(items)
    print(f"Audit: {len(affected)} item(s) would change under the transform")
    if not affected:
        print("Nothing to repair.")
        return 0
    for it in affected:
        slug = it["fieldData"]["slug"]
        src_len = len(_read_source(it))
        dst_len = len(_read_dest(it))
        print(f"  {slug}: source {src_len:,} bytes, current dest {dst_len:,} bytes")
    print()

    snapshot_all(affected)
    print(f"Snapshotted {len(affected)} DEST_FIELD values to {SNAPSHOT_DIR}/\n")

    done = load_progress()
    todo = [it for it in affected if it["fieldData"]["slug"] not in done]
    if not todo:
        print("All affected items already processed (per progress file).")
        return 0
    if done:
        print(f"Resuming: {len(done)} already done, {len(todo)} to go\n")

    # Diff the first item, request human approval before batching
    first = todo[0]
    slug = first["fieldData"]["slug"]
    before = _read_dest(first)
    after = transform(_read_source(first))
    diff_summary(slug, before, after)

    with open(f"{SNAPSHOT_DIR}/{slug}_NEW.html", "w") as f:
        f.write(after)
    print(f"\nFull new DEST_FIELD value for review: {SNAPSHOT_DIR}/{slug}_NEW.html")

    ans = input("\nApprove this shape and stage push for all affected items? [y/N]: ").strip().lower()
    if ans != "y":
        print("Aborted. Nothing pushed.")
        return 0

    pushed = 0
    failed: list[tuple[str, list[str]]] = []
    for it in todo:
        slug = it["fieldData"]["slug"]
        item_id = it["id"]
        new = transform(_read_source(it))
        if not new or new == _read_dest(it):
            continue  # idempotency: skip no-ops
        payload = {
            DEST_FIELD: new,
            "name": it["fieldData"]["name"],
            "slug": slug,
        }
        try:
            echo = patch_item(COLLECTION_ID, item_id, payload)
            echo_dest = echo["fieldData"].get(DEST_FIELD, "") or ""
            issues = verify_after_push(new, echo_dest, slug)
            if issues:
                failed.append((slug, issues))
                print(f"  FAIL {slug}: {issues[0]}")
                print("  Stopping batch. Investigate before continuing.")
                break
            pushed += 1
            record_progress(slug)
            if pushed % 5 == 0 or pushed == len(todo):
                print(f"  {pushed}/{len(todo)}: {slug}")
            time.sleep(REQUEST_DELAY_SECONDS)
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")[:300]
            failed.append((slug, [f"HTTP {e.code}: {body_text}"]))
            print(f"  FAIL {slug}: HTTP {e.code}")
            break
        except Exception as e:
            failed.append((slug, [str(e)]))
            print(f"  FAIL {slug}: {e}")
            break

    print()
    print(f"Staged: {pushed}/{len(todo)}")
    print(f"Failed: {len(failed)}")
    for slug, issues in failed:
        for i in issues:
            print(f"  {slug}: {i[:200]}")

    print()
    print("=== NEXT STEP: human review and publish ===")
    print("Items are in staged-draft state. Live pages serve the previous published version.")
    print("Open each affected item in the Webflow Designer, eyeball the change, and publish")
    print("from there. The API DID NOT publish anything.")
    print()
    print(f"Pre-push snapshots (revert source): {SNAPSHOT_DIR}/<slug>.html")
    print(f"Progress (resume-safe):              {PROGRESS_FILE}")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
