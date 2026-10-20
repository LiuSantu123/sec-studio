#!/usr/bin/env bash
# 在【Mac mini】上运行：把集群上的 SEC Studio 端口转发到本机。
#
#   ./mac-tunnel.sh                # 默认 ssh 别名 zheng，端口 8731
#   ./mac-tunnel.sh <ssh目标> <端口>
#   ./mac-tunnel.sh zheng 8731
#
# 运行后保持这个窗口不关，然后在浏览器打开 http://127.0.0.1:<端口>/
set -euo pipefail
SSH_TARGET="${1:-zheng}"
PORT="${2:-8731}"
URL="http://127.0.0.1:${PORT}/"

echo "SEC Studio 隧道：localhost:${PORT}  ->  ${SSH_TARGET}:127.0.0.1:${PORT}"
echo "启动后请用浏览器打开: ${URL}"
echo "（按 Control-C 关闭隧道）"
echo

# 后台等 2 秒自动打开浏览器（macOS 的 open 命令）
( sleep 2; command -v open >/dev/null && open "$URL" || true ) &

exec ssh -N -o ExitOnForwardFailure=yes -L "${PORT}:127.0.0.1:${PORT}" "$SSH_TARGET"
