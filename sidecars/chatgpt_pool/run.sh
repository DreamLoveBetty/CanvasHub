#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SIDECAR_DIR="$ROOT_DIR/sidecars/chatgpt_pool"
VENV_DIR="${CHATGPT_POOL_VENV:-$SIDECAR_DIR/.venv-runtime}"
HOST="${CHATGPT_POOL_HOST:-127.0.0.1}"

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

resolve_port() {
  if [ -n "${CHATGPT_POOL_PORT:-}" ]; then
    printf '%s\n' "$CHATGPT_POOL_PORT"
    return
  fi
  "$BASE_PYTHON" - "${APP_SETTINGS_PATH:-$ROOT_DIR/settings.json}" <<'PY' 2>/dev/null || echo "18080"
import json, sys
from urllib.parse import urlparse

port = None
try:
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        pool = (json.load(f) or {}).get("chatgpt_pool") or {}
    if isinstance(pool, dict):
        if pool.get("port"):
            port = int(pool["port"])
        elif pool.get("base_url"):
            port = urlparse(str(pool["base_url"])).port
except Exception:
    port = None
print(port if port and 1 <= port <= 65535 else 18080)
PY
}
PORT="$(resolve_port)"
export CHATGPT_POOL_PORT="$PORT"

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
"$VENV_DIR/bin/python" -m pip install -q -r "$SIDECAR_DIR/requirements.txt" -r "$ROOT_DIR/sidecars/google_web/requirements.txt"
"$VENV_DIR/bin/python" - <<'PY'
from backend.app_config import get_chatgpt_pool_config

get_chatgpt_pool_config(ensure_auth_key=True)
PY

exec "$VENV_DIR/bin/python" -m uvicorn sidecars.account_service:app --host "$HOST" --port "$PORT"
