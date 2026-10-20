#!/usr/bin/env bash
set -e

APP_DIR="/home/chris/pi-sonos-player"
SERVICE_NAME="pi-sonos-player.service"

echo "=== Deploying Pi-Sonos-Player on Raspberry Pi ==="
cd "$APP_DIR"

# 1. Ensure required system packages and Python virtual environment exist
sudo apt-get install -y --no-install-recommends libxslt1.1

if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

# 2. Upgrade pip and install pinned requirements
echo "Installing / updating dependencies..."
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r backend/requirements.txt

# 3. Install / update systemd service unit
echo "Configuring systemd service..."
sudo cp deploy/pi-sonos-player.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

# 4. Wait briefly and verify status
sleep 2
if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    PI_IP=$(hostname -I | awk '{print $1}')
    echo "====================================================="
    echo " SUCCESS: Service is running!"
    echo " Open in your browser: http://${PI_IP}:5000"
    echo "====================================================="
else
    echo " ERROR: Service failed to start. Showing recent logs:"
    sudo journalctl -u "$SERVICE_NAME" -n 25 --no-pager
    exit 1
fi
