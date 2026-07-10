#!/bin/sh
set -e

# sidecar 的 config.py 默认读 /app/settings.json，server 已写入 /app/data/settings.json
# 此处确保 symlink 存在（无论 server entrypoint 是否已运行）
SETTINGS_SRC="${APP_SETTINGS_PATH:-/app/data/settings.json}"
ln -sf "$SETTINGS_SRC" /app/settings.json

# 等待 settings.json 就绪，超时则退出让 Docker 重启
WAIT_MAX=10
i=0
while [ ! -f "$SETTINGS_SRC" ] && [ $i -lt $WAIT_MAX ]; do
  sleep 0.5
  i=$((i + 1))
done

if [ ! -f "$SETTINGS_SRC" ]; then
  echo "[sidecar] ERROR: settings.json not found after ${WAIT_MAX}s, exiting"
  exit 1
fi

exec "$@"
