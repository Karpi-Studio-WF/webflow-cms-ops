#!/usr/bin/env python3
"""
audit_glossary.py — offline audit of a glossary, on a snapshot DB from snapshot_collections.py.

    python3 audit_glossary.py /abs/cms-snapshot/cms-2026-09-29.db --glossary glossary \\
        --body-field body --meta-title-max 45 --brand-suffix "Example Co" \\
        --schema-field term-schema > audit.md

Reports (markdown):
  1. Inbound links per entry, from inside and from outside the glossary
  2. Broken internal links (slug not in the snapshot), links to drafts, malformed hrefs
  3. Sibling terms named in an entry's text but never linked from its text
  4. Duplicate passages: word runs shared verbatim between entries
  5. One-way related-terms pairs (A lists B, B does not list A)
  6. AEO shape: answer block length, question H1, name not a question, meta lengths,
     stored brand suffix, FAQ questions duplicated across entries or answering another
     entry's H2
  7. Schema field (only with --schema-field): missing, invalid JSON, no DefinedTerm,
     name mismatch

Read-only. Sections 1-5 are the evidence base for a sweep (references/glossary-sweep.md);
section 6-7 check the entry anatomy in references/glossary-pattern.md. Numbers, not a plan:
a human reads the entries before deciding anything.

Verify --body-field first (often `body`, sometimes `body-2`). A wrong slug makes every
body-based check report zero; the script warns when no entry has the field.
"""
from __future__ import annotations

import argparse
import collections
import html as _html
import itertools
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from glossary_schema import answer_block, faq_pairs, h2_questions, visible  # noqa: E402

HREF = re.compile(r'\bhref=(["\'])(.*?)\1', re.I)


