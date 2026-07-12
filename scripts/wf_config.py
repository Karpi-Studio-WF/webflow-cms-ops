"""
wf_config.py — load Webflow credentials/config for the push scripts.

No dependencies. Import and call load_config():

    from wf_config import load_config
    cfg = load_config()                 # raises if a required key is missing
    token = cfg["WEBFLOW_API_TOKEN"]

Resolution order (later wins, so real env vars override the file):
  1. A .env file at the repo root (or the path in the WF_ENV_FILE env var)
  2. Real process environment variables (os.environ)

This means two ways to supply credentials:
  - Local:  create a .env file (run scripts/setup_env.py).
  - Remote / Claude Code web:  set WEBFLOW_API_TOKEN etc. as environment
    variables in the environment's settings — no file needed, no secret
    ever pasted into a chat.

Recognized keys:
    WEBFLOW_API_TOKEN     (required)  — Data API bearer token
    WEBFLOW_COLLECTION_ID (required)  — target CMS collection id
    WEBFLOW_BODY_FIELD    (optional)  — RichText field slug
    WEBFLOW_SITE_ID       (optional)  — site id for publish/list ops
    WEBFLOW_DB_PATH       (optional)  — absolute path to local SQLite DB
"""

import os

REQUIRED = ("WEBFLOW_API_TOKEN", "WEBFLOW_COLLECTION_ID")
KNOWN = REQUIRED + ("WEBFLOW_BODY_FIELD", "WEBFLOW_SITE_ID", "WEBFLOW_DB_PATH")


def _find_env_file():
    """Return the .env path to read, or None. Honors WF_ENV_FILE override."""
    override = os.environ.get("WF_ENV_FILE")
    if override:
        return override if os.path.exists(override) else None
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(repo_root, ".env")
    return candidate if os.path.exists(candidate) else None


def parse_env_file(path):
    """Minimal .env parser: KEY=VALUE per line, # comments, optional quotes."""
    values = {}
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            values[key] = val
    return values


def load_config(require=REQUIRED):
    """Load config from .env + environment. Raise SystemExit if a required key
    is missing. Pass require=() to load whatever is present without failing."""
    cfg = {}
    env_file = _find_env_file()
    if env_file:
        cfg.update({k: v for k, v in parse_env_file(env_file).items() if v != ""})
    # Real environment variables take precedence over the file.
    for key in KNOWN:
        if os.environ.get(key):
            cfg[key] = os.environ[key]

    missing = [k for k in require if not cfg.get(k)]
    if missing:
        raise SystemExit(
            "Missing required config: %s\n"
            "Supply it via environment variables or a .env file.\n"
            "Checked .env: %s\n"
            "Create one with:  python3 scripts/setup_env.py"
            % (", ".join(missing), env_file or "(none found)")
        )
    return cfg


if __name__ == "__main__":
    # Diagnostic: show what resolves, with the token masked.
    c = load_config(require=())
    for k in KNOWN:
        v = c.get(k, "")
        if k == "WEBFLOW_API_TOKEN" and v:
            v = ("*" * max(0, len(v) - 4)) + v[-4:]
        print("%-22s = %s" % (k, v or "(unset)"))
