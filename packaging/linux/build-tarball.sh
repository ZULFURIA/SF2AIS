#!/bin/bash
# Builds the distributable tarball: sf2ais-linux.tar.gz containing the app
# source, install.sh, uninstall.sh, and the systemd unit. Run from anywhere;
# always packages relative to the repo root.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BUILD_DIR="$(mktemp -d)"
PKG_NAME="sf2ais-linux"

echo "=== Building $PKG_NAME.tar.gz ==="

mkdir -p "$BUILD_DIR/$PKG_NAME"
cp "$REPO_ROOT/main.py" "$REPO_ROOT/ddns.py" "$REPO_ROOT/micro_firewall.py" \
   "$REPO_ROOT/requirements.txt" "$REPO_ROOT/README.md" "$BUILD_DIR/$PKG_NAME/"
cp -r "$REPO_ROOT/static" "$BUILD_DIR/$PKG_NAME/"
mkdir -p "$BUILD_DIR/$PKG_NAME/shared_files"
cp "$SCRIPT_DIR/install.sh" "$SCRIPT_DIR/uninstall.sh" "$SCRIPT_DIR/sf2ais.service" "$BUILD_DIR/$PKG_NAME/"
chmod +x "$BUILD_DIR/$PKG_NAME/install.sh" "$BUILD_DIR/$PKG_NAME/uninstall.sh"

tar -czf "$REPO_ROOT/$PKG_NAME.tar.gz" -C "$BUILD_DIR" "$PKG_NAME"
rm -rf "$BUILD_DIR"

echo "[SUCCESS] Built $REPO_ROOT/$PKG_NAME.tar.gz"
echo "Install with: tar xzf $PKG_NAME.tar.gz && cd $PKG_NAME && sudo ./install.sh"
