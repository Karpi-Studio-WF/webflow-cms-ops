"""
fix_render_multi.py - post-publish render fixes for the tech collection.

  - multi-image: convert the single-line `file image.jpg` bash BLOCK to an inline
    <code> pill (renders via the inline-code CSS instead of a broken code block).
  - multi-image + 223-schema: wrap bare <table> in the embed-wrapper and add the
    ks-pricing-table class so the grid survives ingest and the site CSS styles it.

The prompt + 223 file-tree (language-plaintext) are handled by the FOOTER init
patch, NOT here. Default DRY; --push stages (REPAIR_APPROVE=yes). Never publishes.
"""
import os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import repair_codeblocks_multi as M

CID = "67756fb6c22d9437aa3af048"
FIELD = "article-text"
TARGETS = ["webflow-multi-image-alt-text-claude", "223-schema-articles-claude-code"]
SNAP = "/home/user/webflow-cms-ops/snapshots/tech_fix"

FILE_BLOCK_OLD = '<pre><code class="language-bash">file image.jpg</code></pre>'
FILE_BLOCK_NEW = '<p><code>file image.jpg</code></p>'
BARE_TABLE = re.compile(r'<table>(.*?)</table>', re.S)


def wrap_tables(html):
    def repl(m):
        return f'<div data-rt-embed-type="true"><table class="ks-pricing-table">{m.group(1)}</table></div>'
    return BARE_TABLE.sub(repl, html)


def transform(slug, html):
    new = html
    if slug == "webflow-multi-image-alt-text-claude":
        new = new.replace(FILE_BLOCK_OLD, FILE_BLOCK_NEW)
    new = wrap_tables(new)
    return new


def markers(html):
    return {
        "pre": len(re.findall(r"<pre[^>]*>", html)),
        "bare_table": len(BARE_TABLE.findall(html)),
        "wrapped_table": html.count('data-rt-embed-type="true"'),
        "ks_table": html.count('class="ks-pricing-table"'),
        "pills": len(re.findall(r'<code\b', re.sub(r'<pre\b.*?</pre>', '', html, flags=re.S))),
        "h2": len(re.findall(r"<h2[^>]*>", html)), "h3": len(re.findall(r"<h3[^>]*>", html)),
    }


def main():
    if not M.API_TOKEN:
        sys.exit("WEBFLOW_API_TOKEN not set")
    push = "--push" in sys.argv
    items = {it["fieldData"]["slug"]: it for it in M.list_all(CID)}
    plans = []
    for slug in TARGETS:
        it = items[slug]; old = it["fieldData"].get(FIELD, "") or ""
        new = transform(slug, old)
        om, nm = markers(old), markers(new)
        print(f"\n=== {slug} ===")
        print(f"  markers: {om}")
        print(f"        -> {nm}")
        if slug == "webflow-multi-image-alt-text-claude":
            print(f"  file block converted: {(FILE_BLOCK_OLD in old) and (FILE_BLOCK_NEW in new) and (FILE_BLOCK_OLD not in new)}")
        for i, m in enumerate(re.finditer(r'<div data-rt-embed-type="true"><table class="ks-pricing-table"><thead>(.*?)</thead>', new, re.S), 1):
            hdr = re.findall(r'<th>(.*?)</th>', m.group(1))
            print(f"  wrapped table {i} headers: {hdr}")
        # safety: prose/headings unchanged, bare tables all wrapped
        assert nm["h2"] == om["h2"] and nm["h3"] == om["h3"], "heading count changed"
        assert nm["bare_table"] == 0, "bare tables remain"
        assert nm["wrapped_table"] == om["bare_table"], "wrap count mismatch"
        plans.append((slug, it["id"], old, new))
    print("\nDRY-RUN OK (headings unchanged, all bare tables wrapped).")
    if not push:
        print("Re-run with --push REPAIR_APPROVE=yes to snapshot + stage. No publish.")
        return 0
    if os.environ.get("REPAIR_APPROVE", "").lower() not in ("y", "yes"):
        sys.exit("Set REPAIR_APPROVE=yes to stage.")
    os.makedirs(SNAP, exist_ok=True)
    for slug, iid, old, new in plans:
        open(f"{SNAP}/{slug}.prefix.html", "w").write(old)
        open(f"{SNAP}/{slug}.fixed.html", "w").write(new)
    print(f"Snapshotted pre-fix state to {SNAP}/")
    for slug, iid, old, new in plans:
        echo = M.http("PATCH", f"https://api.webflow.com/v2/collections/{CID}/items/{iid}",
                      {"fieldData": {FIELD: new, "name": items[slug]['fieldData']['name'], "slug": slug}})
        em = markers(echo["fieldData"].get(FIELD, ""))
        print(f"  staged {slug}: bare_table={em['bare_table']} wrapped={em['wrapped_table']} pre={em['pre']}")
        time.sleep(M.DELAY)
    print("\nStaged. NOT published.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
