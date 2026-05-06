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

# Pydantic (and many deps) ship wheels up to 3.13. On 3.14 pip may try to build
# pydantic-core from source (Rust + network); prefer 3.12/3.13/3.11 instead.
choose_python() {
  local cand
  for cand in python3.12 python3.13 python3.11 python3.10; do
    if command -v "$cand" >/dev/null 2>&1; then
      echo "$cand"
      return
    fi
  done
  if command -v python3 >/dev/null 2>&1; then
    local major minor
    major=$(python3 -c 'import sys; print(sys.version_info.major)')
    minor=$(python3 -c 'import sys; print(sys.version_info.minor)')
    if [[ "$major" -eq 3 ]] && [[ "$minor" -lt 14 ]]; then
      echo "python3"
      return
    fi
  fi
  echo ""
}

venv_python_too_new() {
  [[ -x "$VENV_DIR/bin/python" ]] || return 1
  if ! "$VENV_DIR/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info < (3, 14) else 1)'; then
    return 0
  fi
  return 1
}

mkdir -p "$LOG_DIR"

if [[ ! -d "$BACKEND_DIR" ]]; then
  echo "Backend directory not found: $BACKEND_DIR"
  exit 1
fi

kill_port "$PORT"

if venv_python_too_new; then
  echo "Removing backend/.venv: Python 3.14+ often has no binary wheels for pydantic-core (install fails without Rust)."
  echo "Install a supported runtime, e.g.: brew install python@3.12"
  rm -rf "$VENV_DIR"
fi

if [[ ! -d "$VENV_DIR" ]]; then
  PYTHON_BIN="$(choose_python)"
  if [[ -z "$PYTHON_BIN" ]]; then
    echo "No supported Python found (need 3.10–3.13). If \`python3\` is 3.14, install:"
    echo "  brew install python@3.12"
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
)

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
