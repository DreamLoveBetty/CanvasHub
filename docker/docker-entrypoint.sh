#!/bin/sh
set -e

# Create settings.json from Docker template if missing
if [ ! -f "settings.json" ]; then
	cp settings.docker.json settings.json
	echo "[entrypoint] Created settings.json from Docker template"
fi

# Ensure chatgpt_pool.auth_key exists (env var override in docker-compose.yml takes priority at runtime)
python3 -c "
import json, os, secrets
with open('settings.json') as f:
    s = json.load(f)
pool = s.setdefault('chatgpt_pool', {})
if not pool.get('auth_key'):
    pool['auth_key'] = 'sk-docker-' + secrets.token_urlsafe(24)
    with open('settings.json', 'w') as f:
        json.dump(s, f, indent=2, ensure_ascii=False)
    print('[entrypoint] Auto-generated chatgpt_pool.auth_key')
"

exec "$@"
