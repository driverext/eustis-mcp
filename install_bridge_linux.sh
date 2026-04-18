#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_PATH="$SERVICE_DIR/eustis-mcp-bridge.service"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
BRIDGE_DIR="${EUSTIS_BRIDGE_DIR:-/tmp/eustis-mcp-${USER}}"

mkdir -p "$SERVICE_DIR"

cat > "$SERVICE_PATH" <<SERVICE
[Unit]
Description=Eustis MCP bridge worker
After=default.target

[Service]
Type=simple
Environment=EUSTIS_BRIDGE_DIR=$BRIDGE_DIR
ExecStart=$PYTHON_BIN $SCRIPT_DIR/bridge_agent.py
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
SERVICE

systemctl --user daemon-reload
systemctl --user enable --now eustis-mcp-bridge.service

echo "Installed Linux bridge autostart: $SERVICE_PATH"
echo "Bridge directory: $BRIDGE_DIR"
echo "The bridge worker is enabled for your user session."
