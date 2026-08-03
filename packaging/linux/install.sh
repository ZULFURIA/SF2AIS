#!/bin/bash
# Sf2AiS installer - works the same across Debian/Ubuntu/Mint, Arch,
# Fedora/RHEL/SUSE, or anything else with bash, python3, and systemd.
# No distro-specific package manager involved on purpose.
set -e

if [ "$EUID" -ne 0 ]; then
  echo "Please run with sudo."
  exit 1
fi

INSTALL_DIR="/opt/sf2ais"
SERVICE_USER="sf2ais"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Installing Sf2AiS to $INSTALL_DIR ==="

if ! command -v python3 &> /dev/null; then
    echo "Error: python3 not found. Install it with your distro's package manager first."
    exit 1
fi

id -u "$SERVICE_USER" &>/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"

mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR/../../"{main.py,ddns.py,micro_firewall.py,requirements.txt,static,shared_files} "$INSTALL_DIR/" 2>/dev/null || true

echo "Setting up virtual environment..."
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"

echo "Installing systemd service..."
cp "$SCRIPT_DIR/sf2ais.service" /etc/systemd/system/sf2ais.service
systemctl daemon-reload
systemctl enable sf2ais
systemctl start sf2ais

echo ""
echo "[SUCCESS] Sf2AiS installed and running."
echo "  Status:  systemctl status sf2ais"
echo "  Logs:    journalctl -u sf2ais -f"
echo "  Config:  $INSTALL_DIR"
echo "  Uninstall: sudo $SCRIPT_DIR/uninstall.sh"
