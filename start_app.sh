#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_HEALTH_URL="http://localhost:8000/api/health"

wait_for_backend() {
  local attempts=30
  local sleep_secs=1

  echo "Waiting for backend health endpoint..."
  for ((i=1; i<=attempts; i++)); do
    if curl -fsS "$BACKEND_HEALTH_URL" >/dev/null 2>&1; then
      echo "Backend is healthy."
      return 0
    fi
    sleep "$sleep_secs"
  done

  echo "Backend did not become healthy in time: $BACKEND_HEALTH_URL"
  echo "Check logs: $ROOT_DIR/.logs/backend.log"
  return 1
}

echo "Starting DynamicAnalyzer services..."
"$ROOT_DIR/start_backend.sh"
wait_for_backend
"$ROOT_DIR/start_frontend.sh"

echo
echo "All services started."
echo "Frontend: http://localhost:5173"
echo "Backend:  http://localhost:8000"
echo "Backend health: http://localhost:8000/api/health"
echo
echo "Tail logs:"
echo "  tail -f \"$ROOT_DIR/.logs/backend.log\""
echo "  tail -f \"$ROOT_DIR/.logs/frontend.log\""
