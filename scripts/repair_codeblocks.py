"""
repair_codeblocks.py — concrete fill-in of repair_template.py for the Schema Glossary
legacy code-block migration (content-repair-pattern.md).

Transform: legacy <p><code>...with <br>/&nbsp;...</code></p>  ->  round-trip-safe
           <pre><code class="language-X">CONTENT\n</code></pre>   (SKILL.md shape).

Modes (default is READ-ONLY):
    python3 scripts/repair_codeblocks.py            # audit + per-block language table. No writes.
    python3 scripts/repair_codeblocks.py --push     # snapshot + diff; stages PATCH only if
                                                     # REPAIR_APPROVE=yes is set. NEVER publishes.

Collection select (default types):
    REPAIR_COLLECTION=types|terms

Token comes from the environment (never hardcoded / committed):
    WEBFLOW_API_TOKEN=...

SSL: honors SSL_CERT_FILE (sandbox uses /etc/ssl/certs/ca-certificates.crt) via
ssl.create_default_context() with no cafile.
"""

import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from html import unescape


# ============================================================================
# CONFIG
# ============================================================================

API_TOKEN = os.environ.get("WEBFLOW_API_TOKEN", "")

COLLECTIONS = {
    "types": "69d782c825cd3b36434946f8",
    "terms": "69d78318b11f74482c3ac35d",
}
COLLECTION_NAME = os.environ.get("REPAIR_COLLECTION", "types")
COLLECTION_ID = COLLECTIONS[COLLECTION_NAME]

FIELD_SLUG = "body-2"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_DIR = os.path.join(REPO, "snapshots", COLLECTION_NAME)
PROGRESS_FILE = f"/tmp/repair_codeblocks_{COLLECTION_NAME}_progress.txt"

# Webflow allows 150 req/min; 0.5s = 120 req/min with burst headroom.
REQUEST_DELAY_SECONDS = 0.5


# ============================================================================
# TRANSFORMER — verbatim worked example from references/content-repair-pattern.md
# ============================================================================

BR_RE    = re.compile(r'<br\s*/?>', re.IGNORECASE)
NBSP_RE  = re.compile(r'&nbsp;')
ZWJ      = chr(0x200D)
P_CODE_RE = re.compile(r'<p>\s*<code>(.*?)</code>[^<]*</p>', re.DOTALL)


def _detect_language(text_decoded: str) -> str:
    s = text_decoded.lstrip()
    if not s:
        return "language-html"
    # Genuine HTML: block opens with a tag, e.g. a <script type="application/ld+json">
    # embed. Keep language-html so the markup itself is highlighted.
    if s.startswith(("<script", "<style", "<html", "<!DOCTYPE", "<!--")):
        return "language-html"
    if re.search(r'\bdef \w|\bimport \w|^class \w', s, re.MULTILINE):
        return "language-python"
    # JSON in two shapes:
    #   full object/array: opens with { or [ and contains a "key":
    #   JSON-LD fragment:  opens directly with a quoted key, e.g.  "sameAs": [
    #                      (no leading { so the first-char test alone misses it)
    if (s[:1] in "{[" and re.search(r'"[\w@$-]+"\s*:', s)) or re.match(r'"[\w@$-]+"\s*:', s):
        return "language-json"
    return "language-html"


def _is_legacy(inner: str) -> bool:
    return bool(BR_RE.search(inner) or NBSP_RE.search(inner))


def transform(field_value: str) -> str:
    """Rewrite legacy <p><code>...</code></p> blocks (with <br>/&nbsp;) to the
    round-trip-safe <pre><code class="language-X">CONTENT\n</code></pre> shape.
    Idempotent: <p><code> without <br>/&nbsp; is left alone; existing <pre><code>
    is not matched at all."""
    def repl(m):
        inner = m.group(1)
        if not _is_legacy(inner):
            return m.group(0)
        inner = BR_RE.sub("\n", inner)
        inner = NBSP_RE.sub(" ", inner)
        inner = inner.replace(ZWJ, "").rstrip()
        inner = inner.replace('"', '&quot;')
        lang = _detect_language(unescape(inner))
        return f'<pre><code class="{lang}">{inner}\n</code></pre>'
    return P_CODE_RE.sub(repl, field_value)


