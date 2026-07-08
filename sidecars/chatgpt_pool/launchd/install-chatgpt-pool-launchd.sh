#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
LABEL="com.local.tg-mini-app-img-gen.chatgpt-pool"
TEMPLATE="$SCRIPT_DIR/${LABEL}.plist.template"
LOCAL_PLIST="$SCRIPT_DIR/${LABEL}.plist"
TARGET_DIR="$HOME/Library/LaunchAgents"
TARGET_PLIST="$TARGET_DIR/${LABEL}.plist"

if [ ! -f "$TEMPLATE" ]; then
  echo "Missing template: $TEMPLATE" >&2
  exit 1
fi

mkdir -p "$PROJECT_DIR/data/chatgpt_pool" "$TARGET_DIR"

python3 - "$TEMPLATE" "$LOCAL_PLIST" "$PROJECT_DIR" <<'PY'
from pathlib import Path
import sys

template = Path(sys.argv[1])
target = Path(sys.argv[2])
project_dir = sys.argv[3]

target.write_text(
    template.read_text(encoding="utf-8").replace("__PROJECT_DIR__", project_dir),
    encoding="utf-8",
)
PY

cp "$LOCAL_PLIST" "$TARGET_PLIST"

launchctl bootout "gui/$(id -u)" "$TARGET_PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$TARGET_PLIST"
launchctl kickstart -k "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true

echo "Installed $LABEL"
echo "Project: $PROJECT_DIR"
echo "Plist:   $TARGET_PLIST"
