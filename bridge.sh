#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export EUSTIS_BRIDGE_DIR="${EUSTIS_BRIDGE_DIR:-/tmp/eustis-mcp-${USER}}"
exec python3 "$SCRIPT_DIR/bridge_agent.py"
