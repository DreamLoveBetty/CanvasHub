#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SIDECAR_DIR="$ROOT_DIR/sidecars/chatgpt_pool"
VENV_DIR="${CHATGPT_POOL_VENV:-$SIDECAR_DIR/.venv-runtime}"
HOST="${CHATGPT_POOL_HOST:-127.0.0.1}"
PORT="${CHATGPT_POOL_PORT:-18080}"

cd "$ROOT_DIR"
export PATH="${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}:/opt/homebrew/bin:/usr/local/bin"

BASE_PYTHON="${CHATGPT_POOL_PYTHON:-}"
if [ -z "$BASE_PYTHON" ]; then
  if [ -x "/opt/homebrew/bin/python3" ]; then
    BASE_PYTHON="/opt/homebrew/bin/python3"
  elif [ -x "/usr/local/bin/python3" ]; then
    BASE_PYTHON="/usr/local/bin/python3"
  else
    BASE_PYTHON="$(command -v python3)"
  fi
fi

ensure_venv() {
  local rebuild=0

  if [ ! -x "$VENV_DIR/bin/python" ]; then
    rebuild=1
  elif ! "$VENV_DIR/bin/python" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
  then
    rebuild=1
  elif ! "$VENV_DIR/bin/python" - <<'PY' >/dev/null 2>&1
import pip._vendor.requests.exceptions  # noqa: F401
PY
  then
    rebuild=1
  fi

  if [ "$rebuild" -eq 1 ]; then
    "$BASE_PYTHON" -m venv --clear "$VENV_DIR"
  fi
}

ensure_venv

"$VENV_DIR/bin/python" -m pip install -q --upgrade pip
"$VENV_DIR/bin/python" -m pip install -q -r "$SIDECAR_DIR/requirements.txt"
"$VENV_DIR/bin/python" - <<'PY'
from backend.app_config import get_chatgpt_pool_config

get_chatgpt_pool_config(ensure_auth_key=True)
PY

exec "$VENV_DIR/bin/python" -m uvicorn sidecars.chatgpt_pool.app:app --host "$HOST" --port "$PORT"
