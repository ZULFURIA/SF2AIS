#!/bin/bash
# SF2AIS server startup helper (macOS / Linux).
#
# Starts the SF2AIS gateway server (uvicorn) in the background and prints the
# dashboard URL. Idempotent: re-running won't spawn duplicate servers.
#
# Usage:
#   ./start.sh            # start on default port 8000
#   PORT=9000 ./start.sh  # custom port

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-8000}"
PID_FILE="$REPO_ROOT/.sf2ais-server.pid"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "SF2AIS server already running (PID $(cat "$PID_FILE"))."
else
  if [[ ! -f "$REPO_ROOT/main.py" ]]; then
    echo "Error: main.py not found in $REPO_ROOT. Run this from the SF2AIS repo root." >&2
    exit 1
  fi

  PYTHON="python3"
  VENV_PY="$REPO_ROOT/venv/bin/python"
  [[ -x "$VENV_PY" ]] && PYTHON="$VENV_PY"

  nohup "$PYTHON" -m uvicorn main:app --host 0.0.0.0 --port "$PORT" \
    > "$REPO_ROOT/sf2ais.log" 2>&1 &
  echo $! > "$PID_FILE"
  echo "SF2AIS server starting (PID $(cat "$PID_FILE")) on port $PORT..."
  sleep 2
fi

echo "Open http://localhost:$PORT/dashboard to configure."
