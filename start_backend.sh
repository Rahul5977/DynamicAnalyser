#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
PORT=8000
LOG_DIR="$ROOT_DIR/.logs"
LOG_FILE="$LOG_DIR/backend.log"
VENV_DIR="$BACKEND_DIR/.venv"

kill_port() {
  local port="$1"
  local pids
  pids="$(lsof -ti tcp:"$port" || true)"
  if [[ -n "$pids" ]]; then
    echo "Killing process(es) on port $port: $pids"
    kill -9 $pids || true
  fi
}

choose_python() {
  if command -v python3.12 >/dev/null 2>&1; then
    echo "python3.12"
  elif command -v python3 >/dev/null 2>&1; then
    echo "python3"
  else
    echo ""
  fi
}

mkdir -p "$LOG_DIR"

if [[ ! -d "$BACKEND_DIR" ]]; then
  echo "Backend directory not found: $BACKEND_DIR"
  exit 1
fi

kill_port "$PORT"

if [[ ! -d "$VENV_DIR" ]]; then
  PYTHON_BIN="$(choose_python)"
  if [[ -z "$PYTHON_BIN" ]]; then
    echo "No Python 3 executable found (python3.12/python3)."
    exit 1
  fi

  echo "Creating backend virtualenv with $PYTHON_BIN..."
  (
    cd "$BACKEND_DIR"
    "$PYTHON_BIN" -m venv .venv
  )
fi

echo "Ensuring backend dependencies are installed..."
(
  cd "$BACKEND_DIR"
  source .venv/bin/activate
  pip install -r requirements.txt python-multipart
) >/dev/null

echo "Starting backend on port $PORT..."
(
  cd "$BACKEND_DIR"
  source .venv/bin/activate
  python -m uvicorn app.main:app --reload --host 0.0.0.0 --port "$PORT"
) >"$LOG_FILE" 2>&1 &

echo $! > "$ROOT_DIR/.backend.pid"
echo "Backend started. PID: $(cat "$ROOT_DIR/.backend.pid")"
echo "Logs: $LOG_FILE"
echo "URL: http://localhost:$PORT"
