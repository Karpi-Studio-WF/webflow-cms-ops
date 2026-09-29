#!/usr/bin/env python3
"""
build_skill.py — package this repo plus private project folders into one installable skill.

    python3 scripts/build_skill.py                                  # projects from ./projects
    python3 scripts/build_skill.py --projects /abs/private/projects # projects kept elsewhere
    python3 scripts/build_skill.py --out /abs/dist/webflow-cms-ops.skill

The public repo holds only the generic skill. Per-site folders (projects/<name>/positions.md
and notes) are gitignored. This script zips both into dist/webflow-cms-ops.skill, a zip
with a single top-level `webflow-cms-ops/` folder, ready for the Claude skill upload UI.

Included: every file git tracks (so local scratch, snapshots and caches never ship), plus
every file under the projects directory. Refuses to build if a project file contains
something that looks like an API token or key.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAME = "webflow-cms-ops"

# Webflow tokens are 64 hex chars; Anthropic keys start sk-ant-; generic KEY=value assignments.
SECRET = re.compile(
    r"\b[0-9a-f]{64}\b"
    r"|sk-ant-[A-Za-z0-9_-]{10,}"
    r"|\b(?:WEBFLOW_API_TOKEN|WF_TOKEN|API_TOKEN|ANTHROPIC_API_KEY)\s*=\s*[\"']?[A-Za-z0-9_-]{16,}",
    re.I)
SKIP = {"__pycache__", ".DS_Store"}


def tracked_files() -> list[pathlib.Path]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True).stdout
    return [ROOT / p for p in out.decode().split("\0") if p]


def project_files(projects: pathlib.Path) -> list[pathlib.Path]:
    if not projects.is_dir():
        return []
    return sorted(p for p in projects.rglob("*")
                  if p.is_file() and not SKIP.intersection(p.parts) and p.name != "README.md")


def scan(files: list[pathlib.Path]) -> list[str]:
    hits = []
    for f in files:
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if SECRET.search(line):
                hits.append(f"{f}:{n}")
    return hits


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--projects", default=str(ROOT / "projects"), help="directory holding <project>/positions.md folders")
    ap.add_argument("--out", default=str(ROOT / "dist" / f"{NAME}.skill"))
    a = ap.parse_args(argv)

    projects = pathlib.Path(a.projects).resolve()
    base = tracked_files()
    extra = project_files(projects)
    hits = scan(extra)
    if hits:
        sys.exit("Refusing to build: possible secrets in project files:\n  " + "\n  ".join(hits))
    missing = [d.name for d in projects.iterdir() if d.is_dir() and not (d / "positions.md").exists()] if projects.is_dir() else []
    if missing:
        print(f"WARNING: project folders without positions.md: {', '.join(missing)}")

    out = pathlib.Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in base:
            if f.is_file() and not SKIP.intersection(f.parts):
                z.write(f, f"{NAME}/{f.relative_to(ROOT).as_posix()}")
        for f in extra:
            z.write(f, f"{NAME}/projects/{f.relative_to(projects).as_posix()}")

    names = sorted({f.relative_to(projects).parts[0] for f in extra})
    print(f"wrote {out}")
    print(f"  {len(base)} skill files + {len(extra)} project files; projects: {', '.join(names) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
