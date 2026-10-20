#!/usr/bin/env bash
# Run SEC Studio as a background service on the cluster (survives closing the SSH session).
#
#   ./serve.sh start [data-folder] [port]     # 后台启动
#   ./serve.sh stop                           # 停止
#   ./serve.sh status                         # 查看状态
#   ./serve.sh restart                        # 重启
#   ./serve.sh log                            # 跟踪日志
#
# 默认：data-folder = 上一层目录(放 zip 的文件夹)，port = 8731，绑定 127.0.0.1（配 SSH 隧道用）。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DEFAULT="$(dirname "$HERE")"
RUNDIR="$HERE/.run"
PIDFILE="$RUNDIR/sec_studio.pid"
PORTFILE="$RUNDIR/sec_studio.port"
LOGFILE="$RUNDIR/sec_studio.log"
mkdir -p "$RUNDIR"

cmd="${1:-start}"
case "$cmd" in
  start)
    shift || true
    DATA="${1:-$DATA_DEFAULT}"; PORT="${2:-${PORT:-8731}}"; HOST="${HOST:-127.0.0.1}"
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "already running (pid $(cat "$PIDFILE")); use ./serve.sh restart"; exit 0
    fi
    cd "$HERE"
    if command -v setsid >/dev/null 2>&1; then
      setsid python3 app.py --data-dir "$DATA" --port "$PORT" --host "$HOST" --no-browser \
          >"$LOGFILE" 2>&1 </dev/null &
    else
      nohup python3 app.py --data-dir "$DATA" --port "$PORT" --host "$HOST" --no-browser \
          >"$LOGFILE" 2>&1 </dev/null &
    fi
    echo $! > "$PIDFILE"
    echo "$PORT" > "$PORTFILE"
    sleep 1.5
    if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "SEC Studio started (pid $(cat "$PIDFILE"))"
      echo "  cluster : http://127.0.0.1:$PORT/"
      echo "  Mac     : ssh -N -L $PORT:127.0.0.1:$PORT zheng  然后打开 http://127.0.0.1:$PORT/"
      echo "  log     : $LOGFILE"
    else
      echo "failed to start; see $LOGFILE"; tail -n 20 "$LOGFILE" || true; exit 1
    fi
    ;;
  stop)
    if [ -f "$PIDFILE" ]; then
      pid="$(cat "$PIDFILE")"
      if kill -0 "$pid" 2>/dev/null; then kill "$pid"; sleep 1; kill -9 "$pid" 2>/dev/null || true; fi
      rm -f "$PIDFILE" "$PORTFILE"; echo "stopped"
    else
      echo "not running (no pidfile)"
    fi
    ;;
  restart)
    "$0" stop || true; shift || true; "$HERE/serve.sh" start "$@"
    ;;
  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "running (pid $(cat "$PIDFILE"))"
      port="$(cat "$PORTFILE" 2>/dev/null || echo 8731)"
      echo "  cluster : http://127.0.0.1:${port}/"
      echo "  Mac     : ssh -N -L ${port}:127.0.0.1:${port} zheng"
      ss -lntp 2>/dev/null | grep -E ":${port}\b" || echo "  (not listening yet?)"
    else
      echo "not running"
    fi
    exit 0
    ;;
  log) tail -n 60 -f "$LOGFILE" ;;
  *) echo "usage: $0 {start|stop|restart|status|log} [data-folder] [port]"; exit 2 ;;
esac
