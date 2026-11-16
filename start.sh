#!/usr/bin/env bash
# Start the local workbench on macOS/Linux. Windows: start.ps1.
#   ./start.sh --install         first run: create .venv, install deps, build the frontend
#   ./start.sh [--port 8000]     later runs
set -euo pipefail
cd "$(dirname "$0")"
PORT=8000
INSTALL=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --install) INSTALL=1 ;;
    --port) PORT="$2"; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
PY=.venv/bin/python
if [[ ! -x "$PY" ]]; then
  python3 -m venv .venv
  INSTALL=1
fi
if [[ "$INSTALL" == 1 ]]; then
  "$PY" -m pip install --disable-pip-version-check -r requirements.txt
  npm ci --no-audit --no-fund
  npm run build
fi
if [[ ! -f apps/web/dist/index.html ]]; then
  echo "Frontend is not built. Run ./start.sh --install first." >&2
  exit 1
fi
echo "FORM workbench: http://127.0.0.1:$PORT"
exec "$PY" -m uvicorn services.api.app:app --host 127.0.0.1 --port "$PORT"