# ============================================================================
# STRUCTURAL VERIFICATION — adds the language-class marker (the point of the migration)
# ============================================================================

def structural_markers(html: str) -> dict:
    return {
        "h2": len(re.findall(r"<h2[^>]*>", html)),
        "h3": len(re.findall(r"<h3[^>]*>", html)),
        "h4": len(re.findall(r"<h4[^>]*>", html)),
        "pre": len(re.findall(r"<pre[^>]*>", html)),
        # quote-agnostic: Webflow may normalize " -> ' on ingest
        "lang_class": len(re.findall(r"<code\b[^>]*\blanguage-", html)),
        "legacy_p_code": sum(
            1 for m in re.finditer(r"<p>\s*<code>(.*?)</code>", html, re.DOTALL)
            if re.search(r"<br|&nbsp;", m.group(1))
        ),
    }


MUST_BE_ZERO_AFTER_PUSH = {"legacy_p_code"}


# ============================================================================
# HARNESS
# ============================================================================

CTX = ssl.create_default_context()
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
        if transform(body) != body:
            affected.append(it)
    return affected


def snapshot_all(items: list[dict]) -> None:
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    for it in items:
        slug = it["fieldData"]["slug"]
        body = it["fieldData"].get(FIELD_SLUG, "") or ""
        with open(f"{SNAPSHOT_DIR}/{slug}.html", "w") as f:
            f.write(body)
        with open(f"{SNAPSHOT_DIR}/{slug}.item.json", "w") as f:
            json.dump(it, f, indent=2, ensure_ascii=False)


def block_report(html: str) -> list[dict]:
    """Per <p><code> block: legacy?, detected language, one-line preview. Read-only."""
    rows = []
    for i, m in enumerate(P_CODE_RE.finditer(html), 1):
        inner = m.group(1)
        legacy = _is_legacy(inner)
        if legacy:
            tmp = BR_RE.sub("\n", inner)
            tmp = NBSP_RE.sub(" ", tmp)
            tmp = tmp.replace(ZWJ, "").rstrip()
            decoded = unescape(tmp)
            lang = _detect_language(decoded)
            first = next((ln for ln in decoded.splitlines() if ln.strip()), "")
            preview = first.strip()[:64]
        else:
            lang = "(skip)"
            preview = unescape(inner).strip()[:64]
        rows.append({"n": i, "legacy": legacy, "lang": lang, "preview": preview})
    return rows


def diff_summary(slug: str, old: str, new: str) -> None:
    om = structural_markers(old)
    nm = structural_markers(new)
    print(f"\n=== Structural diff for {slug} ===")
    print(f"Body size: {len(old):,} -> {len(new):,} ({len(new)-len(old):+d})")
    for k in om:
        flag = "  <- CHANGED" if om[k] != nm[k] else ""
        print(f"  {k}: {om[k]} -> {nm[k]}{flag}")


def verify_after_push(local_new: str, api_echo: str, slug: str) -> list[str]:
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


def _preflight() -> None:
    if not API_TOKEN:
        sys.exit("WEBFLOW_API_TOKEN not set in environment.")


def run_audit() -> int:
    """READ-ONLY: fetch, audit, snapshot, per-block language table. No push."""
    _preflight()
    print(f"Collection: {COLLECTION_NAME} ({COLLECTION_ID}), field={FIELD_SLUG}")
    print("Fetching items...")
    items = list_all_items(COLLECTION_ID)
    print(f"  {len(items)} items total")

    affected = audit(items)
    print(f"\nAudit: {len(affected)} of {len(items)} item(s) would change\n")
    if not affected:
        print("Nothing to repair.")
        return 0

    snapshot_all(affected)
    print(f"Snapshotted {len(affected)} affected bodies (+ full item JSON) to:\n  {SNAPSHOT_DIR}/\n")

    tally: dict[str, int] = {}
    for it in affected:
        slug = it["fieldData"]["slug"]
        body = it["fieldData"].get(FIELD_SLUG, "") or ""
        rows = block_report(body)
        legacy_rows = [r for r in rows if r["legacy"]]
        clean_rows = [r for r in rows if not r["legacy"]]
        print(f"### {slug}  (id={it['id']}, {len(body):,} bytes)")
        print(f"    <p><code> blocks: {len(rows)} total | to convert: {len(legacy_rows)} | already-clean: {len(clean_rows)}")
        print(f"    {'#':>3}  {'legacy':<6}  {'language':<16}  preview")
        for r in rows:
            print(f"    {r['n']:>3}  {('yes' if r['legacy'] else 'no'):<6}  {r['lang']:<16}  {r['preview']}")
            if r["legacy"]:
                tally[r["lang"]] = tally.get(r["lang"], 0) + 1
        print()

    print("Language tally (blocks to convert):")
    for lang, n in sorted(tally.items()):
        print(f"  {lang}: {n}")
    print("\nREAD-ONLY audit complete. No writes performed.")
    return 0


