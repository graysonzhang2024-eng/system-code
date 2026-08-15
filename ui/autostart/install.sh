#!/bin/bash
# 安装开机自启(macOS launchd)—— 开发模式浮窗
# 用法: bash ui/autostart/install.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UI_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PLIST_TEMPLATE="$SCRIPT_DIR/com.steward.floatwin.plist.template"
PLIST_DST="$HOME/Library/LaunchAgents/com.steward.floatwin.plist"
LOG_DIR="${TMPDIR:-/tmp}"
LAUNCH_DOMAIN="gui/$(id -u)"
SERVICE_TARGET="$LAUNCH_DOMAIN/com.steward.floatwin"

# 安装时解析 Electron.app 的原生可执行文件。不要使用 .bin/electron；它依赖 PATH 中的 node。
python3 "$SCRIPT_DIR/generate_plist.py" \
  --template "$PLIST_TEMPLATE" \
  --destination "$PLIST_DST" \
  --ui-dir "$UI_DIR" \
  --log-dir "$LOG_DIR"
echo "已生成配置到 $PLIST_DST"

# 幂等替换旧服务，并确保新配置立即启动。
launchctl bootout "$SERVICE_TARGET" 2>/dev/null || true
launchctl bootstrap "$LAUNCH_DOMAIN" "$PLIST_DST"
launchctl enable "$SERVICE_TARGET"
launchctl kickstart -k "$SERVICE_TARGET"
echo "已加载 launchd 任务 com.steward.floatwin"
echo "验证: launchctl list | grep steward"
echo "卸载: launchctl bootout $SERVICE_TARGET"
echo "日志: $LOG_DIR/steward-floatwin.err.log"
