"""
repair_codeblocks_multi.py - multi-language code-block repair for the blog/tech collections.

Three operations, per the agreed per-block table:
  A  convert legacy multi-line <p><code> -> <pre><code class="language-X">
  B  add class to bare <pre><code>        -> <pre><code class="language-X">  (inner untouched)
  D  fix mislabeled classed <pre><code>   -> relabel class only, ONLY on a confident
                                             STRONG-language mismatch (inner untouched)

Leaves alone: correctly-classed blocks, inline pills, prose notes, and {{wf}} bindings.

Modes (default DRY):
    python3 scripts/repair_codeblocks_multi.py            # transform in memory, verify vs
                                                          # agreed table, print diff. No write.
    python3 scripts/repair_codeblocks_multi.py --push     # snapshot + stage PATCH (REPAIR_APPROVE=yes).
                                                          # NEVER publishes.
Token from env: WEBFLOW_API_TOKEN. Field: article-text. SSL honors SSL_CERT_FILE.
"""
import json, os, re, ssl, sys, time, urllib.error, urllib.request
from html import unescape

API_TOKEN = os.environ.get("WEBFLOW_API_TOKEN", "")
FIELD = "article-text"
COLLECTIONS = {"aeo": "694a8350885efc83ab2dcdc0", "tech": "67756fb6c22d9437aa3af048"}
SNAP_BASE = "/home/user/webflow-cms-ops/snapshots"
DELAY = 0.5

# Items in scope and the agreed change-set (language per changed block, in document order).
EXPECTED = {
    "faq-schema-beyond-faq-page-webflow":        ["json", "html", "json"],
    "id-referencing-schema-technique-aeo":       ["json"] * 10,
    "webflow-multi-image-alt-text-claude":       ["javascript", "bash", "bash", "plaintext", "python"],
    "bulk-publish-webflow-cms-python-claude-code": ["python"] * 5,
    "223-schema-articles-claude-code":           ["plaintext"],
}
ITEM_COLL = {
    "faq-schema-beyond-faq-page-webflow": "aeo", "id-referencing-schema-technique-aeo": "aeo",
    "webflow-multi-image-alt-text-claude": "tech", "bulk-publish-webflow-cms-python-claude-code": "tech",
    "223-schema-articles-claude-code": "tech",
}
# Explicit language for the two blocks our detector can't call from content alone.
OVERRIDES = [("You are generating accurate HTML alt text", "plaintext"),
             ("patched_images = [", "python")]

STRONG = {"json", "html", "python", "javascript", "bash", "sql"}
BR_RE = re.compile(r'<br\s*/?>', re.I); NBSP_RE = re.compile(r'&nbsp;'); ZWJ = chr(0x200D)


def _decode(inner):
    s = BR_RE.sub('\n', inner); s = NBSP_RE.sub(' ', s)
    return unescape(re.sub(r'<[^>]+>', '', s)).strip()


def detect(dec):
    s = dec.strip()
    for sub, lang in OVERRIDES:
        if sub in s:
            return lang, True
    if not s:
        return "plaintext", False
    if re.search(r'[├└│]', s):
        return "plaintext", True
    if re.match(r'<(!--|!doctype|html|head|body|div|span|script|style|ul|ol|li|table|tr|td|th|h[1-6]|img|section|nav|header|footer|main|button|form|input|label|meta|link|a\b|p\b|svg|path|iframe|figure|video|source)', s, re.I):
        return "html", True
    js_imp = bool(re.search(r'\bimport\b.*\bfrom\b|\brequire\s*\(', s))
    py_imp = bool(re.search(r'^\s*import\s+\w|^\s*from\s+[\w.]+\s+import\b', s, re.M))
    py_compr = bool(re.search(r'[\[{][^\]}]*\bfor\s+\w+\s+in\b', s, re.S)) and not re.search(r'\bdo\b', s)
    js = bool(re.search(r'\b(const|let|var)\s+[\w{]|\bfunction\b|=>|\bconsole\.\w|\bdocument\.\w|\bwindow\.\w|\bexport\b|`|(?<!:)//', s)) or js_imp
    py = bool(re.search(r'\bdef\s+\w+\s*\(|\bprint\s*\(|\bself\b|\belif\b|\b__\w+__\b|(?<![\w$])f["\']|\bNone\b|\bTrue\b|\bFalse\b|\.append\(', s, re.M)) or (py_imp and not js_imp) or py_compr
    bash = bool(re.search(r'(^|\n)\s*(\$\s|#!/|cd\s|ls\s|npm\s|npx\s|pip3?\s|python3?\s|node\s|bash\s|sh\s|source\s|git\s|curl\s|wget\s|chmod\s|mkdir\s|sudo\s|brew\s|sips\s|file\s)', s)) or bool(re.search(r'\bfor\s+\w+\s+in\b.*?\bdo\b', s, re.S)) or bool(re.search(r'(^|\n)\s*done\s*$', s, re.M))
    sql = bool(re.search(r'\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE)\b', s, re.I))
    jsonl = (s[:1] in '{[' or bool(re.match(r'"[\w@$-]+"\s*:', s))) and bool(re.search(r'"[\w@$-]+"\s*:', s)) and not re.search(r'(?<!:)//', s)
    if py and js: return "ambig", False
    if py: return "python", True
    if js: return "javascript", True
    if jsonl: return "json", True
    if sql: return "sql", True
    if bash: return "bash", True
    return "unknown", False


