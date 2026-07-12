#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${CANVASHUB_UPSCALE_BUILD_VENV:-$ROOT/.venv-upscale-component}"
BASE_PYTHON="${CANVASHUB_PACKAGING_PYTHON:-}"
VERSION="${CANVASHUB_UPSCALE_VERSION:-1.0.0}"
BASE_URL="${CANVASHUB_UPSCALE_BASE_URL:-}"

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
  echo "Unable to locate the upscale build virtual-environment Python executable." >&2
  exit 1
fi

"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r "$ROOT/requirements-upscale.txt" "pyinstaller>=6.16,<7"

PLATFORM_KEY=$("$VENV_PYTHON" - <<'PY'
import platform
system = {"Darwin": "darwin", "Windows": "windows", "Linux": "linux"}.get(platform.system(), platform.system().lower())
machine = platform.machine().lower()
arch = "arm64" if machine in {"arm64", "aarch64"} else "x64" if machine in {"x86_64", "amd64"} else machine
print(f"{system}-{arch}")
PY
)

cd "$ROOT"
"$VENV_PYTHON" -m PyInstaller \
  --clean \
  --noconfirm \
  --distpath "$ROOT/build/upscale-worker-dist" \
  --workpath "$ROOT/build/upscale-worker-work" \
  "$ROOT/packaging/upscale/upscale-worker.spec"

"$VENV_PYTHON" "$ROOT/packaging/upscale/build_component.py" \
  --project-root "$ROOT" \
  --worker-dir "$ROOT/build/upscale-worker-dist/upscale-worker" \
  --output-dir "$ROOT/build/upscale-component-release" \
  --version "$VERSION" \
  --platform "$PLATFORM_KEY" \
  --base-url "$BASE_URL"
