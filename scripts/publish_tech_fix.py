"""
publish_tech_fix.py - publish the two tech items staged by fix_render_multi.py.

fix_render_multi.py stages (PATCH) but never publishes. This companion publishes
exactly those two items, after re-verifying their staged field shape (no bare
<table> remain, expected wrapped-table count present). Item-level publish only --
it does NOT republish the whole site, so unrelated staged changes stay staged.

Default DRY (resolve IDs + verify staged shape, print plan). --publish with
PUBLISH_APPROVE=yes calls the Webflow item-publish endpoint.
"""
import os, sys, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import repair_codeblocks_multi as M
import fix_render_multi as F

CID = F.CID
FIELD = F.FIELD
# expected staged wrapped-table count per slug, post-fix (see fix_render_multi.py)
EXPECT_WRAPPED = {
    "webflow-multi-image-alt-text-claude": 1,
    "223-schema-articles-claude-code": 2,
}


def main():
    if not M.API_TOKEN:
        sys.exit("WEBFLOW_API_TOKEN not set")
    publish = "--publish" in sys.argv
    items = {it["fieldData"]["slug"]: it for it in M.list_all(CID)}
    targets = []
    for slug, exp_wrapped in EXPECT_WRAPPED.items():
        it = items[slug]
        m = F.markers(it["fieldData"].get(FIELD, "") or "")
        ok = m["bare_table"] == 0 and m["wrapped_table"] == exp_wrapped
        print(f"=== {slug} ===")
        print(f"  id={it['id']}  markers={m}")
        print(f"  staged-shape OK: {ok} (bare_table==0, wrapped_table=={exp_wrapped})")
        if not ok:
            sys.exit(f"Refusing to publish {slug}: staged shape unexpected.")
        targets.append(it["id"])
    print(f"\nReady to publish {len(targets)} items: {targets}")
    if not publish:
        print("Re-run with --publish PUBLISH_APPROVE=yes to publish these items live.")
        return 0
    if os.environ.get("PUBLISH_APPROVE", "").lower() not in ("y", "yes"):
        sys.exit("Set PUBLISH_APPROVE=yes to publish.")
    try:
        resp = M.http("POST", f"https://api.webflow.com/v2/collections/{CID}/items/publish",
                      {"itemIds": targets})
    except urllib.error.HTTPError as e:
        sys.exit(f"Publish failed: HTTP {e.code} {e.read().decode()}")
    published = resp.get("publishedItemIds", [])
    errors = resp.get("errors", [])
    print(f"\nPublished {len(published)} items: {published}")
    if errors:
        print(f"ERRORS: {errors}")
        return 1
    print("All target items published live. Spot-check the live pages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
