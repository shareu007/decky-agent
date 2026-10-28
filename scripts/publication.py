"""The source and install archives deliberately have separate public manifests."""
from pathlib import Path

PUBLIC_DOCS = ("AUTH.md", "VOICE.md", "PERMISSIONS.md", "TESTING.md", "PRIVACY.md")
PUBLIC_ROOT = ("README.md", "README.zh-CN.md", "LICENSE", "THIRD_PARTY_NOTICES.md",
    "SECURITY.md", "CONTRIBUTING.md", "CHANGELOG.md", ".gitignore", ".gitattributes",
    "package.json", "package-lock.json", "plugin.json", "main.py", "requirements-dev.txt",
    "tsconfig.json", "rollup.config.js", "vite.config.ts", "index.html")
PRIVATE_NAMES = {"auth.json", "settings.json", "decky-account-context.json", ".DS_Store"}
PRIVATE_PARTS = {"__pycache__", "node_modules", ".venv", ".git", ".codex", ".agents", ".ssh", ".aws", ".private", "sessions", "speech", "diagnostics"}


def _walk(root: Path, folder: str, suffixes=None):
    start = root / folder
    if start.is_symlink():
        raise ValueError(f"Public directory is a symlink: {folder}")
    for path in sorted(start.rglob("*")):
        if not path.is_file() and not path.is_symlink():
            continue
        relative = path.relative_to(root)
        if any(part in PRIVATE_PARTS for part in relative.parts):
            continue
        if any(part.startswith(".") and not (i == 0 and part == ".github") for i, part in enumerate(relative.parts)):
            continue
        if path.name in PRIVATE_NAMES or path.suffix in {".pyc", ".log", ".wav", ".mp3", ".ogg", ".m4a", ".pem", ".key"}:
            continue
        if suffixes is None or path.suffix in suffixes:
            yield path


def _checked(root: Path, files):
    result = []
    for path in sorted(set(files)):
        cursor = root
        for part in path.relative_to(root).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError(f"Public file is a symlink: {path.relative_to(root)}")
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Public file is outside the project")
        if path.is_file():
            result.append(path)
    return result


def source_files(root: Path):
    files = [root / name for name in PUBLIC_ROOT]
    for folder, suffixes in (("src", {".ts", ".tsx"}), ("decky_agent", {".py"}),
        ("scripts", {".py", ".mjs", ".sh"}), ("tests", {".py", ".ts", ".tsx"}),
        (".github", {".yml", ".yaml"}), ("licenses", None)):
        files.extend(_walk(root, folder, suffixes))
    files += [root / "docs" / name for name in PUBLIC_DOCS]
    files += [root / "resources" / name for name in ("README.md", "codex-models.json")]
    files.extend(_walk(root, "docs/assets", {".svg"}))
    return _checked(root, files)


def release_files(root: Path, lite=False):
    names = ("package.json", "plugin.json", "main.py", "README.md", "README.zh-CN.md", "LICENSE",
        "THIRD_PARTY_NOTICES.md", "SECURITY.md", "CONTRIBUTING.md", "CHANGELOG.md")
    files = [root / name for name in names]
    for folder, suffixes in (("dist", {".js"}), ("decky_agent", {".py"}), ("licenses", None)):
        files.extend(_walk(root, folder, suffixes))
    files += [root / "docs" / name for name in PUBLIC_DOCS]
    files += [root / "resources" / name for name in ("README.md", "codex-models.json")]
    files.extend(_walk(root, "docs/assets", {".svg"}))
    if not lite:
        files += [root / "bin" / name for name in ("codex", "CODEX_RUNTIME.json")]
        files.extend(_walk(root, "bin/codex-runtime"))
    return _checked(root, files)


def frontend_source_files(root: Path):
    files = [root / name for name in ("package.json", "package-lock.json", "plugin.json", "tsconfig.json", "rollup.config.js")]
    files += [p for p in (root / "src").glob("*") if p.suffix in {".ts", ".tsx"}]
    return _checked(root, files)
