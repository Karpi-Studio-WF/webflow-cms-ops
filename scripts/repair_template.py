"""
repair_template.py — content repair / legacy shape migration on a Webflow CMS field.

Copy this file, fill in the CONFIG block, drop your transformer into `transform()`,
adjust `structural_markers()` for your target shape, and run:

    python3 repair_template.py

Performs the pattern documented in `references/content-repair-pattern.md`:

    fetch -> audit -> snapshot -> diff first -> human approve -> stage push -> structural verify -> resume-safe progress

DOES NOT publish. The staged change sits on top of the published version; the human
reviews each item in the Webflow Designer and publishes from there.

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
# CONFIG — edit these five values, then drop in your transformer below
# ============================================================================

API_TOKEN = "<YOUR_WEBFLOW_API_TOKEN>"     # CMS read/write scope only
COLLECTION_ID = "<YOUR_COLLECTION_ID>"
FIELD_SLUG = "body-2"                       # or "body" / "article-text"; verify by GETting one item
SNAPSHOT_DIR = "/tmp/repair_snapshots"      # absolute path; per-item bodies written here
PROGRESS_FILE = "/tmp/repair_progress.txt"  # resume-safe; skip slugs already pushed

# Webflow allows 150 req/min; 0.5s = 120 req/min with burst headroom.
REQUEST_DELAY_SECONDS = 0.5


# ============================================================================
# TRANSFORMER — replace this body with your project-specific transformation
# ============================================================================

def transform(field_value: str) -> str:
    """Pure: current field value -> new field value. Idempotent.

    Replace this body with your transformation logic. Rules:
      - Pure: no I/O.
      - Idempotent: running twice equals running once.
      - Conservative: only touch your target legacy shape.
      - Testable: easy to assert on sample inputs.

    Worked example (Schema Glossary code-block migration) is documented in
    `references/content-repair-pattern.md`."""
    raise NotImplementedError("Replace transform() with your transformation logic.")


# ============================================================================
# STRUCTURAL VERIFICATION — customize for the shape your transform changes
# ============================================================================

def structural_markers(html: str) -> dict:
    """Counts used for pre/post structural verification.

    The harness checks that the API echo's markers match the local expected markers
    after each PATCH. Customize the keys to match what your transformation changes.
    Defaults below are reasonable for code-block migrations; adjust freely."""
    return {
        "h2": len(re.findall(r"<h2[^>]*>", html)),
        "h3": len(re.findall(r"<h3[^>]*>", html)),
        "h4": len(re.findall(r"<h4[^>]*>", html)),
        "pre": len(re.findall(r"<pre[^>]*>", html)),
        # legacy <p><code> with <br> or &nbsp; (the shape this template targets by default)
        "legacy_p_code": sum(
            1 for m in re.finditer(r"<p>\s*<code>(.*?)</code>", html, re.DOTALL)
            if re.search(r"<br|&nbsp;", m.group(1))
        ),
    }


# After verification, this set of keys MUST be zero on the post-push echo or the push
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


def audit(items: list[dict]) -> list[dict]:
    affected = []
    for it in items:
        body = it["fieldData"].get(FIELD_SLUG, "") or ""
        try:
            new = transform(body)
        except Exception as e:
            sys.exit(f"transform() raised on item {it['fieldData'].get('slug', it['id'])}: {e}")
        if new != body:
            affected.append(it)
    return affected


def snapshot_all(items: list[dict]) -> None:
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    for it in items:
        slug = it["fieldData"]["slug"]
        body = it["fieldData"].get(FIELD_SLUG, "") or ""
        with open(f"{SNAPSHOT_DIR}/{slug}.html", "w") as f:
            f.write(body)


def diff_summary(slug: str, old: str, new: str) -> None:
    om = structural_markers(old)
    nm = structural_markers(new)
    print(f"\n=== Diff for {slug} ===")
    print(f"Body size: {len(old):,} -> {len(new):,} ({len(new)-len(old):+d})")
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
        sys.exit("Fill in API_TOKEN, COLLECTION_ID, FIELD_SLUG in the CONFIG block first.")
    try:
        transform("")  # smoke check: did the user override transform()?
    except NotImplementedError:
        sys.exit("Implement transform() in the script before running.")
    except Exception:
        pass  # other errors on empty input are fine

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
        body = it["fieldData"].get(FIELD_SLUG, "") or ""
        print(f"  {slug}: {len(body):,} bytes")
    print()

    snapshot_all(affected)
    print(f"Snapshotted {len(affected)} bodies to {SNAPSHOT_DIR}/\n")

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
    old_body = first["fieldData"][FIELD_SLUG]
    new_body = transform(old_body)
    diff_summary(slug, old_body, new_body)

    with open(f"{SNAPSHOT_DIR}/{slug}_NEW.html", "w") as f:
        f.write(new_body)
    print(f"\nFull transformed body for review: {SNAPSHOT_DIR}/{slug}_NEW.html")

    ans = input("\nApprove this shape and stage push for all affected items? [y/N]: ").strip().lower()
    if ans != "y":
        print("Aborted. Nothing pushed.")
        return 0

    pushed = 0
    failed: list[tuple[str, list[str]]] = []
    for it in todo:
        slug = it["fieldData"]["slug"]
        item_id = it["id"]
        body = it["fieldData"].get(FIELD_SLUG, "") or ""
        new = transform(body)
        if new == body:
            continue  # idempotency: skip already-clean items
        payload = {
            FIELD_SLUG: new,
            "name": it["fieldData"]["name"],
            "slug": slug,
        }
        try:
            echo = patch_item(COLLECTION_ID, item_id, payload)
            echo_body = echo["fieldData"].get(FIELD_SLUG, "") or ""
            issues = verify_after_push(new, echo_body, slug)
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
