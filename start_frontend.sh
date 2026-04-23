#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
PORT=5173
LOG_DIR="$ROOT_DIR/.logs"
LOG_FILE="$LOG_DIR/frontend.log"

kill_port() {
  local port="$1"
  local pids
  pids="$(lsof -ti tcp:"$port" || true)"
  if [[ -n "$pids" ]]; then
    echo "Killing process(es) on port $port: $pids"
    kill -9 $pids || true
  fi
}

mkdir -p "$LOG_DIR"

if [[ ! -d "$FRONTEND_DIR" ]]; then
  echo "Frontend directory not found: $FRONTEND_DIR"
  exit 1
fi

kill_port "$PORT"

echo "Starting frontend on port $PORT..."
(
  cd "$FRONTEND_DIR"
  npm run dev -- --host 0.0.0.0 --port "$PORT"
) >"$LOG_FILE" 2>&1 &

echo $! > "$ROOT_DIR/.frontend.pid"
echo "Frontend started. PID: $(cat "$ROOT_DIR/.frontend.pid")"
echo "Logs: $LOG_FILE"
echo "URL: http://localhost:$PORT"
