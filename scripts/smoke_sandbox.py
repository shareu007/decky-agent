#!/usr/bin/env python3
"""Check Codex's native Linux workspace sandbox without a model/API call."""
import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default=shutil.which("codex"))
    args = parser.parse_args()
    if not args.codex:
        raise SystemExit("Codex binary not found; pass --codex PATH")
    cache = Path.home() / ".cache"
    cache.mkdir(exist_ok=True)
    # Codex deliberately refuses helper aliases under /tmp. Use a private,
    # short-lived CODEX_HOME in the user cache without changing ~/.codex.
    with tempfile.TemporaryDirectory(prefix="decky-sandbox-check-", dir=cache) as directory:
        root = Path(directory)
        workspace = root / "workspace"
        workspace.mkdir()
        home = root / "codex"
        home.mkdir()
        script = """import errno,json,sys
from pathlib import Path
Path('inside.txt').write_text('sandbox check')
blocked=False
try:
    Path(sys.argv[1]).write_text('must be blocked')
except OSError as error:
    if error.errno not in (errno.EACCES,errno.EPERM,errno.EROFS):
        raise
    blocked=True
print(json.dumps({'inside_write':Path('inside.txt').exists(),'outside_write_blocked':blocked}))
raise SystemExit(0 if blocked else 1)
"""
        result = subprocess.run([
            args.codex, "sandbox", "-P", ":workspace", "-C", str(workspace), "--",
            "/usr/bin/python3", "-c", script, str(root / "outside.txt"),
        ], env=dict(os.environ, CODEX_HOME=str(home)), capture_output=True, text=True, timeout=25)
        if result.returncode:
            raise SystemExit("Codex sandbox failed: " + result.stderr[-2000:])
        metrics = json.loads(result.stdout)
        assert metrics["inside_write"] and metrics["outside_write_blocked"]
        assert not (root / "outside.txt").exists()
        print(json.dumps({"native_codex_sandbox": "PASS", **metrics}))


if __name__ == "__main__":
    main()
