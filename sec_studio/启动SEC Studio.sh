#!/usr/bin/env bash
# One-click local web launcher for Linux and macOS.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$(dirname "$HERE")"
PORT="${SEC_STUDIO_PORT:-8731}"

if command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON="$(command -v python)"
else
  echo "找不到 Python 3。请先安装 Python 3，再安装 sec_studio/requirements.txt 中的依赖。"
  read -r -p "按回车退出..."
  exit 1
fi

cd "$HERE"
echo "SEC Studio 正在启动，浏览器将打开 http://127.0.0.1:${PORT}/"
echo "关闭此窗口即可停止服务。"
exec "$PYTHON" app.py --data-dir "$DATA_DIR" --host 127.0.0.1 --port "$PORT"
