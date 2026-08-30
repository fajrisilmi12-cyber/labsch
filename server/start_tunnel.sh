#!/bin/bash
# Start Cloudflare quick tunnel for LabSCH server.
# Exposes local FastAPI server (port 8080) via a public HTTPS URL
# like https://<random>.trycloudflare.com
#
# For a stable URL across restarts, set up a named tunnel:
#   cloudflared tunnel login
#   cloudflared tunnel create labsch-server
#   cloudflared tunnel route dns labsch-server labsch.yourdomain.com
#   cloudflared tunnel run labsch-server
#
# Install cloudflared (one-time, Debian/Ubuntu):
#   curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb
#   sudo dpkg -i /tmp/cloudflared.deb
# Other platforms: https://pkg.cloudflare.com/

set -e

# Locate cloudflared: prefer system PATH, fallback to common locations
CLOUDFLARED=""
if command -v cloudflared &>/dev/null; then
    CLOUDFLARED=$(command -v cloudflared)
elif [ -x "/usr/local/bin/cloudflared" ]; then
    CLOUDFLARED="/usr/local/bin/cloudflared"
elif [ -x "/usr/bin/cloudflared" ]; then
    CLOUDFLARED="/usr/bin/cloudflared"
elif [ -x "/root/.9router/bin/cloudflared" ]; then
    # Backward compat with 9router install
    CLOUDFLARED="/root/.9router/bin/cloudflared"
else
    echo "cloudflared not found. Install it first:"
    echo "  curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb"
    echo "  sudo dpkg -i /tmp/cloudflared.deb"
    exit 1
fi

LOG_FILE="/tmp/cloudflared-labsch.log"
PID_FILE="/tmp/cloudflared-labsch.pid"
PORT="${LABSCH_PORT:-8080}"

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

echo "Starting Cloudflare quick tunnel for http://localhost:$PORT ..."
echo "Using binary: $CLOUDFLARED"
echo "Logs: $LOG_FILE"
echo ""

# Run in background, capture URL from log
nohup "$CLOUDFLARED" tunnel --url "http://localhost:$PORT" --no-autoupdate \
    > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
TUNNEL_PID=$(cat "$PID_FILE")
echo "Tunnel started (PID $TUNNEL_PID)"

# Wait for URL to appear in log
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
    echo "For a stable URL, set up a named tunnel with your own domain."
    echo "See the README 'Server setup' section."
else
    echo "Failed to get tunnel URL. Check log:"
    tail -30 "$LOG_FILE"
    exit 1
fi
