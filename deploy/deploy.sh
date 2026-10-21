#!/usr/bin/env bash
set -euo pipefail

# Paths and user are derived from where the repo lives and who runs the script
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="${SUDO_USER:-$(id -un)}"
SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
SERVICE_NAME="pi-sonos-player.service"

echo "=== Deploying Pi-Sonos-Player ==="
echo "    Directory: $APP_DIR"
echo "    User:      $SERVICE_USER"
cd "$APP_DIR"

# 1. System packages (libxslt for lxml used by SoCo)
sudo apt-get install -y --no-install-recommends python3-venv libxslt1.1

if [ ! -d venv ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

# 2. Python dependencies (yt-dlp is upgraded every deploy; YouTube changes often)
echo "Installing / updating dependencies..."
./venv/bin/pip install --upgrade pip
./venv/bin/pip install --upgrade -r backend/requirements.txt

[ -f .env ] || cp .env.example .env
mkdir -p .cache

# 3. Render and install systemd unit
echo "Configuring systemd service..."
sed -e "s|__APP_DIR__|$APP_DIR|g" \
    -e "s|__USER__|$SERVICE_USER|g" \
    -e "s|__GROUP__|$SERVICE_GROUP|g" \
    deploy/pi-sonos-player.service | sudo tee "/etc/systemd/system/$SERVICE_NAME" > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

# 4. Verify
sleep 3
if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    PORT="$(grep -E '^PORT=' .env | cut -d= -f2 || true)"
    PI_IP="$(hostname -I | awk '{print $1}')"
    echo "====================================================="
    echo " SUCCESS: Service is running!"
    echo " Open in your browser: http://${PI_IP}:${PORT:-5000}"
    echo "====================================================="
else
    echo " ERROR: Service failed to start. Recent logs:"
    sudo journalctl -u "$SERVICE_NAME" -n 25 --no-pager
    exit 1
fi