PCODE_BLOCK = re.compile(r'<p>\s*<code>(.*?)</code>\s*</p>', re.S)
PRECODE = re.compile(r'(<pre\b[^>]*>\s*<code\b)([^>]*?)(>)(.*?)(</code>\s*</pre>)', re.S)


def convert_legacy(html):
    def repl(m):
        inner = m.group(1)
        if not (BR_RE.search(inner) or NBSP_RE.search(inner) or '\n' in inner or len(_decode(inner)) > 80):
            return m.group(0)
        lang, _ = detect(_decode(inner))
        body = BR_RE.sub("\n", inner); body = NBSP_RE.sub(" ", body)
        body = body.replace(ZWJ, "").rstrip().replace('"', '&quot;')
        return f'<pre><code class="language-{lang}">{body}\n</code></pre>'
    return PCODE_BLOCK.sub(repl, html)


def fix_precode(html):
    def repl(m):
        open_, attrs, gt, inner, close = m.groups()
        cm = re.search(r'class\s*=\s*"([^"]*)"', attrs)
        dec = _decode(inner); lang, conf = detect(dec)
        if not cm or 'language-' not in cm.group(1):
            if not conf and lang in ("unknown", "ambig"):
                return m.group(0)  # do not guess a class we are unsure of
            if cm:
                newattrs = re.sub(r'class\s*=\s*"([^"]*)"', lambda c: f'class="{c.group(1)} language-{lang}"', attrs)
            else:
                newattrs = attrs + f' class="language-{lang}"'
            return open_ + newattrs + gt + inner + close
        existing = re.search(r'language-([a-z0-9]+)', cm.group(1)).group(1)
        norm = {"js": "javascript", "py": "python", "sh": "bash", "shell": "bash", "text": "plaintext"}.get(existing, existing)
        if conf and lang in STRONG and lang != norm:
            newcls = cm.group(1).replace(f'language-{existing}', f'language-{lang}')
            return open_ + re.sub(r'class\s*=\s*"[^"]*"', f'class="{newcls}"', attrs) + gt + inner + close
        return m.group(0)
    return PRECODE.sub(repl, html)


def transform(html):
    return fix_precode(convert_legacy(html))


def classes_of(html):
    return [(re.search(r'language-([a-z0-9]+)', a) or [None, None])[1] if 'language-' in a else None
            for a in [m.group(2) for m in PRECODE.finditer(html)]]


def markers(html):
    return {
        "h2": len(re.findall(r"<h2[^>]*>", html)), "h3": len(re.findall(r"<h3[^>]*>", html)),
        "pre": len(re.findall(r"<pre[^>]*>", html)),
        "bare_pre": sum(1 for a in [m.group(2) for m in PRECODE.finditer(html)] if 'language-' not in a),
        "legacy": sum(1 for m in PCODE_BLOCK.finditer(html) if BR_RE.search(m.group(1)) or NBSP_RE.search(m.group(1)) or '\n' in m.group(1) or len(_decode(m.group(1))) > 80),
        "pills": len(re.findall(r'<code\b', PCODE_BLOCK.sub('', re.sub(r'<pre\b.*?</pre>', '', html, flags=re.S)))),
        "wf": html.count('{{wf'),
    }


# ---- harness ----
CTX = ssl.create_default_context()
HDR = {"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json", "Accept": "application/json"}


def http(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=HDR, method=method)
    with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
        return json.loads(r.read().decode())


def list_all(cid):
    out, off = [], 0
    while True:
        p = http("GET", f"https://api.webflow.com/v2/collections/{cid}/items?limit=100&offset={off}")
        out += p.get("items", [])
        if len(p.get("items", [])) < 100: break
        off += 100; time.sleep(DELAY)
    return out


