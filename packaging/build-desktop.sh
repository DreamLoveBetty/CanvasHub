#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_MODE="${CANVASHUB_DESKTOP_BUILD_MODE:-release}"

"$ROOT/packaging/build-python-runtime.sh"

cd "$ROOT/desktop/electron"
if [ -f package-lock.json ]; then
  npm ci
else
  npm install
fi

if [ "$BUILD_MODE" = "pack" ]; then
  npm run pack
  exit 0
fi

case "$(uname -s)" in
  Darwin)
    npm run dist:mac
    ;;
  MINGW*|MSYS*|CYGWIN*)
    npm run dist:win
    ;;
  *)
    echo "Unsupported release platform: $(uname -s). Use CANVASHUB_DESKTOP_BUILD_MODE=pack for an unpacked build." >&2
    exit 1
    ;;
esac
