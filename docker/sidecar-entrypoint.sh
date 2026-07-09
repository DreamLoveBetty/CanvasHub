#!/bin/sh
set -e

# 等待 server 容器完成 settings.json 初始化
SETTINGS_PATH="${APP_SETTINGS_PATH:-/app/data/settings.json}"
WAIT_MAX=10
i=0
while [ ! -f "$SETTINGS_PATH" ] && [ $i -lt $WAIT_MAX ]; do
  sleep 0.5
  i=$((i + 1))
done

exec "$@"
