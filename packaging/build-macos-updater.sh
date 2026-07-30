#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/packaging/macos-updater/CanvasHubUpdater.m"
OUTPUT="$ROOT/dist/canvashub-updater"
ARCH="${CANVASHUB_DESKTOP_ARCH:-$(uname -m)}"

case "$ARCH" in
  arm64|x86_64) ;;
  *) echo "Unsupported macOS updater architecture: $ARCH" >&2; exit 1 ;;
esac

mkdir -p "$(dirname "$OUTPUT")"
xcrun clang \
  -fobjc-arc \
  -fmodules \
  -fmodules-cache-path="$ROOT/build/clang-module-cache" \
  -O2 \
  -arch "$ARCH" \
  -mmacosx-version-min=12.0 \
  -Wno-deprecated-declarations \
  "$SOURCE" \
  -framework Foundation \
  -o "$OUTPUT"
codesign --force --sign - "$OUTPUT"
"$OUTPUT" --version
