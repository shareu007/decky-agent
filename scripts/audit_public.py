#!/usr/bin/env python3
"""Scan only public candidates; never print the matched private data.

Use Gitleaks as an additional independent credential scanner before publication.
"""
import argparse
import ipaddress
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.publication import PRIVATE_NAMES, PRIVATE_PARTS, source_files

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "credential": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "developer-home": re.compile(r"/(?:Users|home|var/home)/(?!deck(?:/|\b)|user(?:/|\b)|example(?:/|\b))[A-Za-z0-9][A-Za-z0-9._-]{1,64}/"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})"),
    "network-address": re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])"),
}
EXAMPLE_NETWORKS = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]


def inspect_entries(entries):
    issues = []
    for name, payload in entries:
        path = PurePosixPath(name)
        if (path.is_absolute() or ".." in path.parts or path.name in PRIVATE_NAMES
                or any(p in PRIVATE_PARTS or p.startswith(".env") for p in path.parts)
                or path.suffix.lower() in {".pem", ".key", ".wav", ".mp3", ".m4a", ".ogg", ".log", ".pyc"}
                or ("docs" in path.parts and path.name.startswith(("DEPLOYMENT-", "FIXES-", "REVIEW-")))):
            issues.append({"file": name, "rule": "private-file"})
            continue
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            if not name.startswith("Decky Agent/bin/codex-runtime/"):
                issues.append({"file": name, "rule": "unexpected-binary"})
            continue
        third_party = "licenses" in path.parts or name.startswith("Decky Agent/bin/codex-runtime/") or path.name == "codex-models.json"
        registry_emails = set()
        if path.name == "package-lock.json":
            try:
                for package_path, package in json.loads(text).get("packages", {}).items():
                    warning = package.get("deprecated", "")
                    if package_path.startswith("node_modules/") and isinstance(warning, str):
                        registry_emails.update(m.group() for m in PATTERNS["email"].finditer(warning))
            except (ValueError, AttributeError):
                pass
        for number, line in enumerate(text.splitlines(), 1):
            for rule, pattern in PATTERNS.items():
                for match in pattern.finditer(line):
                    if rule == "email":
                        domain = match.group(1).lower()
                        if third_party or domain in {"example.com", "example.org", "example.net", "example.invalid"} or domain.endswith(".example"):
                            continue
                        # Public npm deprecation notices can include the upstream
                        # maintainer's contact. Root package author fields do not
                        # receive this exception.
                        if match.group() in registry_emails and line.lstrip().startswith('"deprecated":'):
                            continue
                    if rule == "network-address":
                        try:
                            address = ipaddress.ip_address(match.group())
                        except ValueError:
                            continue
                        if third_party or address.is_loopback or not address.is_private or any(address in n for n in EXAMPLE_NETWORKS):
                            continue
                    issues.append({"file": name, "line": number, "rule": rule})
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--tracked", action="store_true", help="Check the exact Git index, rejecting files outside the public manifest")
    group.add_argument("--archive", type=Path, help="Check an install ZIP, including its frontend source")
    parser.add_argument("--export", type=Path, help="Export audited public source to an empty directory")
    args = parser.parse_args()
    approved = source_files(ROOT)
    if args.archive:
        with zipfile.ZipFile(args.archive) as archive:
            entries = [(name, archive.read(name)) for name in archive.namelist() if not name.endswith("/")]
    elif args.tracked:
        paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().rstrip("\0").split("\0")
        allowed = {p.relative_to(ROOT).as_posix() for p in approved}
        unexpected = [p for p in paths if p and p not in allowed]
        if unexpected:
            print(json.dumps({"status": "FAIL", "issues": [{"file": p, "rule": "outside-public-manifest"} for p in unexpected]}))
            return 1
        entries = [(p, subprocess.check_output(["git", "show", ":" + p], cwd=ROOT)) for p in paths if p]
    else:
        entries = [(p.relative_to(ROOT).as_posix(), p.read_bytes()) for p in approved]
    issues = inspect_entries(entries)
    print(json.dumps({"status": "FAIL" if issues else "PASS", "files": len(entries), "issues": issues}, ensure_ascii=False))
    if issues:
        return 1
    if args.export:
        if args.tracked or args.archive:
            raise ValueError("Export uses audited source candidates only")
        args.export.mkdir(parents=True, exist_ok=True, mode=0o700)
        if any(args.export.iterdir()):
            raise ValueError("Audit export directory must be empty")
        for p in approved:
            destination = args.export / p.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
