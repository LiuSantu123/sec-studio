#!/usr/bin/env bash
# Launch SEC Studio.
#   ./run.sh [data-folder] [port] [extra app.py flags...]
# Examples:
#   ./run.sh
#   ./run.sh /data/somewhere/zips 9000
#   ./run.sh "" 8731 --no-browser
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${1:-$(dirname "$HERE")}"      # default: the folder that holds the *.zip files
PORT="${2:-${PORT:-8731}}"
[ "$#" -ge 1 ] && shift
[ "$#" -ge 1 ] && shift
exec python3 "$HERE/app.py" --data-dir "$DATA" --port "$PORT" "$@"
