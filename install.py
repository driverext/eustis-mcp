#!/usr/bin/env python3
"""Install eustis-mcp into a local Codex MCP config."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path


SECTION_NAME = "eustis"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Register the local eustis-mcp server in ~/.codex/config.toml."
    )
    parser.add_argument(
        "--repo-dir",
        default=str(Path(__file__).resolve().parent),
        help="Path to the eustis-mcp repository. Defaults to this script's directory.",
    )
    parser.add_argument(
        "--config-path",
        default=str(Path.home() / ".codex" / "config.toml"),
        help="Codex config file to update. Defaults to ~/.codex/config.toml.",
    )
    parser.add_argument(
        "--name",
        default=SECTION_NAME,
        help="MCP server name to register in Codex. Defaults to 'eustis'.",
    )
    parser.add_argument(
        "--nid",
        default="",
        help="Optional UCF NID to bake into the MCP env block as EUSTIS_NID.",
    )
    parser.add_argument(
        "--bridge",
        action="store_true",
        help="Enable bridge mode by setting EUSTIS_USE_BRIDGE=1 in the MCP env block.",
    )
    parser.add_argument(
        "--bridge-dir",
        default="",
        help="Optional bridge directory to bake into the MCP env block as EUSTIS_BRIDGE_DIR.",
    )
    parser.add_argument(
        "--python",
        default=shutil.which("python3") or "python3",
        help="Python executable to use in the MCP command. Defaults to the current python3.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generated config block without writing it.",
    )
    return parser.parse_args()


def build_section(name: str, python_cmd: str, server_path: Path, nid: str, bridge: bool, bridge_dir: str) -> str:
    lines = [
        f"[mcp_servers.{name}]",
        f'command = "{python_cmd}"',
        f'args = ["{server_path}"]',
    ]
    env_lines = []
    if nid:
        env_lines.append(f'EUSTIS_NID = "{nid}"')
    if bridge:
        env_lines.append('EUSTIS_USE_BRIDGE = "1"')
    if bridge_dir:
        env_lines.append(f'EUSTIS_BRIDGE_DIR = "{bridge_dir}"')
    if env_lines:
        lines.append("[mcp_servers.%s.env]" % name)
        lines.extend(env_lines)
    return "\n".join(lines) + "\n"


def upsert_section(existing_text: str, name: str, section_text: str) -> str:
    pattern = re.compile(
        rf"(?ms)^\[mcp_servers\.{re.escape(name)}\]\n.*?(?=^\[|\Z)"
    )
    if pattern.search(existing_text):
        return pattern.sub(section_text + "\n", existing_text, count=1)

    insertion_anchor = re.compile(r"(?m)^\[mcp_servers\.[^\]]+\]\n")
    matches = list(insertion_anchor.finditer(existing_text))
    if matches:
        last_match = matches[-1]
        section_start = last_match.start()
        next_section = re.search(r"(?m)^\[", existing_text[last_match.end() :])
        if next_section:
            insert_at = last_match.end() + next_section.start()
        else:
            insert_at = len(existing_text)
        prefix = existing_text[:insert_at].rstrip() + "\n\n"
        suffix = existing_text[insert_at:].lstrip("\n")
        return prefix + section_text + "\n" + suffix

    base = existing_text.rstrip()
    if base:
        base += "\n\n"
    return base + section_text


def main() -> int:
    args = parse_args()
    repo_dir = Path(args.repo_dir).expanduser().resolve()
    config_path = Path(args.config_path).expanduser()
    server_path = repo_dir / "server.py"

    if not server_path.exists():
        print(f"error: server.py was not found at {server_path}", file=sys.stderr)
        return 1

    section_text = build_section(args.name, args.python, server_path, args.nid, args.bridge, args.bridge_dir)
    if args.dry_run:
        print(section_text, end="")
        return 0

    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing_text = config_path.read_text() if config_path.exists() else ""
    updated_text = upsert_section(existing_text, args.name, section_text)
    config_path.write_text(updated_text)

    print(f"Updated {config_path}")
    print(f"Registered MCP server '{args.name}' -> {server_path}")
    if args.nid:
        print("Stored EUSTIS_NID in the MCP config env block.")
    else:
        print("No NID stored in config. Pass --nid later if you want a default.")
    if args.bridge:
        print("Enabled bridge mode in the MCP config env block.")
    if args.bridge_dir:
        print(f"Stored EUSTIS_BRIDGE_DIR={args.bridge_dir} in the MCP config env block.")
    print("Restart or reload Codex before testing the new MCP server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
