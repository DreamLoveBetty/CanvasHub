#!/bin/bash
# Mini App Watchdog - runs via crontab every 10 minutes
# Single-instance guard + deterministic server startup

set -u

export PATH="${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}:/opt/homebrew/bin:/usr/local/bin"
export GEN_DEDUPE_WINDOW_SECONDS=300  # 5 minutes idempotency window
# 服务进程默认不带全局代理；仅 Telegram 发送时在代码里显式指定 Clash 代理
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy || true
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$DIR/server.py"
SIDECAR_RUN="$DIR/sidecars/chatgpt_pool/run.sh"
PY="${TG_MINI_APP_PYTHON:-}"
if [ -z "$PY" ]; then
    if [ -x "$DIR/.venv/bin/python" ]; then
        PY="$DIR/.venv/bin/python"
    else
        PY="python3"
    fi
fi
LOG="$DIR/watchdog.log"
SERVER_PID_FILE="$DIR/server.pid"
SIDECAR_PID_FILE="$DIR/chatgpt_pool.pid"
SIDECAR_LOG_DIR="$DIR/data/chatgpt_pool"
WATCHDOG_LOCK_DIR="$DIR/.watchdog.lock"
PORT=18463
SIDECAR_PORT="${CHATGPT_POOL_PORT:-18080}"
SERVER_MAX_AGE_SECONDS="${SERVER_MAX_AGE_SECONDS:-0}"
LAUNCHD_LABEL="${LAUNCHD_LABEL:-com.user.tg-mini-app-img-gen.server}"
LAUNCHD_SERVICE="gui/$(id -u)/${LAUNCHD_LABEL}"
SIDECAR_LAUNCHD_LABEL="${SIDECAR_LAUNCHD_LABEL:-com.local.tg-mini-app-img-gen.chatgpt-pool}"
SIDECAR_LAUNCHD_SERVICE="gui/$(id -u)/${SIDECAR_LAUNCHD_LABEL}"

log() { echo "$(date): $1" >> "$LOG"; }

# Watchdog single-run lock (prevents overlapping cron runs)
if ! mkdir "$WATCHDOG_LOCK_DIR" 2>/dev/null; then
    log "watchdog already running; skip"
    exit 0
fi
trap 'rmdir "$WATCHDOG_LOCK_DIR" 2>/dev/null || true' EXIT

is_server_running() {
    # 1) Prefer PID file check
    if [ -f "$SERVER_PID_FILE" ]; then
        local pid
        pid=$(cat "$SERVER_PID_FILE" 2>/dev/null || true)
        if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
            local cmd
            cmd=$(ps -p "$pid" -o command= 2>/dev/null || true)
            if echo "$cmd" | grep -F "$APP" >/dev/null 2>&1; then
                return 0
            fi
        fi
    fi

    # 2) Fallback: process match by absolute app path
    if pgrep -f "$APP" >/dev/null 2>&1; then
        return 0
    fi

    return 1
}

get_server_pid() {
    if [ -f "$SERVER_PID_FILE" ]; then
        local pid
        pid=$(cat "$SERVER_PID_FILE" 2>/dev/null || true)
        if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
            local cmd
            cmd=$(ps -p "$pid" -o command= 2>/dev/null || true)
            if echo "$cmd" | grep -F "$APP" >/dev/null 2>&1; then
                printf '%s\n' "$pid"
                return 0
            fi
        fi
    fi

    pgrep -f "$APP" 2>/dev/null | head -n 1
}

sync_server_pid_file() {
    local pid
    pid=$(get_server_pid 2>/dev/null || true)
    if [ -n "${pid:-}" ]; then
        echo "$pid" > "$SERVER_PID_FILE"
    fi
}

