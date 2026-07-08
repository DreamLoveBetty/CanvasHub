#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LABEL="${TG_MINI_APP_LAUNCHD_LABEL:-com.user.tg-mini-app-img-gen.server}"
TEMPLATE="$SCRIPT_DIR/com.user.tg-mini-app-img-gen.server.plist.template"
LOCAL_PLIST="$SCRIPT_DIR/${LABEL}.plist"
TARGET_DIR="$HOME/Library/LaunchAgents"
TARGET_PLIST="$TARGET_DIR/${LABEL}.plist"
PYTHON_BIN="${TG_MINI_APP_PYTHON:-}"

if [ ! -f "$TEMPLATE" ]; then
  echo "Missing template: $TEMPLATE" >&2
  exit 1
fi

if [ -z "$PYTHON_BIN" ]; then
  if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi

mkdir -p "$TARGET_DIR"

python3 - "$TEMPLATE" "$LOCAL_PLIST" "$PROJECT_DIR" "$PYTHON_BIN" "$LABEL" <<'PY'
from pathlib import Path
import sys

template = Path(sys.argv[1])
target = Path(sys.argv[2])
project_dir = sys.argv[3]
python_bin = sys.argv[4]
label = sys.argv[5]

text = template.read_text(encoding="utf-8")
text = text.replace("com.user.tg-mini-app-img-gen.server", label)
text = text.replace("__PROJECT_DIR__", project_dir)
text = text.replace("__PYTHON_BIN__", python_bin)
target.write_text(text, encoding="utf-8")
PY

cp "$LOCAL_PLIST" "$TARGET_PLIST"

launchctl bootout "gui/$(id -u)" "$TARGET_PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$TARGET_PLIST"
launchctl kickstart -k "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true

echo "Installed $LABEL"
echo "Project: $PROJECT_DIR"
echo "Python:  $PYTHON_BIN"
echo "Plist:   $TARGET_PLIST"
