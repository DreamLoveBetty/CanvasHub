#!/bin/sh
set -e

SETTINGS_PATH="${APP_SETTINGS_PATH:-/app/data/settings.json}"

# Ensure data directory exists
mkdir -p /app/data

# Symlink cache dirs into volume so they survive container rebuilds
for d in gpt_outputs google_outputs; do
  if [ ! -L "/app/$d" ]; then
    mkdir -p "/app/data/$d"
    ln -sfn "data/$d" "/app/$d"
  fi
done

# Create settings.json from Docker template if missing
if [ ! -f "$SETTINGS_PATH" ]; then
	cp /app/settings.docker.json "$SETTINGS_PATH"
	echo "[entrypoint] Created settings.json from Docker template"
fi

# Ensure chatgpt_pool.auth_key exists (env var overrides at runtime)
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

exec "$@"
