#!/usr/bin/env python3
"""Host-side bridge worker for sandboxed eustis-mcp clients.

Run this in a normal terminal with VPN access. The MCP server can then submit
ssh/scp jobs via the shared filesystem instead of needing direct network access.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


BRIDGE_ROOT = Path(os.environ.get("EUSTIS_BRIDGE_DIR", "/tmp/eustis-mcp-bridge")).expanduser()
REQUESTS = BRIDGE_ROOT / "requests"
RESPONSES = BRIDGE_ROOT / "responses"
PID_FILE = BRIDGE_ROOT / "worker.pid"


def ensure_dirs() -> None:
    REQUESTS.mkdir(parents=True, exist_ok=True)
    RESPONSES.mkdir(parents=True, exist_ok=True)


def write_pid() -> None:
    PID_FILE.write_text(str(os.getpid()))


def remove_pid() -> None:
    PID_FILE.unlink(missing_ok=True)


def handle_request(path: Path) -> None:
    payload = json.loads(path.read_text())
    command = payload["command"]
    timeout_seconds = int(payload.get("timeout_seconds", 30))
    request_id = payload["id"]
    response_path = RESPONSES / f"{request_id}.json"

    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        response = {
            "returncode": process.returncode,
            "stdout": process.stdout,
            "stderr": process.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        response = {
            "returncode": 124,
            "stdout": exc.stdout or "",
            "stderr": (exc.stderr or "") + f"\nTimed out after {timeout_seconds} seconds",
        }
    except Exception as exc:
        response = {"returncode": 1, "stdout": "", "stderr": str(exc)}

    response_path.write_text(json.dumps(response))
    path.unlink(missing_ok=True)


def main() -> int:
    ensure_dirs()
    write_pid()
    print(f"Bridge root: {BRIDGE_ROOT}")
    print("Watching for requests. Press Ctrl+C to stop.")

    try:
        while True:
            for path in sorted(REQUESTS.glob("*.json")):
                handle_request(path)
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopping bridge worker.")
    finally:
        remove_pid()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
