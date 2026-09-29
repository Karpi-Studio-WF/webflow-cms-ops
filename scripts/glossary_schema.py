"""
glossary_schema.py — DefinedTerm (+ FAQPage) JSON-LD for glossary entries.

Pure functions (no I/O except the `set` CLI, which only reads a snapshot DB). Use it:

  1. As a library: `entry_graph(...)` builds the JSON-LD for one entry;
     `answer_block()` and `faq_pairs()` extract the parts audit_glossary.py checks.
  2. As the transform for scripts/repair_template.py (cross-field mode: read the body,
     write a dedicated PlainText schema field). See references/glossary-pattern.md, "Schema".

         from glossary_schema import make_transform
         transform = make_transform(
             site_url="https://www.example.com", url_prefix="/glossary/",
             set_url="https://www.example.com/glossary", set_name="Example Glossary")

  3. From the command line, to print the DefinedTermSet for the glossary hub page:

         python3 glossary_schema.py set --db /abs/cms-snapshot/cms-2026-09-29.db \\
             --glossary glossary --site-url https://www.example.com \\
             --set-url https://www.example.com/glossary --set-name "Example Glossary"

     `python3 glossary_schema.py selftest` runs the smoke test.

Conventions the extractors rely on (same as references/faqpage-schema.md):
  - Answer block: a dedicated PlainText field if the collection has one, else the first
    non-empty <p> of the body.
  - FAQ: an <h2> reading "Frequently Asked Questions" or "FAQ"; each <h3> under it is a
    question, the <p>s until the next <h3>/<h2> are its answer.

Output is deterministic (same input, same string), so the repair harness's idempotency
check (new == current) holds. `</` is escaped as `<\\/` so an answer containing
`</script>` cannot close the template's <script> tag.
"""
from __future__ import annotations

import json
import re
import sys
from html import unescape

TAGS = re.compile(r"<[^>]+>")
P_BLOCK = re.compile(r"<p\b[^>]*>(.*?)</p>", re.I | re.S)
H2_ANY = re.compile(r"<h2\b[^>]*>(.*?)</h2>", re.I | re.S)
H2_FAQ = re.compile(r"<h2\b[^>]*>\s*(?:Frequently Asked Questions|FAQs?)\s*</h2>", re.I)
H3 = re.compile(r"<h3\b[^>]*>(.*?)</h3>", re.I | re.S)


def visible(fragment: str) -> str:
    """Strip tags, decode entities, collapse whitespace."""
    return re.sub(r"\s+", " ", unescape(TAGS.sub("", fragment or ""))).strip()


def answer_block(body_html: str) -> str:
    """Visible text of the first non-empty <p> in the body."""
    for m in P_BLOCK.finditer(body_html or ""):
        t = visible(m.group(1))
        if t:
            return t
    return ""


def h2_questions(body_html: str) -> list[str]:
    return [visible(m.group(1)) for m in H2_ANY.finditer(body_html or "")]


def faq_pairs(body_html: str) -> list[tuple[str, str]]:
    """(question, answer) pairs from the body's FAQ section, in document order."""
    m = H2_FAQ.search(body_html or "")
    if not m:
        return []
    after = body_html[m.end():]
    nxt = re.search(r"<h2\b", after, re.I)
    section = after[:nxt.start()] if nxt else after
    h3s = list(H3.finditer(section))
    pairs = []
    for i, q in enumerate(h3s):
        end = h3s[i + 1].start() if i + 1 < len(h3s) else len(section)
        answer = " ".join(t for t in (visible(p.group(1)) for p in P_BLOCK.finditer(section[q.end():end])) if t)
        question = visible(q.group(1))
        if question and answer:
            pairs.append((question, answer))
    return pairs


def defined_term(name: str, description: str, url: str, set_url: str, set_name: str, same_as=()) -> dict:
    node = {
        "@type": "DefinedTerm",
        "@id": url + "#term",
        "name": name,
        "description": description,
        "url": url,
        "inDefinedTermSet": {"@type": "DefinedTermSet", "@id": set_url + "#set", "name": set_name, "url": set_url},
    }
    if same_as:
        node["sameAs"] = list(same_as)
    return node


def faq_page(pairs, url: str) -> dict:
    return {
        "@type": "FAQPage",
        "@id": url + "#faq",
        "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in pairs
        ],
    }


def _dump(obj: dict) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False).replace("</", "<\\/")


def entry_graph(name: str, url: str, body_html: str, set_url: str, set_name: str,
                answer: str | None = None, include_faq: bool = True, same_as=()) -> str:
    """JSON-LD string for one entry: DefinedTerm, plus FAQPage when the body has an FAQ
    section and include_faq is True. Returns "" when there is no answer block (nothing
    honest to put in `description`)."""
    description = (answer or "").strip() or answer_block(body_html)
    if not (name and description):
        return ""
    graph = [defined_term(name, description, url, set_url, set_name, same_as)]
    pairs = faq_pairs(body_html) if include_faq else []
    if pairs:
        graph.append(faq_page(pairs, url))
    return _dump({"@context": "https://schema.org", "@graph": graph})