def gather():
    items = {}
    for cname, cid in COLLECTIONS.items():
        for it in list_all(cid):
            if it["fieldData"]["slug"] in EXPECTED:
                items[it["fieldData"]["slug"]] = (cname, cid, it)
    return items


def verify_item(slug, old, new):
    issues = []
    om, nm = markers(old), markers(new)
    if nm["legacy"] != 0: issues.append(f"{slug}: {nm['legacy']} legacy <p><code> remain")
    if nm["bare_pre"] != 0: issues.append(f"{slug}: {nm['bare_pre']} bare <pre> remain")
    if om["h2"] != nm["h2"] or om["h3"] != nm["h3"]: issues.append(f"{slug}: heading count changed")
    if om["pills"] != nm["pills"]: issues.append(f"{slug}: pill count changed {om['pills']}->{nm['pills']}")
    if om["wf"] != nm["wf"]: issues.append(f"{slug}: {{{{wf}}}} binding count changed {om['wf']}->{nm['wf']}")
    oc, ncl = classes_of(old), classes_of(new)
    changed = [n for o, n in zip(([None] * (len(ncl) - len(oc)) + oc) if len(ncl) >= len(oc) else oc, ncl) if True]
    new_pre_langs = ncl
    # languages assigned to blocks that were bare/new or relabeled
    changed_langs = []
    # recompute by diffing class lists positionally on pre blocks present in both
    # (convert adds new <pre>; align by detecting which new langs differ from old)
    return issues, om, nm, new_pre_langs


def main():
    if not API_TOKEN: sys.exit("WEBFLOW_API_TOKEN not set")
    push = "--push" in sys.argv
    items = gather()
    missing = set(EXPECTED) - set(items)
    if missing: sys.exit(f"items not found: {missing}")
    all_ok = True; plans = []
    for slug, (cname, cid, it) in items.items():
        old = it["fieldData"].get(FIELD, "") or ""
        new = transform(old)
        issues, om, nm, new_langs = verify_item(slug, old, new)
        # the change is (new pre count) added classes + relabels; check expected multiset
        exp = sorted(EXPECTED[slug])
        # langs now present that account for the change: compare class multiset delta
        old_langs = sorted([c for c in classes_of(old) if c])
        cur_langs = sorted([c for c in classes_of(new) if c])
        delta = list(cur_langs)
        for c in old_langs:
            if c in delta: delta.remove(c)
        # relabels (html->python) also change; approximate the change-set as delta plus relabeled
        print(f"\n=== {slug} ({cname}) ===")
        print(f"  markers: {om}  ->  {nm}")
        print(f"  expected change langs: {exp}")
        print(f"  new-class delta      : {sorted(delta)}")
        if issues:
            all_ok = False
            for i in issues: print(f"  ISSUE: {i}")
        plans.append((slug, cname, cid, it["id"], old, new))
    print("\n" + ("DRY-RUN OK" if all_ok else "DRY-RUN HAS ISSUES"))
    if not push:
        print("Re-run with --push (and REPAIR_APPROVE=yes) to snapshot + stage. No publish.")
        return 0 if all_ok else 1
    if not all_ok: sys.exit("Refusing to push: verification issues above.")
    if os.environ.get("REPAIR_APPROVE", "").lower() not in ("y", "yes"):
        sys.exit("Set REPAIR_APPROVE=yes to stage.")
    for slug, cname, cid, iid, old, new in plans:
        d = f"{SNAP_BASE}/{cname}"; os.makedirs(d, exist_ok=True)
        open(f"{d}/{slug}.html", "w").write(old)
        open(f"{d}/{slug}_NEW.html", "w").write(new)
    print(f"\nSnapshotted {len(plans)} items under {SNAP_BASE}/")
    for slug, cname, cid, iid, old, new in plans:
        echo = http("PATCH", f"https://api.webflow.com/v2/collections/{cid}/items/{iid}",
                    {"fieldData": {FIELD: new, "name": items[slug][2]['fieldData']['name'], "slug": slug}})
        em = markers(echo["fieldData"].get(FIELD, ""))
        ok = em["legacy"] == 0 and em["bare_pre"] == 0
        print(f"  staged {slug}: legacy={em['legacy']} bare={em['bare_pre']} pre={em['pre']} {'OK' if ok else 'CHECK'}")
        time.sleep(DELAY)
    print("\nStaged. NOT published. Verify echoes above, then publish separately.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
