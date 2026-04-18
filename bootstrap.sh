#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${1:-}"
NID="${2:-}"
INSTALL_DIR="${EUSTIS_MCP_INSTALL_DIR:-$HOME/.local/share/eustis-mcp}"

if [[ -z "$REPO_URL" ]]; then
  echo "usage: bash bootstrap.sh <repo-url> [nid]" >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "error: git is required for bootstrap installation" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 is required for bootstrap installation" >&2
  exit 1
fi

mkdir -p "$(dirname "$INSTALL_DIR")"

if [[ -d "$INSTALL_DIR/.git" ]]; then
  git -C "$INSTALL_DIR" pull --ff-only
else
  rm -rf "$INSTALL_DIR"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

if [[ -n "$NID" ]]; then
  exec "$INSTALL_DIR/install.sh" --repo-dir "$INSTALL_DIR" --nid "$NID"
else
  exec "$INSTALL_DIR/install.sh" --repo-dir "$INSTALL_DIR"
fi
