#!/usr/bin/env python3
"""Build an installable Decky zip without development files or secrets."""
import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.publication import frontend_source_files, release_files


def package(lite=False):
    version = json.loads((ROOT / "package.json").read_text())["version"]
    if not (ROOT / "dist" / "index.js").exists():
        raise ValueError("请先运行 npm run build")
    if not lite and not (ROOT / "bin" / "codex").exists():
        raise ValueError("请先运行 python3 scripts/bundle_codex.py；只打兼容模式包请加 --lite")
    files = release_files(ROOT, lite=lite)
    source_files = frontend_source_files(ROOT)
    output = ROOT / "out"
    output.mkdir(exist_ok=True)
    path = output / f"decky-agent-{version}-{'lite' if lite else 'steamdeck'}.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in files:
            archive.write(file, "Decky Agent/" + file.relative_to(ROOT).as_posix())
        # Supply the frontend and build inputs so its LGPL library can be replaced.
        for file in source_files:
            archive.write(file, "Decky Agent/source/" + file.relative_to(ROOT).as_posix())
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    path.with_suffix(".zip.sha256").write_text(f"{digest}  {path.name}\n")
    shutil.copy2(ROOT / "scripts" / "install-on-deck.sh", output / "install-on-deck.sh")
    print(f"{path} ({path.stat().st_size / 1024 / 1024:.1f} MiB)\nSHA256 {digest}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lite", action="store_true", help="Omit Codex; compatible API mode still works")
    package(parser.parse_args().lite)
