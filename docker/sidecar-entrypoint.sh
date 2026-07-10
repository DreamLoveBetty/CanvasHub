#!/bin/sh
set -e

# server 容器的 docker-entrypoint.sh 将 settings.json 写入 /app/data/settings.json
# sidecar 的 config.py 默认读取 /app/settings.json，symlink 使之指向同一份文件
SETTINGS_SRC="${APP_SETTINGS_PATH:-/app/data/settings.json}"
ln -sf "$SETTINGS_SRC" /app/settings.json

WAIT_MAX=10
i=0
while [ ! -f "$SETTINGS_SRC" ] && [ $i -lt $WAIT_MAX ]; do
  sleep 0.5
  i=$((i + 1))
done

exec "$@"
