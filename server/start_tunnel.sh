#!/bin/bash
# Start Cloudflare quick tunnel for labsch-manager server.
# This makes the local server (port 8080) accessible via a public
# HTTPS URL like https://<random>.trycloudflare.com

set -e

CLOUDFLARED="/root/.9router/bin/cloudflared"  # reuse existing binary

if [ ! -x "$CLOUDFLARED" ]; then
    echo "cloudflared not found at $CLOUDFLARED"
    # fallback to system PATH
    CLOUDFLARED=$(which cloudflared 2>/dev/null || echo "")
    if [ -z "$CLOUDFLARED" ]; then
        echo "Install cloudflared first: pacman -S github-cli cloudflared"
        exit 1
    fi
fi

LOG_FILE="/tmp/cloudflared-labsch.log"
PID_FILE="/tmp/cloudflared-labsch.pid"

# Kill any existing
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping existing tunnel (PID $OLD_PID)..."
        kill "$OLD_PID" || true
        sleep 2
    fi
    rm -f "$PID_FILE"
fi

echo "Starting Cloudflare quick tunnel for http://localhost:8080 ..."
echo "Logs: $LOG_FILE"
echo ""

# Run in background. Capture URL from log.
nohup "$CLOUDFLARED" tunnel --url http://localhost:8080 --no-autoupdate \
    > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
TUNNEL_PID=$(cat "$PID_FILE")
echo "Tunnel started (PID $TUNNEL_PID)"

# Wait for URL to appear
echo "Waiting for tunnel URL..."
for i in {1..30}; do
    if grep -qE "https://[a-z0-9-]+\.trycloudflare\.com" "$LOG_FILE" 2>/dev/null; then
        break
    fi
    sleep 1
done

URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$LOG_FILE" | head -1)

if [ -n "$URL" ]; then
    echo ""
    echo "════════════════════════════════════════════"
    echo "  Tunnel URL: $URL"
    echo "════════════════════════════════════════════"
    echo ""
    echo "Save this URL — it goes into client config:"
    echo "  [server]"
    echo "  url = $URL"
    echo ""
    echo "Test from local:"
    echo "  curl $URL/api/health"
    echo ""
    echo "Note: Quick tunnel URL is RANDOM — changes on every restart."
    echo "For stable URL, set up a named tunnel with your own domain."
else
    echo "Failed to get tunnel URL. Check log:"
    tail -30 "$LOG_FILE"
    exit 1
fi
