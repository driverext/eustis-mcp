#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/com.eustis-mcp.bridge.plist"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
BRIDGE_DIR="${EUSTIS_BRIDGE_DIR:-/tmp/eustis-mcp-${USER}}"

mkdir -p "$PLIST_DIR"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>com.eustis-mcp.bridge</string>
    <key>ProgramArguments</key>
    <array>
      <string>$PYTHON_BIN</string>
      <string>$SCRIPT_DIR/bridge_agent.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
      <key>EUSTIS_BRIDGE_DIR</key>
      <string>$BRIDGE_DIR</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/eustis-mcp-bridge.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/eustis-mcp-bridge.stderr.log</string>
  </dict>
</plist>
PLIST

launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl load "$PLIST_PATH"

echo "Installed macOS bridge autostart: $PLIST_PATH"
echo "Bridge directory: $BRIDGE_DIR"
echo "The bridge worker will now start automatically at login."
