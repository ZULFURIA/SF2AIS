#!/bin/bash
# Reverses exactly what install.sh did - nothing more.
set -e

if [ "$EUID" -ne 0 ]; then
  echo "Please run with sudo."
  exit 1
fi

INSTALL_DIR="/opt/sf2ais"
SERVICE_USER="sf2ais"

echo "=== Uninstalling Sf2AiS ==="

systemctl stop sf2ais 2>/dev/null || true
systemctl disable sf2ais 2>/dev/null || true
rm -f /etc/systemd/system/sf2ais.service
systemctl daemon-reload

read -p "Remove install directory $INSTALL_DIR (this includes your shared_files and config)? [y/N] " confirm
if [[ "$confirm" =~ ^[Yy]$ ]]; then
    rm -rf "$INSTALL_DIR"
    echo "Removed $INSTALL_DIR"
else
    echo "Left $INSTALL_DIR in place."
fi

id -u "$SERVICE_USER" &>/dev/null && userdel "$SERVICE_USER"

echo "[SUCCESS] Sf2AiS uninstalled."
