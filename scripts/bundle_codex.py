#!/usr/bin/env python3
"""Bundle the official, integrity-checked Linux x64 npm distribution."""
import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.164.0"
INTEGRITY = "sha512-XLAoaWsGOT2khzl+P4FYDPTkzAr9W0VFXFaVkqlFdkM0soa1gH/4S0wSD57Ek3HHwkirAEGz2/Mwehseh+l5Mg=="
PREFIX = "package/vendor/x86_64-unknown-linux-musl/"


def bundle(archive: Path):
    with archive.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha512").digest()
    if "sha512-" + base64.b64encode(digest).decode() != INTEGRITY:
        raise ValueError("Codex 包的 SHA-512 与固定的官方 npm 完整性值不符")
    target = ROOT / "bin" / "codex-runtime"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if not member.name.startswith(PREFIX) or not member.isfile():
                continue
            relative = PurePosixPath(member.name[len(PREFIX):])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("不安全的归档路径")
            path = target / str(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as source, path.open("wb") as dest:
                shutil.copyfileobj(source, dest)
            path.chmod(0o755 if member.mode & 0o111 else 0o644)
    binary = target / "bin" / "codex"
    with binary.open("rb") as handle:
        header = handle.read(20)
    if header[:4] != b"\x7fELF" or header[18:20] != b"\x3e\x00":
        raise ValueError("运行时不是 Linux x86_64 ELF")
    # Preserve upstream resource layout (bwrap, rg, code-mode host, voice licenses).
    launcher = ROOT / "bin" / "codex"
    launcher.write_text('#!/bin/sh\nset -eu\nagent_bin_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexec "$agent_bin_dir/codex-runtime/bin/codex" "$@"\n')
    launcher.chmod(0o755)
    (ROOT / "bin" / "CODEX_RUNTIME.json").write_text(json.dumps({
        "version": VERSION, "platform": "linux-x64", "integrity": INTEGRITY,
        "source": f"https://registry.npmjs.org/@openai/codex/-/codex-{VERSION}-linux-x64.tgz",
    }, indent=2) + "\n")
    print(f"Bundled Codex {VERSION} (Linux x86_64), upstream resources preserved")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Use an already downloaded official npm archive")
    args = parser.parse_args()
    if args.archive:
        bundle(args.archive)
    else:
        with tempfile.TemporaryDirectory(prefix="decky-agent-codex-") as directory:
            result = subprocess.run([
                "npm", "pack", f"@openai/codex@{VERSION}-linux-x64", "--ignore-scripts",
                "--pack-destination", directory, "--json",
            ], check=True, capture_output=True, text=True, cwd=ROOT)
            package = json.loads(result.stdout)[0]
            bundle(Path(directory) / package["filename"])