def run_push() -> int:
    """Snapshot + diff first item; stage PATCH for affected only if REPAIR_APPROVE=yes.
    NEVER publishes."""
    _preflight()
    items = list_all_items(COLLECTION_ID)
    affected = audit(items)
    print(f"Audit: {len(affected)} of {len(items)} item(s) would change")
    if not affected:
        print("Nothing to repair.")
        return 0
    snapshot_all(affected)
    print(f"Snapshotted {len(affected)} bodies to {SNAPSHOT_DIR}/")

    done = load_progress()
    todo = [it for it in affected if it["fieldData"]["slug"] not in done]
    if not todo:
        print("All affected items already staged (per progress file).")
        return 0

    first = todo[0]
    slug = first["fieldData"]["slug"]
    old_body = first["fieldData"][FIELD_SLUG]
    new_body = transform(old_body)
    diff_summary(slug, old_body, new_body)
    with open(f"{SNAPSHOT_DIR}/{slug}_NEW.html", "w") as f:
        f.write(new_body)
    print(f"\nTransformed body for review: {SNAPSHOT_DIR}/{slug}_NEW.html")

    print("\nPer-block language assignment (legacy blocks only):")
    for r in block_report(old_body):
        if r["legacy"]:
            print(f"  #{r['n']:>2}  {r['lang']:<14}  {r['preview']}")

    shown: set[str] = set()
    for m in P_CODE_RE.finditer(old_body):
        inner = m.group(1)
        if not _is_legacy(inner):
            continue
        kind = "script-wrapped -> html" if inner.lstrip().startswith("<script") else "fragment/object -> json"
        if kind in shown:
            continue
        shown.add(kind)
        before, after = m.group(0), transform(m.group(0))
        print(f"\n--- BEFORE [{kind}] (truncated) ---\n{before[:300]}")
        print(f"--- AFTER (truncated) ---\n{after[:300]}")
        if len(shown) >= 2:
            break

    if os.environ.get("REPAIR_APPROVE", "").lower() not in ("y", "yes"):
        print("\nDiff only. Re-run with REPAIR_APPROVE=yes to stage the PATCH (no publish).")
        return 0

    pushed = 0
    failed: list[tuple[str, list[str]]] = []
    for it in todo:
        slug = it["fieldData"]["slug"]
        body = it["fieldData"].get(FIELD_SLUG, "") or ""
        new = transform(body)
        if new == body:
            continue
        payload = {FIELD_SLUG: new, "name": it["fieldData"]["name"], "slug": slug}
        try:
            echo = patch_item(COLLECTION_ID, it["id"], payload)
            echo_body = echo["fieldData"].get(FIELD_SLUG, "") or ""
            issues = verify_after_push(new, echo_body, slug)
            if issues:
                failed.append((slug, issues))
                print(f"  FAIL {slug}: {issues[0]}  -- stopping batch.")
                break
            pushed += 1
            record_progress(slug)
            print(f"  staged {pushed}/{len(todo)}: {slug}")
            time.sleep(REQUEST_DELAY_SECONDS)
        except urllib.error.HTTPError as e:
            failed.append((slug, [f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"]))
            print(f"  FAIL {slug}: HTTP {e.code}  -- stopping batch.")
            break

    print(f"\nStaged: {pushed}/{len(todo)} | Failed: {len(failed)}")
    for slug, issues in failed:
        for i in issues:
            print(f"  {slug}: {i[:200]}")
    print("\nStaged-draft only. The API did NOT publish. Publish is a separate, explicit step.")
    return 0 if not failed else 1


def main() -> int:
    if "--push" in sys.argv:
        return run_push()
    return run_audit()


if __name__ == "__main__":
    sys.exit(main())