get_server_age_seconds() {
    local pid="$1"
    local elapsed raw days hours minutes seconds
    raw=$(ps -p "$pid" -o etime= 2>/dev/null | tr -d ' ')
    if [ -z "${raw:-}" ]; then
        printf '0\n'
        return
    fi

    days=0
    if echo "$raw" | grep -q -- '-'; then
        days=${raw%%-*}
        raw=${raw#*-}
    fi

    IFS=':' read -r a b c <<EOF
$raw
EOF

    if [ -n "${c:-}" ]; then
        hours=${a:-0}
        minutes=${b:-0}
        seconds=${c:-0}
    else
        hours=0
        minutes=${a:-0}
        seconds=${b:-0}
    fi

    elapsed=$((10#${days:-0} * 86400 + 10#${hours:-0} * 3600 + 10#${minutes:-0} * 60 + 10#${seconds:-0}))
    printf '%s\n' "$elapsed"
}

is_server_healthy() {
    curl --noproxy '*' -fsS --max-time 5 "http://127.0.0.1:${PORT}/" >/dev/null 2>&1
}

is_sidecar_healthy() {
    "$PY" - "$SIDECAR_PORT" <<'PY' >/dev/null 2>&1
import json
import sys
import urllib.request

port = sys.argv[1]
with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as response:
    data = json.loads(response.read().decode("utf-8") or "{}")
capabilities = data.get("capabilities") if isinstance(data, dict) else {}
raise SystemExit(0 if data.get("ok", True) and capabilities.get("search") and capabilities.get("chat_completions") else 1)
PY
}

is_launchd_managed() {
    launchctl print "$LAUNCHD_SERVICE" >/dev/null 2>&1
}

is_sidecar_launchd_managed() {
    launchctl print "$SIDECAR_LAUNCHD_SERVICE" >/dev/null 2>&1
}

get_sidecar_pid() {
    if [ -f "$SIDECAR_PID_FILE" ]; then
        local pid
        pid=$(cat "$SIDECAR_PID_FILE" 2>/dev/null || true)
        if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
            local cmd
            cmd=$(ps -p "$pid" -o command= 2>/dev/null || true)
            if echo "$cmd" | grep -F "sidecars.chatgpt_pool.app:app" >/dev/null 2>&1 || echo "$cmd" | grep -F "$SIDECAR_RUN" >/dev/null 2>&1; then
                printf '%s\n' "$pid"
                return 0
            fi
        fi
    fi

    pgrep -f "sidecars.chatgpt_pool.app:app" 2>/dev/null | head -n 1
}

restart_sidecar() {
    if [ "${CHATGPT_POOL_AUTOSTART:-1}" = "0" ]; then
        log "chatgpt pool sidecar autostart disabled"
        return
    fi

    log "$1"

    if is_sidecar_launchd_managed; then
        launchctl kickstart -k "$SIDECAR_LAUNCHD_SERVICE" >/dev/null 2>&1 || true
        sleep 2
        if is_sidecar_healthy; then
            log "chatgpt pool sidecar restarted via launchd"
        else
            log "chatgpt pool sidecar launchd restart did not become healthy"
        fi
        return
    fi

    local old_pid
    old_pid=$(get_sidecar_pid 2>/dev/null || true)
    if [ -n "${old_pid:-}" ]; then
        kill "$old_pid" 2>/dev/null || true
    fi

    local waited=0
    while [ -n "${old_pid:-}" ] && kill -0 "$old_pid" 2>/dev/null; do
        sleep 1
        waited=$((waited + 1))
        if [ "$waited" -ge 8 ]; then
            kill -9 "$old_pid" 2>/dev/null || true
            break
        fi
    done

    mkdir -p "$SIDECAR_LOG_DIR"
    cd "$DIR"
    nohup "$SIDECAR_RUN" > "$SIDECAR_LOG_DIR/sidecar.watchdog.log" 2>&1 &
    local spid=$!
    echo "$spid" > "$SIDECAR_PID_FILE"
    sleep 2

    if is_sidecar_healthy; then
        log "chatgpt pool sidecar started OK (PID $spid)"
    elif kill -0 "$spid" 2>/dev/null; then
        log "chatgpt pool sidecar process alive but health check not ready yet (PID $spid)"
    else
        log "chatgpt pool sidecar FAILED to start"
    fi
}

restart_server() {
    log "$1"

    if is_launchd_managed; then
        launchctl kickstart -k "$LAUNCHD_SERVICE" >/dev/null 2>&1 || true
        sleep 2
        sync_server_pid_file
        if is_server_healthy; then
            log "server.py restarted via launchd (PID $(cat "$SERVER_PID_FILE" 2>/dev/null || echo unknown))"
        else
            log "server.py launchd restart did not become healthy"
        fi
        return
    fi

    local old_pid
    old_pid=$(get_server_pid 2>/dev/null || true)
    if [ -n "${old_pid:-}" ]; then
        kill "$old_pid" 2>/dev/null || true
    else
        pkill -f "$APP" 2>/dev/null || true
    fi

    local waited=0
    while true; do
        if [ -n "${old_pid:-}" ]; then
            if ! kill -0 "$old_pid" 2>/dev/null; then
                break
            fi
        elif ! pgrep -f "$APP" >/dev/null 2>&1; then
            break
        fi
        sleep 1
        waited=$((waited + 1))
        if [ "$waited" -ge 8 ]; then
            if [ -n "${old_pid:-}" ]; then
                kill -9 "$old_pid" 2>/dev/null || true
            else
                pkill -9 -f "$APP" 2>/dev/null || true
            fi
            break
        fi
    done

    waited=0
    while /usr/sbin/lsof -i TCP:$PORT -sTCP:LISTEN -P >/dev/null 2>&1; do
        sleep 1
        waited=$((waited + 1))
        if [ "$waited" -ge 8 ]; then
            log "port $PORT still busy before restart; forcing one more second of backoff"
            sleep 1
            break
        fi
    done

    cd "$DIR"
    nohup "$PY" -u "$APP" > /tmp/server.log 2>&1 &
    spid=$!
    echo "$spid" > "$SERVER_PID_FILE"
    sleep 2

    if kill -0 "$spid" 2>/dev/null; then
        if /usr/sbin/lsof -i TCP:$PORT -P > /dev/null 2>&1; then
            log "server.py started OK (PID $spid)"
        else
            log "server.py process alive but $PORT not listening yet (PID $spid)"
        fi
    else
        log "server.py FAILED to start"
    fi
}

# 1. ChatGPT account-pool sidecar (port 18080)
if ! is_sidecar_healthy; then
    restart_sidecar "chatgpt pool sidecar unhealthy on http://127.0.0.1:${SIDECAR_PORT}/health; restarting..."
fi

# 2. server.py (port 18463)
if ! is_server_running; then
    restart_server "server.py not running; restarting..."
else
    sync_server_pid_file
    pid=$(get_server_pid)
    age_seconds=$(get_server_age_seconds "$pid")

    if ! is_server_healthy; then
        restart_server "server.py unhealthy on http://127.0.0.1:${PORT}/; restarting..."
    elif [ "${SERVER_MAX_AGE_SECONDS:-0}" -gt 0 ] && [ "${age_seconds:-0}" -ge "${SERVER_MAX_AGE_SECONDS:-0}" ]; then
        restart_server "server.py age ${age_seconds}s exceeded ${SERVER_MAX_AGE_SECONDS}s; rotating..."
    fi
fi

# 3. Public access is handled by the Cloudflare Tunnel launch daemon.
if ! pgrep -f "cloudflared tunnel run" >/dev/null 2>&1; then
    log "cloudflared tunnel process not detected; check Cloudflare service"
fi

# 4. Daily tasks.db cleanup (throttled; process_jobs.py was replaced by server.py threading)
CLEANUP_MARKER="$DIR/.last_task_cleanup"
CLEANUP_INTERVAL_SECONDS=86400
now_epoch=$(date +%s)
last_cleanup=0
if [ -f "$CLEANUP_MARKER" ]; then
    last_cleanup=$(cat "$CLEANUP_MARKER" 2>/dev/null || echo 0)
fi
if ! [[ "$last_cleanup" =~ ^[0-9]+$ ]]; then
    last_cleanup=0
fi

if [ $((now_epoch - last_cleanup)) -ge "$CLEANUP_INTERVAL_SECONDS" ]; then
    if "$PY" -c "from database import cleanup_old_tasks, vacuum_tasks_db; n = cleanup_old_tasks(days=180); vacuum_tasks_db(); print(f'tasks cleanup: deleted {n} rows older than 180 days and vacuumed tasks.db')" >> "$LOG" 2>&1; then
        printf '%s\n' "$now_epoch" > "$CLEANUP_MARKER"
        log "tasks.db cleanup completed"
    else
        log "tasks.db cleanup failed"
    fi
fi

# 5. process_gpt_jobs.py — REMOVED (replaced by server.py SQLite + threading)
