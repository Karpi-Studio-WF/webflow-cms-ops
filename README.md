# webflow-cms-ops

A Claude skill for bulk-publishing and editorial fix passes on Webflow CMS. Built from production use pushing 281 articles with 796 API writes and zero failures.

## What this is

A single Claude skill that covers five related content operations on Webflow CMS:

- **Bulk push** — send new or updated content from a local source (SQLite, markdown, CSV) to a Webflow CMS collection at scale, beyond what the MCP or Designer handle well.
- **Editorial fix pass** — run a targeted rewrite across existing items (strip a phrase, remove meta-content leaks, swap a heading, rewrite formulaic openers) as a repeatable, resume-safe, rollback-friendly sweep.
- **Vision pipeline** — bulk-generate content from binary assets (alt text from images, summaries from PDFs, image categorization) and push back as field updates, including the multi-image field array schema. For the common alt-text-on-a-gallery-field job specifically, `references/multi-image-alt-text.md` is a complete, project-agnostic runbook (discover → pull → caption → review → push → publish) you can copy-paste and run locally.
- **Content shape repair**: reshape legacy markup on stored CMS field values to a new target shape across many items (legacy code blocks to round-trip-safe `<pre><code>`, brand suffix stripped from `meta-title`, deprecated schema property renames, broken tables restored, etc.). Workflow: audit, snapshot, transform with an idempotent pure function, diff, stage push, human publishes from the Designer.
- **Secondary JSON-LD via CMS field**: inject per-article secondary schema (FAQPage, HowTo, Product, Review, BreadcrumbList) alongside the page's primary schema. One-time setup creates a dedicated CMS field and a template embed; per-article workflow extracts the content (Q&As, steps, etc.) from the body and writes the JSON-LD object into the field. Same harness as content-repair, in cross-field mode (read body, write to dedicated field).

The skill handles the known gotchas that waste a first-time user's first production session: macOS SSL cert issues, the Webflow RichText whitespace-between-tags parser bug, slug soft-delete traps, background agent deadlocks, the 32MB request cap on cumulative image Reads, and more. Each is documented with symptoms and fixes in `references/webflow-gotchas.md`.

## Structure

```
webflow-cms-ops/
├── SKILL.md                         ← entry point, always loaded
├── references/
│   ├── push-pattern.md              ← bulk push pattern, full push loop, multi-image field PATCH
│   ├── fix-pass-pattern.md          ← six-step editorial fix pattern
│   ├── content-repair-pattern.md    ← shape repair on stored CMS field values (legacy markup migration)
│   ├── faqpage-schema.md            ← FAQPage and other secondary JSON-LD via a dedicated CMS field
│   ├── webflow-gotchas.md           ← gotchas with symptoms and fixes
│   ├── webflow-richtext-tables.md   ← HTML <table> in RichText (markdown tables don't work)
│   ├── vision-pipeline.md           ← bulk content generation from binaries (alt text, summaries)
│   ├── multi-image-alt-text.md      ← end-to-end alt-text pipeline for multi-image/gallery fields + local runbook
│   └── session-handoff.md           ← split a heavy batch across two chats via filesystem
├── scripts/
│   ├── compact.py                   ← HTML compact helper (required before every push)
│   ├── push_template.py             ← standalone runnable push script
│   └── repair_template.py           ← standalone runnable repair script (content-repair-pattern)
└── examples/
    └── minimal-example.md           ← end-to-end walkthrough for 10 markdown files
```

## How the skill bundle is organized

`SKILL.md` is the entry point. When invoked, Claude reads it and decides which reference file(s) to load based on the specific task — push, fix pass, or troubleshooting a Webflow gotcha. References are loaded on-demand, keeping context clean.

Scripts are executed via Bash, not read into context. They're reference-quality production code with inline comments explaining every design decision.

## Installation

### As a Claude skill (Claude.ai / Claude Code)

1. Download or clone this repo.
2. Zip the `webflow-cms-ops/` folder (not its contents — zip the folder itself).
3. Upload the zip via Claude's skill upload UI.

### As a Claude Code project-level skill

Copy the folder into your project's `.claude/skills/` directory:

```bash
cp -r webflow-cms-ops /your/project/.claude/skills/
```

Restart Claude Code. The skill will be available in the skill index for that project.

### As a standalone Python pipeline (no Claude)

The scripts work independently of Claude:

```bash
pip3 install certifi markdown
# Copy scripts/push_template.py to your project, edit CONFIG block, run
python3 push_template.py
```

## Requirements

- Python 3.9+
- `certifi` — required for macOS, harmless on Linux (`pip3 install certifi`)
- `markdown` — only if generating HTML from markdown source (`pip3 install markdown`)
- A Webflow site with API access and a Data API token (CMS read/write scope)

## Why this exists

Webflow's CMS wasn't built for 300-article bulk uploads. The official tooling hits walls fast:

- CSV imports reserve slugs permanently on soft-delete, breaking re-imports.
- The Webflow MCP works for small batches but deadlocks in background Claude Code agents because interactive permission prompts can't reach a headless process.
- Manual editing in Designer doesn't scale past a few dozen items.
- The Data API is powerful but has undocumented behaviors (whitespace-sensitive RichText parsing, field slug quirks) that burn iterations to discover.

This skill and its scripts are the result of solving each of those problems in production.

## Companion articles

Deep-dive write-ups of the patterns in this skill:

- [How to Bulk-Publish Content to Webflow CMS With Python and Claude Code](https://www.karpi.studio/blog/bulk-publish-webflow-cms-python-claude-code) — the technical playbook, with code walkthroughs for every step.
- [How We Built a 281-Article Schema Glossary Using Claude Code](https://www.karpi.studio/blog/223-schema-articles-claude-code) — the case study that produced this toolkit, including the debugging arc that uncovered each gotcha.

## Contributing

Hit a Webflow gotcha not documented here? Open an issue or PR. The goal is to capture every hard-won lesson so the next person doesn't pay to learn it too.

## License

MIT. Use freely in commercial and personal projects.

## Credits

Developed at [Karpi Studio](https://www.karpi.studio) during the build of the [Schema HQ glossary](https://www.karpi.studio/resources/schema-glossary).