def norm_q(q: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", q.lower()).strip()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db")
    ap.add_argument("--glossary", required=True, help="collection short name of the glossary in the snapshot")
    ap.add_argument("--body-field", default="body", help="RichText field slug holding the entry body")
    ap.add_argument("--related-heading", default="Related terms",
                    help="heading text of a hardcoded related-terms block in the body; links under it do not count as in-text links")
    ap.add_argument("--shingle", type=int, default=8, help="words per shared run for duplicate detection")
    ap.add_argument("--min-dup-entries", type=int, default=2, help="report runs shared by at least N entries")
    ap.add_argument("--boilerplate-share", type=float, default=0.2,
                    help="ignore word runs present in more than this share of entries (template text)")
    ap.add_argument("--top", type=int, default=40, help="max rows per table")
    ap.add_argument("--answer-field", help="PlainText/RichText field holding the answer block; default: first <p> of the body")
    ap.add_argument("--answer-min", type=int, default=40)
    ap.add_argument("--answer-max", type=int, default=60)
    ap.add_argument("--meta-title-field", default="meta-title")
    ap.add_argument("--meta-title-max", type=int, default=60,
                    help="max stored length; subtract any suffix the template appends (see webflow-gotchas #9)")
    ap.add_argument("--meta-desc-field", default="meta-description")
    ap.add_argument("--meta-desc-max", type=int, default=155)
    ap.add_argument("--brand-suffix", help="brand text the template appends to titles; flagged if stored in the field")
    ap.add_argument("--schema-field", help="PlainText field holding the entry's JSON-LD (see glossary_schema.py)")
    a = ap.parse_args(argv)

    c = sqlite3.connect(a.db)
    G = a.glossary
    row = c.execute("SELECT url_prefix FROM collections WHERE name=?", (G,)).fetchone()
    if not row:
        sys.exit(f"Collection '{G}' not in {a.db}. Names present: "
                 + ", ".join(r[0] for r in c.execute("SELECT name FROM collections")))
    prefix = row[0].rstrip("/")
    entries = c.execute("SELECT slug, name, h1, is_draft, field_data_json FROM items "
                        "WHERE collection=? AND is_archived=0 ORDER BY slug", (G,)).fetchall()
    fd = {s: json.loads(j) for s, _, _, _, j in entries}
    raw = {s: fd[s].get(a.body_field) or "" for s in fd}
    slugs = set(fd)
    names = {s: (n or s) for s, n, _, _, _ in entries}
    REL = re.compile(rf"<h[2-4][^>]*>\s*{re.escape(a.related_heading)}\s*</h[2-4]>(.*?)(?=<h2|$)", re.S | re.I)

    def text_only(h: str) -> str:
        """Body HTML minus the related-terms block, as plain text lines."""
        h = REL.sub(" ", h)
        h = re.sub(r"</(p|h[1-6]|li|tr|div)>", "\n", h, flags=re.I)
        return _html.unescape(re.sub(r"<[^>]+>", " ", h))

    known = {}  # path -> is_draft
    for col, pre in c.execute("SELECT name, url_prefix FROM collections").fetchall():
        for s, d in c.execute("SELECT slug, is_draft FROM items WHERE collection=?", (col,)):
            known[pre.rstrip("/") + "/" + s] = d
    prefixes = [p.rstrip("/") for (p,) in c.execute("SELECT url_prefix FROM collections")]

    def p(*x):
        print(*x)

    p(f"# Glossary audit: `{G}` ({len(entries)} entries, prefix `{prefix}/`)\n")
    if entries and not any(raw.values()):
        p(f"> **WARNING:** no entry has a value in `{a.body_field}`. Body-based checks below are empty. "
          f"Fields present: {', '.join(sorted(next(iter(fd.values())).keys()))}\n")

    # 1. inbound links
    p("## 1. Inbound links\n")
    rows = c.execute("SELECT from_collection, from_slug, to_path FROM links WHERE to_path LIKE ?", (prefix + "/%",)).fetchall()
    inside, outside = collections.Counter(), collections.Counter()
    for fc, fs, tp in rows:
        t = tp[len(prefix) + 1:]
        if fc == G and fs != t:
            inside[t] += 1
        elif fc != G:
            outside[t] += 1
    p(f"Links into the glossary from other snapshotted collections: **{sum(outside.values())}**. "
      f"Glossary-to-glossary in-body links: **{sum(inside.values())}**. "
      f"Entries with zero inbound from outside: **{sum(1 for s in slugs if not outside[s])}**.\n")
    p("Least-linked entries first:\n")
    p("| Entry | In-glossary inbound | Outside inbound |\n|---|---|---|")
    for s in sorted(slugs, key=lambda s: (outside[s], inside[s], s))[:a.top]:
        p(f"| {s} | {inside[s]} | {outside[s]} |")

    # 2. link hygiene
    p("\n## 2. Broken, draft, and malformed links\n")
    bad = []
    for fc, fs, href, anchor, tp, internal in c.execute(
            "SELECT from_collection, from_slug, href, anchor, to_path, is_internal FROM links"):
        if not href.strip() or not (anchor or "").strip():
            bad.append((fc, fs, href, "empty href or anchor"))
        elif re.match(r"^https?://[a-z0-9-]+(/|$)", href) and "." not in href.split("/")[2]:
            bad.append((fc, fs, href, "malformed absolute URL (no domain)"))
        elif internal and tp and any(tp.startswith(px + "/") for px in prefixes):
            if tp not in known:
                bad.append((fc, fs, href, "slug not found under this prefix (404, or a renamed slug that may 301)"))
            elif known[tp]:
                bad.append((fc, fs, href, "target is a draft"))
    for col, s, text in c.execute("SELECT collection, slug, body_text FROM items ORDER BY collection, slug"):
        for m in re.findall(r"\[[^\]]+\]\([^)]+\)", text or ""):
            bad.append((col, s, m[:60], "raw markdown link in text"))
    p(f"{len(bad)} issues.\n")
    if bad:
        p("| From | Slug | Href | Issue |\n|---|---|---|---|")
        for r in bad:
            p(f"| {r[0]} | {r[1]} | `{r[2]}` | {r[3]} |")

    # 3. unlinked sibling mentions
    p("\n## 3. Sibling terms named but not linked\n")
    linked = collections.defaultdict(set)  # in-text links only (related-terms block excluded)
    for s, h in raw.items():
        for _q, href in HREF.findall(REL.sub(" ", h)):
            m = re.search(re.escape(prefix) + r"/([a-z0-9-]+)", href)
            if m:
                linked[s].add(m.group(1))

    def variants(name: str) -> set[str]:
        n = name.lower().strip()
        v = {n, n.rstrip("s")}
        if not n.endswith("s"):
            v.add(n + "s")
        return {x for x in v if len(x) >= 4}

    unl = []
    for s in sorted(slugs):
        low = text_only(raw[s]).lower()
        for t in sorted(slugs - {s}):
            if t in linked[s]:
                continue
            for v in variants(names[t]):
                m = re.search(rf"(?<![a-z]){re.escape(v)}(?![a-z])", low)
                if m:
                    unl.append((s, t, low[max(0, m.start() - 40): m.end() + 40].replace("\n", " ")))
                    break
    p(f"{len(unl)} unlinked mentions: the entry names a sibling term in its text but never links it in its text "
      f"(links under a '{a.related_heading}' heading do not count).\n")
    per = collections.Counter(u[0] for u in unl)
    if per:
        p("Most affected entries: " + ", ".join(f"{k} ({v})" for k, v in per.most_common(10)) + "\n")
    p("| Entry | Mentions | Context |\n|---|---|---|")
    for s, t, ctx in unl[:a.top]:
        p(f"| {s} | {t} | …{ctx.strip()}… |")

    # 4. duplicate passages
    p(f"\n## 4. Duplicate passages ({a.shingle}-word runs shared verbatim)\n")

    def words(t: str) -> list[str]:
        return re.findall(r"[a-z0-9%$./-]+", (t or "").lower())

    sh = collections.defaultdict(set)
    for s in slugs:
        for line in text_only(raw[s]).split("\n"):  # runs never cross a heading or paragraph
            w = words(line)
            for i in range(len(w) - a.shingle + 1):
                sh[" ".join(w[i:i + a.shingle])].add(s)
    cap = max(3, int(a.boilerplate_share * len(entries)))
    shared = {k: v for k, v in sh.items() if a.min_dup_entries <= len(v) <= cap}
    pair = collections.Counter()
    for v in shared.values():
        for x, y in itertools.combinations(sorted(v), 2):
            pair[(x, y)] += 1
    p(f"{len(shared)} shared runs (runs in more than {cap} entries are treated as template text and ignored). "
      f"Pairs of entries sharing the most text (N runs is roughly N+{a.shingle - 1} shared words):\n")
    p("| Entry A | Entry B | Shared runs |\n|---|---|---|")
    for (x, y), n in pair.most_common(a.top):
        p(f"| {x} | {y} | {n} |")

    def merge(runs: list[str]) -> list[str]:
        """Stitch overlapping shingles into longer passages."""
        runs = sorted(runs)
        out, used = [], set()
        for r in runs:
            if r in used:
                continue
            cur = r.split()
            used.add(r)
            grown = True
            while grown:
                grown = False
                tail = " ".join(cur[-(a.shingle - 1):])
                for r2 in runs:
                    if r2 not in used and r2.startswith(tail + " "):
                        cur.append(r2.split()[-1])
                        used.add(r2)
                        grown = True
                        break
            out.append(" ".join(cur))
        return out

    p("\nPassages repeated in the most entries (overlapping runs merged):\n")
    p("| Entries | Passage |\n|---|---|")
    groups = collections.defaultdict(list)  # same set of entries -> runs
    for k, v in shared.items():
        groups[frozenset(v)].append(k)
    rows_ = [(len(k), sorted(k), m) for k, rs in groups.items() for m in merge(rs)]
    rows_.sort(key=lambda r: (-r[0], -len(r[2])))
    for n, ents, m in rows_[:a.top]:
        p(f"| {n}: {', '.join(ents)[:120]} | “{m[:220]}” |")

    # 5. related-terms symmetry
    p("\n## 5. One-way related-terms pairs\n")
    try:
        rel = c.execute('SELECT from_slug, to_slug FROM "references" WHERE from_collection=? AND to_collection=?',
                        (G, G)).fetchall()
    except sqlite3.OperationalError:
        rel = c.execute("SELECT from_slug, to_slug FROM related_terms").fetchall()  # older snapshot schema
    rs = set(rel)
    oneway = sorted((x, y) for x, y in rs if (y, x) not in rs)
    p(f"{len(rs)} related-terms edges, {len(oneway)} one-way. Symmetry matters most for deliberate splits "
      f"and umbrella/child pairs; other one-way edges can be intentional.\n")
    if oneway:
        p("| Lists | Is not listed back by |\n|---|---|")
        for x, y in oneway[:a.top]:
            p(f"| {x} | {y} |")

    # 6. AEO shape
    p("\n## 6. AEO shape\n")
    shape = collections.defaultdict(list)  # check -> [(slug, detail)]
    faq_by_q = collections.defaultdict(list)
    h2_by_q = collections.defaultdict(list)
    for s, name, h1, _draft, _ in entries:
        body = raw[s]
        ans = visible(fd[s].get(a.answer_field) or "") if a.answer_field else answer_block(body)
        n = len(ans.split())
        if not ans:
            shape["answer block missing"].append((s, "no answer field value / no <p> in body"))
        elif not a.answer_min <= n <= a.answer_max:
            shape[f"answer block outside {a.answer_min}-{a.answer_max} words"].append((s, f"{n} words: {ans[:90]}…"))
        if not (h1 or "").strip():
            shape["H1 field empty"].append((s, ""))
        elif not h1.strip().endswith("?"):
            shape["H1 is not a question"].append((s, h1))
        if re.match(r"^(what|how|why|when|who)\b", (name or "").strip(), re.I) or (name or "").strip().endswith("?"):
            shape["name is phrased as a question (should be the bare term)"].append((s, name))
        mt = (fd[s].get(a.meta_title_field) or "").strip()
        md = (fd[s].get(a.meta_desc_field) or "").strip()
        if not mt:
            shape["meta title empty"].append((s, ""))
        elif len(mt) > a.meta_title_max:
            shape[f"meta title over {a.meta_title_max} chars"].append((s, f"{len(mt)}: {mt}"))
        if a.brand_suffix and mt and a.brand_suffix.lower() in mt.lower():
            shape["brand suffix stored in meta title (template appends it)"].append((s, mt))
        if not md:
            shape["meta description empty"].append((s, ""))
        elif len(md) > a.meta_desc_max:
            shape[f"meta description over {a.meta_desc_max} chars"].append((s, f"{len(md)} chars"))
        for q, _ans in faq_pairs(body):
            faq_by_q[norm_q(q)].append((s, q))
        for q in h2_questions(body):
            h2_by_q[norm_q(q)].append(s)
    for nq, hits in faq_by_q.items():
        owners = sorted({s for s, _ in hits})
        if len(owners) > 1:
            shape["same FAQ question in several entries"].append((", ".join(owners), hits[0][1]))
        for s2 in sorted(set(h2_by_q.get(nq, [])) - set(owners)):
            shape["FAQ question is another entry's H2"].append((f"{owners[0]} → {s2}", hits[0][1]))
    total = sum(len(v) for v in shape.values())
    p(f"{total} findings across {len(shape)} checks. Answer block source: "
      f"{'field `' + a.answer_field + '`' if a.answer_field else 'first <p> of the body'}.\n")
    if shape:
        p("| Check | Count |\n|---|---|")
        for k, v in sorted(shape.items(), key=lambda kv: -len(kv[1])):
            p(f"| {k} | {len(v)} |")
        for k, v in sorted(shape.items(), key=lambda kv: -len(kv[1])):
            p(f"\n### {k}\n\n| Entry | Detail |\n|---|---|")
            for s, d in v[:a.top]:
                p(f"| {s} | {str(d).replace('|', '/')} |")

    # 7. schema field
    if a.schema_field:
        p(f"\n## 7. Schema field `{a.schema_field}`\n")
        issues = []
        for s, name, _h1, _d, _ in entries:
            v = (fd[s].get(a.schema_field) or "").strip()
            if not v:
                issues.append((s, "empty"))
                continue
            try:
                data = json.loads(v)
            except ValueError as e:
                issues.append((s, f"invalid JSON: {e}"))
                continue
            nodes = data.get("@graph", [data]) if isinstance(data, dict) else []
            terms = [n for n in nodes if isinstance(n, dict) and n.get("@type") == "DefinedTerm"]
            if not terms:
                issues.append((s, "no DefinedTerm node"))
            elif (terms[0].get("name") or "").strip().lower() != (name or "").strip().lower():
                issues.append((s, f"DefinedTerm name '{terms[0].get('name')}' != entry name '{name}'"))
            if re.search(r"</script", v, re.I):
                issues.append((s, "unescaped </script> would close the template tag"))
        p(f"{len(issues)} issues in {len(entries)} entries.\n")
        if issues:
            p("| Entry | Issue |\n|---|---|")
            for s, i in issues[:max(a.top, 100)]:
                p(f"| {s} | {i} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
