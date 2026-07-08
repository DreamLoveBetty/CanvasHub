#!/usr/bin/env bash
# Start the Mini App server. Public access is handled by Cloudflare Tunnel.
set -e

PORT=18463
SIDECAR_PORT="${CHATGPT_POOL_PORT:-18080}"
PUBLIC_URL="${MINIAPP_PUBLIC_URL:-}"
DIR="$(cd "$(dirname "$0")" && pwd)"
SIDECAR_RUN="$DIR/sidecars/chatgpt_pool/run.sh"
SIDECAR_LOG_DIR="$DIR/data/chatgpt_pool"
SIDECAR_PID=""
SIDECAR_STARTED=0
PYTHON_BIN="${TG_MINI_APP_PYTHON:-}"
SIDECAR_LAUNCHD_LABEL="${SIDECAR_LAUNCHD_LABEL:-com.local.tg-mini-app-img-gen.chatgpt-pool}"
SIDECAR_LAUNCHD_SERVICE="gui/$(id -u)/${SIDECAR_LAUNCHD_LABEL}"

export PATH="${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}:/opt/homebrew/bin:/usr/local/bin"

if [ -z "$PYTHON_BIN" ]; then
    if [ -x "$DIR/.venv/bin/python" ]; then
        PYTHON_BIN="$DIR/.venv/bin/python"
    else
        PYTHON_BIN="python3"
    fi
fi

is_sidecar_healthy() {
    "$PYTHON_BIN" - "$SIDECAR_PORT" <<'PY' >/dev/null 2>&1
import json
import sys
import urllib.request

port = sys.argv[1]
with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
    data = json.loads(response.read().decode("utf-8") or "{}")
capabilities = data.get("capabilities") if isinstance(data, dict) else {}
raise SystemExit(0 if data.get("ok", True) and capabilities.get("search") and capabilities.get("chat_completions") else 1)
PY
}

is_sidecar_port_listening() {
    /usr/sbin/lsof -i TCP:"$SIDECAR_PORT" -sTCP:LISTEN -P >/dev/null 2>&1
}

is_sidecar_launchd_managed() {
    launchctl print "$SIDECAR_LAUNCHD_SERVICE" >/dev/null 2>&1
}

restart_existing_sidecar() {
    if ! is_sidecar_port_listening; then
        return
    fi

    if is_sidecar_launchd_managed; then
        echo "🔁  Existing ChatGPT account-pool sidecar is stale; restarting launchd service..."
        launchctl kickstart -k "$SIDECAR_LAUNCHD_SERVICE" >/dev/null 2>&1 || true
    else
        old_pid=$(/usr/sbin/lsof -ti TCP:"$SIDECAR_PORT" -sTCP:LISTEN 2>/dev/null | head -n 1)
        if [ -n "${old_pid:-}" ]; then
            old_cmd=$(ps -p "$old_pid" -o command= 2>/dev/null || true)
            if echo "$old_cmd" | grep -F "sidecars.chatgpt_pool.app:app" >/dev/null 2>&1; then
                echo "🔁  Existing ChatGPT account-pool sidecar is stale; restarting PID $old_pid..."
                kill "$old_pid" 2>/dev/null || true
            fi
        fi
    fi

    for _ in $(seq 1 12); do
        if is_sidecar_healthy; then
            return
        fi
        if ! is_sidecar_port_listening; then
            return
        fi
        sleep 1
    done
}

start_sidecar() {
    if [ "${CHATGPT_POOL_AUTOSTART:-1}" = "0" ]; then
        echo "⏭️  ChatGPT account-pool sidecar autostart disabled."
        return
    fi

    if is_sidecar_healthy; then
        echo "✅ ChatGPT account-pool sidecar is already online on port $SIDECAR_PORT."
        return
    fi

    restart_existing_sidecar
    if is_sidecar_healthy; then
        echo "✅ ChatGPT account-pool sidecar is online on port $SIDECAR_PORT."
        return
    fi

    if [ ! -x "$SIDECAR_RUN" ]; then
        echo "⚠️  ChatGPT account-pool sidecar launcher missing: $SIDECAR_RUN"
        return
    fi

    mkdir -p "$SIDECAR_LOG_DIR"
    echo "🔧  Starting ChatGPT account-pool sidecar on port $SIDECAR_PORT ..."
    "$SIDECAR_RUN" > "$SIDECAR_LOG_DIR/sidecar.start.log" 2>&1 &
    SIDECAR_PID=$!
    SIDECAR_STARTED=1

    for _ in $(seq 1 30); do
        if is_sidecar_healthy; then
            echo "✅ ChatGPT account-pool sidecar is online."
            return
        fi
        if ! kill -0 "$SIDECAR_PID" 2>/dev/null; then
            echo "⚠️  ChatGPT account-pool sidecar exited early; see $SIDECAR_LOG_DIR/sidecar.start.log"
            SIDECAR_PID=""
            SIDECAR_STARTED=0
            return
        fi
        sleep 1
    done

    echo "⚠️  ChatGPT account-pool sidecar did not become healthy; GPT image tasks may be limited."
}

start_sidecar

echo "🔧  Starting Python server on port $PORT ..."
"$PYTHON_BIN" "$DIR/server.py" &
SERVER_PID=$!
sleep 1

# Legacy job workers removed — server.py handles all tasks via SQLite + threads

echo ""
echo "═══════════════════════════════════════════════"
echo "  ✅  Mini App is LIVE"
echo ""
echo "  Local:   http://localhost:$PORT"
echo "  Sidecar: http://127.0.0.1:$SIDECAR_PORT"
if [ -n "$PUBLIC_URL" ]; then
    echo "  Public:  $PUBLIC_URL"
    echo ""
    echo "  👉 Go to @BotFather → /newapp (or /editapp)"
    echo "     Set Web App URL to:"
    echo "     $PUBLIC_URL"
else
    echo "  Public:  set MINIAPP_PUBLIC_URL when exposing the app"
fi
echo "═══════════════════════════════════════════════"
echo ""
echo "  Press Ctrl+C to stop everything."
echo ""

cleanup() {
    kill $SERVER_PID 2>/dev/null || true
    if [ "$SIDECAR_STARTED" = "1" ] && [ -n "${SIDECAR_PID:-}" ]; then
        kill "$SIDECAR_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM
wait "$SERVER_PID"
