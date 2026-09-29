# projects/

One folder per site or client. Everything in here except this README is gitignored, so private decisions never reach the public repo, yet they sit side by side with the generic skill and ship inside the installed bundle.

```
projects/
  <project>/
    positions.md      ← required: copy of references/glossary-positions-template.md, filled in
    <anything else>   ← optional: notes, keyword lists, ownership maps, briefs
```

`positions.md` is the project's single source of site-specific facts: domain, collection IDs, field slugs, the title suffix the template appends, tools and methods the site actually uses, the ownership map, deliberate splits, rejected heads, voice rules, and where CMS writes are logged. Every reference in this skill stays generic; when a task names a site or client, the skill reads that project's `positions.md` and its values override the generic defaults.

Never put API tokens here. Tokens go in environment variables or a `.env` outside the bundle; `scripts/build_skill.py` refuses to build if it finds something that looks like one.

## Build one installable skill

```bash
python3 scripts/build_skill.py                             # uses ./projects
python3 scripts/build_skill.py --projects /path/to/private/projects
```

Output: `dist/webflow-cms-ops.skill` (a zip with a single `webflow-cms-ops/` folder). Upload it via the Claude skill upload UI; it replaces separate per-project skills.

Because this folder is gitignored, keep its source of truth somewhere private (a private repo, or a synced drive) and point `--projects` at it.
