#!/bin/bash
# 安装开机自启(macOS launchd)—— 开发模式浮窗
# 用法: bash ui/autostart/install.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UI_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PLIST_TEMPLATE="$SCRIPT_DIR/com.steward.floatwin.plist.template"
PLIST_DST="$HOME/Library/LaunchAgents/com.steward.floatwin.plist"
ELECTRON_BIN="$UI_DIR/node_modules/.bin/electron"
LOG_DIR="${TMPDIR:-/tmp}"

if [ ! -x "$ELECTRON_BIN" ]; then
  echo "未找到 Electron: $ELECTRON_BIN" >&2
  echo "请先在 ui 目录安装依赖。" >&2
  exit 1
fi

mkdir -p "$(dirname "$PLIST_DST")"

# launchd 需要绝对路径；安装时由本机实际仓库位置生成，模板本身不保存个人路径。
python3 - "$PLIST_TEMPLATE" "$PLIST_DST" "$ELECTRON_BIN" "$UI_DIR" "$LOG_DIR" <<'PY'
from pathlib import Path
import sys

template, destination, electron, ui_dir, log_dir = map(Path, sys.argv[1:])
content = template.read_text(encoding="utf-8")
content = content.replace("__ELECTRON_BIN__", str(electron.resolve()))
content = content.replace("__UI_DIR__", str(ui_dir.resolve()))
content = content.replace("__LOG_DIR__", str(log_dir.resolve()))
destination.write_text(content, encoding="utf-8")
PY
echo "已生成配置到 $PLIST_DST"

# 卸载旧的(若已加载),再加载新的
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"
echo "已加载 launchd 任务 com.steward.floatwin"
echo "验证: launchctl list | grep steward"
echo "卸载: launchctl unload $PLIST_DST"
echo "日志: /tmp/steward-floatwin.err.log"