def make_transform(site_url: str, url_prefix: str, set_url: str, set_name: str,
                   answer_field: str | None = None, include_faq: bool = True):
    """Build a `transform(source_value, item)` for scripts/repair_template.py.
    SOURCE_FIELD = the body field, DEST_FIELD = the schema field. The harness passes the
    item, which supplies name, slug and (optionally) the answer field."""
    base = site_url.rstrip("/") + "/" + url_prefix.strip("/") + "/"

    def transform(source_value: str, item: dict | None = None) -> str:
        if not item:
            return ""
        fd = item["fieldData"]
        answer = visible(fd.get(answer_field) or "") if answer_field else None
        return entry_graph(fd.get("name") or "", base + fd["slug"], source_value or "",
                           set_url, set_name, answer=answer, include_faq=include_faq)
    return transform


def defined_term_set(set_name: str, set_url: str, terms, description: str | None = None) -> str:
    """JSON-LD for the glossary hub page. `terms` = [(name, url), ...]. Regenerate and
    re-paste whenever entries are added, renamed or removed."""
    node = {
        "@context": "https://schema.org",
        "@type": "DefinedTermSet",
        "@id": set_url + "#set",
        "name": set_name,
        "url": set_url,
        "hasDefinedTerm": [{"@type": "DefinedTerm", "@id": u + "#term", "name": n, "url": u} for n, u in terms],
    }
    if description:
        node["description"] = description
    return _dump(node)


def _cli_set(argv) -> int:
    import argparse
    import sqlite3
    ap = argparse.ArgumentParser(prog="glossary_schema.py set")
    ap.add_argument("--db", required=True)
    ap.add_argument("--glossary", required=True, help="collection short name used in the snapshot")
    ap.add_argument("--site-url", required=True)
    ap.add_argument("--set-url", required=True)
    ap.add_argument("--set-name", required=True)
    ap.add_argument("--description")
    a = ap.parse_args(argv)
    c = sqlite3.connect(a.db)
    rows = c.execute("SELECT name, url FROM items WHERE collection=? AND is_draft=0 AND is_archived=0 ORDER BY name",
                     (a.glossary,)).fetchall()
    if not rows:
        sys.exit(f"No published items for collection '{a.glossary}' in {a.db}")
    site = a.site_url.rstrip("/")
    print("<script type=\"application/ld+json\">")
    print(defined_term_set(a.set_name, a.set_url, [(n, site + u) for n, u in rows], a.description))
    print("</script>")
    return 0


def _selftest() -> None:
    body = ("<p>A <a href=\"/glossary/heatmap\">heatmap</a> type that shows where visitors click.</p>"
            "<h2>How is a click map read?</h2><p>Hot areas get more clicks.</p>"
            "<h2>FAQ</h2><h3>Is a click map a heatmap?</h3><p>Yes, a type of one.</p>"
            "<h3>Does it need consent?</h3><p>Usually.</p><p>Check local law.</p>"
            "<h2>Sources</h2><p>x</p>")
    assert answer_block(body) == "A heatmap type that shows where visitors click."
    assert faq_pairs(body) == [("Is a click map a heatmap?", "Yes, a type of one."),
                               ("Does it need consent?", "Usually. Check local law.")]
    out = entry_graph("Click map", "https://ex.com/glossary/click-map", body,
                      "https://ex.com/glossary", "Ex Glossary")
    g = json.loads(out)["@graph"]
    assert [n["@type"] for n in g] == ["DefinedTerm", "FAQPage"]
    assert g[0]["description"] == answer_block(body)
    assert entry_graph("X", "u", "<p>a</p>", "s", "n") == entry_graph("X", "u", "<p>a</p>", "s", "n")  # deterministic
    assert "<\\/script>" in entry_graph("X", "u", "<p>use &lt;/script&gt; here</p>", "s", "n")
    assert entry_graph("X", "u", "<h2>No paragraph</h2>", "s", "n") == ""
    t = make_transform("https://ex.com", "/glossary/", "https://ex.com/glossary", "Ex")
    assert t(body) == ""  # no item, no output
    item = {"fieldData": {"name": "Click map", "slug": "click-map", "answer": "<p>Override.</p>"}}
    assert json.loads(t(body, item))["@graph"][0]["url"] == "https://ex.com/glossary/click-map"
    t2 = make_transform("https://ex.com", "glossary", "s", "n", answer_field="answer", include_faq=False)
    g2 = json.loads(t2(body, item))["@graph"]
    assert g2[0]["description"] == "Override." and len(g2) == 1
    s = json.loads(defined_term_set("Ex", "https://ex.com/glossary", [("Click map", "https://ex.com/glossary/click-map")]))
    assert s["hasDefinedTerm"][0]["@id"] == g[0]["@id"]  # hub and entry point at the same node
    print("glossary_schema smoke test: OK")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "set":
        sys.exit(_cli_set(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        _selftest()
        sys.exit(0)
    print(__doc__)
