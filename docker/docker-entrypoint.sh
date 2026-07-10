#!/bin/sh
set -e

SETTINGS_PATH="${APP_SETTINGS_PATH:-/app/data/settings.json}"

# Ensure data directory exists
mkdir -p /app/data

# ---- 持久化链接 ----
# 将运行时 DB 和缓存目录通过 symlink 落入 volume，避免容器重建丢失

# 缓存目录
for d in gpt_outputs google_outputs; do
  if [ ! -L "/app/$d" ]; then
    mkdir -p "/app/data/$d"
    ln -sfn "data/$d" "/app/$d"
  fi
done

# SQLite 数据库（assets.db / prompt_sources.db / layout_drafts.db 硬编码 BASE_DIR）
for db in assets.db prompt_sources.db layout_drafts.db; do
  if [ ! -L "/app/$db" ]; then
    if [ -f "/app/$db" ]; then
      mv "/app/$db" "/app/data/$db"
    fi
    touch "/app/data/$db"
    ln -sf "data/$db" "/app/$db"
  fi
done

# ---- settings.json ----
if [ ! -f "$SETTINGS_PATH" ]; then
	cp /app/settings.docker.json "$SETTINGS_PATH"
	echo "[entrypoint] Created settings.json from Docker template"
fi

# Ensure chatgpt_pool.auth_key exists
python3 -c "
import json, os, secrets
path = os.environ.get('APP_SETTINGS_PATH', '/app/data/settings.json')
with open(path) as f:
    s = json.load(f)
pool = s.setdefault('chatgpt_pool', {})
if not pool.get('auth_key'):
    pool['auth_key'] = 'sk-docker-' + secrets.token_urlsafe(24)
    with open(path, 'w') as f:
        json.dump(s, f, indent=2, ensure_ascii=False)
    print('[entrypoint] Auto-generated chatgpt_pool.auth_key')
"

# sidecar 读的是 /app/settings.json → symlink 到 volume
ln -sf "$SETTINGS_PATH" /app/settings.json

exec "$@"
