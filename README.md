# Raspberry Pi YouTube-to-Sonos Web Player

A lightweight, self-hosted web application for streaming YouTube audio directly to Sonos speakers on your local network. Designed specifically for low-resource single-board computers like the Raspberry Pi Model B (ARMv6, 512MB RAM).

---

## 1. Architecture Decision

### Why Not Music Assistant?
Before committing to this architecture, **Music Assistant** was evaluated:
- **CPU Architecture Incompatibility:** Music Assistant 2.x is distributed as container images that require **ARMv7, ARM64, or x86_64**. The target Raspberry Pi Model B Rev 2 has an **ARMv6 (32-bit BCM2835)** CPU, for which no official Music Assistant builds exist.
- **Severe Memory Limits:** The Pi has **~426 MiB RAM**. Running Docker and Music Assistant Server requires a minimum of 1–2 GB RAM and triggers immediate out-of-memory (OOM) failures on 512MB hardware.
- **Scope Mismatch:** Music Assistant is a full multi-room media server with library indexing. This project needs a focused, single-purpose YouTube-to-Sonos controller with instant startup and zero background bloat.

### Selected Architecture
A **native Python service** using:
1. **Flask + Waitress (Python 3.13):** Minimal RAM footprint (~25 MB total), production-grade threaded WSGI server.
2. **SoCo (Sonos Controller):** LAN discovery and UPnP transport control for all Sonos speakers.
3. **yt-dlp + Stream Proxy:** Extracts direct AAC audio streams (format 140: 128kbps AAC-LC) and proxies HTTP chunks with Range header support directly to Sonos. This bypasses YouTube SSL/cipher restrictions on older Sonos players, uses **0% CPU** (pure network I/O pass-through), and causes zero SD card write wear.

```
[ User Browser ]
       │ (HTTP Web UI :5000)
       ▼
[ Raspberry Pi (Flask / yt-dlp) ] ── (Pipes stream) ──> [ Sonos Speaker ]
       │                                                      │
       └─── (SoCo UPnP Play Command with DIDL Metadata) ──────┘
```

---

## 2. Hardware & OS Compatibility

- **Target Device:** Raspberry Pi Model B Rev 2 / Raspberry Pi Zero / 2 / 3 / 4 / 5.
- **Operating System:** Raspberry Pi OS Lite (Debian 13 Trixie / Debian 12 Bookworm).
- **RAM:** Less than 30MB required.
- **Network:** Connected to the same subnet/Wi-Fi as your Sonos speakers.

---

## 3. Quick Setup on a Clean Raspberry Pi

Run these commands in an SSH session on the Raspberry Pi:

### Step 1: Install System Dependencies
```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git libxslt1.1
```

### Step 2: Clone the Repository
```bash
git clone https://github.com/chris9689/pi-sonos-player ~/pi-sonos-player
cd ~/pi-sonos-player
```

### Step 3: Run the Automated Deploy Script
```bash
bash deploy/deploy.sh
```

The script detects the repo location and current user, sets up the Python virtual environment, creates `.env` from `.env.example`, registers the systemd service, and starts it automatically.

Access the web interface at:
```
http://<PI_IP>:5000
```

Tip: on your phone, open the page and use *Add to Home Screen*. You can also prefill a link via `http://<PI_IP>:5000/?url=<youtube link>` (handy for iOS Shortcuts / Android share actions).

---

## 4. Development Workflow (Windows PC to Pi)

This repository is designed to be edited on a development workstation (e.g., Windows PC) and deployed to the Pi via GitHub:

```
[ Workstation ] ── git push ──> [ GitHub ] ── git pull ──> [ Raspberry Pi ]
```

### Editing on Windows
1. Clone the repository on Windows:
   ```powershell
   git clone https://github.com/chris9689/pi-sonos-player
   cd pi-sonos-player
   ```
2. Make your edits to frontend (`frontend/`) or backend (`backend/`).
3. Commit and push:
   ```powershell
   git add .
   git commit -m "Update player styling"
   git push origin main
   ```

### Updating the Raspberry Pi
1. SSH into the Pi:
   ```powershell
   ssh <USER>@<PI_IP>
   ```
2. Pull and restart:
   ```bash
   cd ~/pi-sonos-player
   git pull
   bash deploy/deploy.sh
   ```

Alternatively, push the current commit directly without GitHub:
```powershell
.\sync_to_pi.ps1 -PiHost <PI_IP> -User <USER> -Deploy
```

---

## 5. Service Management & Troubleshooting

### Check Service Status
```bash
sudo systemctl status pi-sonos-player
```

### View Live Logs
```bash
sudo journalctl -u pi-sonos-player -f
```

### Restart Service
```bash
sudo systemctl restart pi-sonos-player
```

### Stop Service
```bash
sudo systemctl stop pi-sonos-player
```

---

## 6. Network & Firewall Configuration

- **Port 5000 (TCP):** Web UI and HTTP audio streaming endpoint.
- **Port 1900 (UDP):** SSDP / UPnP multicast discovery used by SoCo.
- **Port 1400 / 1443 (TCP):** Sonos UPnP control and status events.
- **FRITZ!Box / Router Setting:** Ensure *"Die unten aufgeführten aktiven WLAN-Geräte dürfen untereinander kommunizieren"* (devices may communicate with each other) is enabled. Devices connected to a Guest Network (`192.168.179.x`) are isolated and cannot discover Sonos on the primary network (`192.168.178.x`).

---

## 7. Acceptance Test Checklist

- [x] Web interface loads from desktop and mobile browser via `http://<PI_IP>:5000`.
- [x] Discovers all Sonos speakers on the local subnet (`/api/speakers`).
- [x] Pasting a YouTube URL extracts video title and thumbnail.
- [x] Clicking **Play** streams audio to the selected Sonos speaker.
- [x] Transport controls (**Pause**, **Resume**, **Stop**, **Volume Slider**) react in real time.
- [x] Playback continues uninterrupted if the browser tab or client device is closed.
- [x] Background service starts automatically after Raspberry Pi reboot.
