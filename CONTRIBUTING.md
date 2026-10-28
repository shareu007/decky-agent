# Contributing

Small, focused fixes and reproducible device reports are welcome. For interface changes, check both 中文 and English at a 320 px sidebar width. State the operating system, Decky version and plugin version without including a device hostname or username.

## Local checks

```bash
npm ci
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm run check
python scripts/audit_public.py
```

Use the browser preview for layout and simulated interaction. Use the local-only Codex checks in [TESTING.md](docs/TESTING.md) for protocol behavior. Do not send real model requests, make recordings or run device commands just to test a documentation change.

## Before publishing

The public source and install archives use explicit manifests in `scripts/publication.py`. Local deployment and debugging notes, credentials, runtime data, recordings, development environments, generated bundles and old install packages stay outside Git. Release ZIPs are rebuilt from the public manifest; a `.gitignore` entry alone does not protect a ZIP.

Run `python scripts/audit_public.py --tracked` after staging, then scan the Git history with Gitleaks using `--redact`. Run the archive check on each release ZIP as well. Never attach local configuration, Codex authentication files or unredacted logs to an issue.

Include a brief description of the behavior and relevant validation in pull requests. Keep third-party notices and the rebuildable frontend source when changing packaging. Report security-sensitive issues through [SECURITY.md](SECURITY.md).
