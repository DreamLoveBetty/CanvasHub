#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${CANVASHUB_PACKAGING_VENV:-$ROOT/.venv-desktop}"
BASE_PYTHON="${CANVASHUB_PACKAGING_PYTHON:-}"

if [ -z "$BASE_PYTHON" ]; then
  if [ -x "$ROOT/.venv/bin/python" ]; then
    BASE_PYTHON="$ROOT/.venv/bin/python"
  elif [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
    BASE_PYTHON="$ROOT/.venv/Scripts/python.exe"
  else
    BASE_PYTHON="python3"
  fi
fi

if [ ! -x "$VENV/bin/python" ] && [ ! -x "$VENV/Scripts/python.exe" ]; then
  "$BASE_PYTHON" -m venv "$VENV"
fi

if [ -x "$VENV/bin/python" ]; then
  VENV_PYTHON="$VENV/bin/python"
elif [ -x "$VENV/Scripts/python.exe" ]; then
  VENV_PYTHON="$VENV/Scripts/python.exe"
else
  echo "Unable to locate the packaging virtual-environment Python executable." >&2
  exit 1
fi

"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r "$ROOT/packaging/requirements-runtime.txt"

cd "$ROOT"
"$VENV_PYTHON" -m PyInstaller \
  --clean \
  --noconfirm \
  --distpath "$ROOT/dist" \
  --workpath "$ROOT/build/pyinstaller" \
  "$ROOT/packaging/pyinstaller/canvashub-runtime.spec"

RUNTIME_EXECUTABLE="$ROOT/dist/canvashub-runtime/canvashub-runtime"
if [ -f "$ROOT/dist/canvashub-runtime/canvashub-runtime.exe" ]; then
  RUNTIME_EXECUTABLE="$ROOT/dist/canvashub-runtime/canvashub-runtime.exe"
fi

"$RUNTIME_EXECUTABLE" doctor \
  --resource-dir "$ROOT" \
  --data-dir "$ROOT/build/runtime-smoke-data"
