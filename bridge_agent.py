#!/usr/bin/env python3
"""Host-side bridge worker for sandboxed eustis-mcp clients.

Run this in a normal terminal with VPN access. The MCP server can then submit
ssh/scp jobs via the shared filesystem instead of needing direct network access.
"""

from __future__ import annotations

import getpass
import json
import os
import secrets
import stat
import subprocess
import tempfile
import time
import uuid
from pathlib import Path


BRIDGE_DIR_MODE = 0o700
BRIDGE_FILE_MODE = 0o600


def default_bridge_root() -> Path:
    return Path("/tmp") / f"eustis-mcp-{getpass.getuser()}"


BRIDGE_ROOT = Path(os.environ.get("EUSTIS_BRIDGE_DIR", str(default_bridge_root()))).expanduser()
REQUESTS = BRIDGE_ROOT / "requests"
RESPONSES = BRIDGE_ROOT / "responses"
PID_FILE = BRIDGE_ROOT / "worker.pid"
TOKEN_FILE = BRIDGE_ROOT / "bridge.token"


def current_uid():
    return os.getuid() if hasattr(os, "getuid") else None


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=BRIDGE_DIR_MODE)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise RuntimeError(f"Refusing to use symlink as bridge directory: {path}")
    if not path.is_dir():
        raise RuntimeError(f"Bridge path is not a directory: {path}")
    uid = current_uid()
    if uid is not None and info.st_uid != uid:
        raise RuntimeError(f"Bridge directory is not owned by the current user: {path}")
    if uid is not None:
        os.chmod(path, BRIDGE_DIR_MODE)


def ensure_private_file(path: Path) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        raise RuntimeError(f"Refusing to use symlink as bridge file: {path}")
    uid = current_uid()
    if uid is not None and info.st_uid != uid:
        raise RuntimeError(f"Bridge file is not owned by the current user: {path}")
    if uid is not None:
        os.chmod(path, BRIDGE_FILE_MODE)


def atomic_write_text(path: Path, text: str) -> None:
    tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, BRIDGE_FILE_MODE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload) -> None:
    atomic_write_text(path, json.dumps(payload))


def ensure_dirs() -> None:
    ensure_private_dir(BRIDGE_ROOT)
    ensure_private_dir(REQUESTS)
    ensure_private_dir(RESPONSES)


def write_pid() -> None:
    atomic_write_text(PID_FILE, str(os.getpid()))
    ensure_private_file(PID_FILE)


def remove_pid() -> None:
    PID_FILE.unlink(missing_ok=True)


def ensure_token() -> str:
    env_token = os.environ.get("EUSTIS_BRIDGE_TOKEN", "").strip()
    if env_token:
        return env_token
    if TOKEN_FILE.exists():
        ensure_private_file(TOKEN_FILE)
        token = TOKEN_FILE.read_text().strip()
        if token:
            return token
    token = secrets.token_hex(32)
    atomic_write_text(TOKEN_FILE, token)
    ensure_private_file(TOKEN_FILE)
    return token


def read_request(path: Path):
    ensure_private_file(path)
    return json.loads(path.read_text())


def handle_request(path: Path, token: str) -> None:
    try:
        payload = read_request(path)
        if payload.get("token") != token:
            response = {"token": token, "returncode": 1, "stdout": "", "stderr": "Invalid bridge token"}
        else:
            command = payload["command"]
            timeout_seconds = int(payload.get("timeout_seconds", 30))
            try:
                process = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    check=False,
                )
                response = {
                    "token": token,
                    "returncode": process.returncode,
                    "stdout": process.stdout,
                    "stderr": process.stderr,
                }
            except subprocess.TimeoutExpired as exc:
                response = {
                    "token": token,
                    "returncode": 124,
                    "stdout": exc.stdout or "",
                    "stderr": (exc.stderr or "") + f"\nTimed out after {timeout_seconds} seconds",
                }
            except Exception as exc:
                response = {"token": token, "returncode": 1, "stdout": "", "stderr": str(exc)}

        request_id = payload.get("id", path.stem)
        response_path = RESPONSES / f"{request_id}.json"
        atomic_write_json(response_path, response)
        ensure_private_file(response_path)
    finally:
        path.unlink(missing_ok=True)


def main() -> int:
    ensure_dirs()
    token = ensure_token()
    write_pid()
    print(f"Bridge root: {BRIDGE_ROOT}")
    print("Watching for requests. Press Ctrl+C to stop.")

    try:
        while True:
            for path in sorted(REQUESTS.glob("*.json")):
                handle_request(path, token)
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopping bridge worker.")
    finally:
        remove_pid()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
