# Glossary Sweep: Audit and Clean Up an Existing Glossary

Use this when a glossary already exists and its entries have started repeating each other, contradicting the site's articles, or linking poorly, or when taking over a client's glossary for AEO work. The target state is defined in `references/glossary-pattern.md`; this reference is the route from what exists to that state. Everything before step 6 is read-only.

## 1. Snapshot the CMS locally

```bash
export WEBFLOW_API_TOKEN=...   # CMS read scope is enough
python3 scripts/snapshot_collections.py --site-domain example.com --out /abs/path/cms-snapshot \
  --collection <glossary-collection-id>:glossary:/glossary/ \
  --collection <guides-collection-id>:guides:/guides/ \
  --collection <blog-collection-id>:blog:/blog/
```

Include every collection that links to the glossary or competes with it (guides, blog, other glossaries). Inbound links from a collection you did not snapshot are invisible to the audit. The CMS is the source of truth; local drafts are usually older. Find collection IDs with `GET /v2/sites/{site_id}/collections` (the `0_discover.py` script in `multi-image-alt-text.md` lists them).

## 2. Run the automatic audit

```bash
python3 scripts/audit_glossary.py /abs/path/cms-snapshot/cms-<date>.db --glossary glossary \
  --body-field body --meta-title-max 45 --brand-suffix "Example Co" > audit.md
```

Check `--body-field` first. If the output starts with a WARNING that no entry has that field, the slug is wrong (often `body-2`). Add `--answer-field` if the collection has a dedicated answer field, and `--schema-field` once schema is set up.

The audit gives the numbers: inbound links, broken and draft links, unlinked sibling mentions, duplicate passages, one-way related-terms pairs, and the AEO shape checks. It is the evidence base, not the plan. It finds text repeated word for word; it cannot find the same concept re-explained in different words. Only reading finds that.

## 3. Split into lanes and read the entries

Split the glossary into topic lanes (e.g. testing, behavior analytics, metrics, tools), plus one cross-cutting link lane and one gap-term lane. With subagents, run the lanes in parallel; they only read local files, so the background-agent deadlock (`webflow-gotchas.md` #6) does not apply. Give every lane the same written brief: the goal, the read-only rule, the deliberate splits and rejected heads from the positions file, the snapshot paths (`text/<collection>/<slug>.txt` is easiest to read), and the report format. Each lane returns:

1. **Concept ownership map:** concept | owner | entries re-explaining it | approximate duplicate words.
2. **Per-entry actions:** KEEP / TRIM (quote the first ~10 words of the passage to cut, and the link that replaces it) / REFOCUS / MERGE / NEW, plus the entry's differs line.
3. **Link fixes.**
4. **Contradictions** with live articles, or with how the business actually works (the positions file).

## 4. Verify before you trust

Spot-check lane claims against the DB: a broken link, a missing link, a count. Lanes sometimes disagree, for example on who owns a concept or whether a new entry is needed. Resolve each disagreement with the ownership tests in `glossary-pattern.md` and record which way you went and why.

## 5. Decisions and the change table

Collect the calls only the site owner can make (which tool is the default, which method the team uses, which article owns a definition, new entries yes or no) and ask them in one list, each with a recommendation. Record the answers in the positions file.

Then write one change table: every page that changes, the action, and what changes. Group it by cluster. Include live articles and housekeeping (READMEs, pipeline scripts that would overwrite the changes). End with open questions. Get approval on the table. Never edit before it is approved.

## 6. Execute per cluster

1. GET fresh from the CMS immediately before editing each cluster (another session may have written since the snapshot).
2. Edit with the matching mechanism: `content-repair-pattern.md` and `scripts/repair_template.py` when the CMS is the source, `fix-pass-pattern.md` when a local markdown source exists and is current.
3. Show a before/after per cluster. Push only on approval.
4. Log the write in the project's write log, have the items published, re-snapshot, re-run the audit, and confirm the numbers moved.

Order: pipeline safety fixes first (a script that would silently revert the changes), then hard errors (broken links), then dedup trims, then in-text linking, then live-article fixes, then new entries, then schema (`glossary-pattern.md`, workflow E), then link-backs from the rest of the site once the glossary is live.

## Common findings

From the 71-entry CRO glossary sweep that produced this workflow:

- Shared platform how-tos (install a script, track a form success) repeated across many entries. Pick one owner.
- Children not linking their umbrella; the umbrella absorbing a child's mechanics.
- A pipeline script that would silently revert CMS changes (e.g. writing the H1 back into `name` on the next sync).
- Live articles contradicting the glossary on numbers, tools or method.
- Dated facts (prices) living in five places.
- Zero inbound links from the rest of the site.
- A hardcoded "Related terms" block in the body duplicating the MultiReference field (`--related-heading` keeps its links out of the in-text link count).

## Report template

```
=== Glossary Sweep Report ===
Glossary:          <collection> (<N> entries)
Snapshot:          <db path>
Before → after:    inbound from site <a> → <b> | broken links <a> → <b> |
                   unlinked mentions <a> → <b> | duplicate runs <a> → <b> |
                   AEO shape findings <a> → <b>
Entries changed:   <N> (trim <n>, refocus <n>, merge <n>, new <n>)
Decisions logged:  <positions file path>
Open questions:    <list>
```
