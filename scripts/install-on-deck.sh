#!/bin/bash
# Run from Steam Deck desktop mode, after copying the release ZIP to the Deck.
set -euo pipefail
if [[ $(uname -s) != Linux || $(uname -m) != x86_64 ]]; then
  echo "此安装脚本仅用于 Steam Deck / Linux x86_64。" >&2
  exit 1
fi
if [[ $# -ne 1 || ! -f "$1" ]]; then
  echo '用法：bash install-on-deck.sh /path/to/decky-agent-0.1.9-steamdeck.zip' >&2
  exit 1
fi
agent_decky_home="${DECKY_HOME:-$HOME/homebrew}"
if [[ ! -d "$agent_decky_home/plugins" ]]; then
  echo "找不到 Decky 插件目录：$agent_decky_home/plugins。请先安装 Decky Loader。" >&2
  exit 1
fi
agent_stage=$(mktemp -d)
trap 'rm -rf -- "$agent_stage"' EXIT
python3 - "$1" "$agent_stage" <<'PY'
import sys, zipfile
from pathlib import Path, PurePosixPath
with zipfile.ZipFile(sys.argv[1]) as archive:
    for entry in archive.infolist():
        parts = PurePosixPath(entry.filename)
        if parts.is_absolute() or '..' in parts.parts or not parts.parts or parts.parts[0] != 'Decky Agent':
            raise SystemExit('插件包路径无效')
    archive.extractall(sys.argv[2])
root = Path(sys.argv[2]) / 'Decky Agent'
for name in ['plugin.json', 'package.json', 'main.py', 'dist/index.js']:
    if not (root / name).is_file():
        raise SystemExit('插件包缺少 ' + name)
for path in (root / 'bin').rglob('*'):
    if path.is_file():
        with path.open('rb') as handle:
            executable = path.name == 'codex' or handle.read(4) == b'\x7fELF'
        if executable:
            path.chmod(0o755)
PY
agent_target="$agent_decky_home/plugins/Decky Agent"
# Keep the previous installation as a reversible sibling backup.
if [[ -e "$agent_target" ]]; then
  agent_backup="$agent_decky_home/Decky-Agent-backup-$(date +%Y%m%d-%H%M%S)"
  sudo mv -- "$agent_target" "$agent_backup"
  echo "旧版本已备份至 $agent_backup"
fi
sudo cp -a -- "$agent_stage/Decky Agent" "$agent_target"
sudo chown -R "$(id -u):$(id -g)" "$agent_target"
sudo systemctl restart plugin_loader.service
echo '安装完成。返回游戏模式，打开 Decky → Decky Agent → 设置。'
