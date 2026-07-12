#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACTION="${1:-}"
shift || true
BUILD=1
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: ./packaging/release-version.sh <patch|minor|major|X.Y.Z> [--no-build] [--dry-run]

  patch      26.0.1 -> 26.0.2
  minor      26.0.1 -> 26.1.0
  major      26.0.1 -> 27.0.0
  X.Y.Z      Set an explicit version

The command synchronizes all application version declarations and builds the
desktop release by default. A failed build restores the previous versions.
EOF
}

if [ -z "$ACTION" ] || [ "$ACTION" = "-h" ] || [ "$ACTION" = "--help" ]; then
  usage
  [ -n "$ACTION" ] && exit 0 || exit 2
fi

for option in "$@"; do
  case "$option" in
    --no-build) BUILD=0 ;;
    --dry-run) DRY_RUN=1 ;;
    *) echo "Unknown option: $option" >&2; usage >&2; exit 2 ;;
  esac
done

CURRENT="$(node "$ROOT/packaging/version-tool.mjs" current)"
case "$ACTION" in
  patch|minor|major)
    TARGET="$(node "$ROOT/packaging/version-tool.mjs" next "$ACTION")"
    ;;
  *)
    if [[ "$ACTION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      TARGET="$ACTION"
    else
      echo "Invalid release level or version: $ACTION" >&2
      usage >&2
      exit 2
    fi
    ;;
esac

if [ "$TARGET" = "$CURRENT" ]; then
  echo "Version is already $CURRENT; nothing to release." >&2
  exit 2
fi

echo "CanvasHub release: $CURRENT -> $TARGET"
if [ "$DRY_RUN" = "1" ]; then
  echo "Dry run only; no files changed."
  exit 0
fi

TARGET_FILES=(
  "backend/version.py"
  "desktop/electron/package.json"
  "desktop/electron/package-lock.json"
  "desktop/electron/src/main.ts"
  "frontend/desktop.html"
)
BACKUP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/canvashub-version.XXXXXX")"
for relative in "${TARGET_FILES[@]}"; do
  mkdir -p "$BACKUP_DIR/$(dirname "$relative")"
  cp "$ROOT/$relative" "$BACKUP_DIR/$relative"
done

restore_versions() {
  echo "Release failed; restoring version files to $CURRENT." >&2
  for relative in "${TARGET_FILES[@]}"; do
    cp "$BACKUP_DIR/$relative" "$ROOT/$relative"
  done
  rm -rf "$BACKUP_DIR"
}
on_error() {
  local status=$?
  trap - ERR INT TERM
  restore_versions
  exit "$status"
}
on_interrupt() {
  trap - ERR INT TERM
  restore_versions
  exit 130
}
trap on_error ERR
trap on_interrupt INT TERM

node "$ROOT/packaging/version-tool.mjs" set "$TARGET" >/dev/null
node "$ROOT/packaging/version-tool.mjs" check "$TARGET" >/dev/null
echo "Version declarations synchronized."

if [ "$BUILD" = "1" ]; then
  export CANVASHUB_UPDATE_URL="${CANVASHUB_UPDATE_URL:-https://github.com/DreamLoveBetty/CanvasHub/releases/latest/download}"
  export CANVASHUB_UPSCALE_MANIFEST_URL="${CANVASHUB_UPSCALE_MANIFEST_URL:-${CANVASHUB_UPDATE_URL%/}/upscale-manifest.json}"
  "$ROOT/packaging/build-desktop.sh"
else
  echo "Build skipped (--no-build)."
fi

trap - ERR INT TERM
rm -rf "$BACKUP_DIR"
echo "CanvasHub $TARGET release completed."
