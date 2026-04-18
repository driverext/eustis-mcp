#!/usr/bin/env python3
"""MCP server for UCF's Eustis environment.

This server can:
- Return Eustis connection guidance.
- Check whether the local machine appears able to reach Eustis.
- Run remote commands on Eustis via ssh.
- Upload and download files via scp.

Important constraint:
The machine running this MCP server must already have network access to Eustis,
typically through the UCF Cisco VPN or an authenticated campus network.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


EUSTIS_HOST = os.environ.get("EUSTIS_HOST", "eustis3.eecs.ucf.edu")
EUSTIS_IP = os.environ.get("EUSTIS_IP", "10.173.204.63")
VPN_URL = "https://secure.vpn.ucf.edu"
MOBA_URL = "http://mobaxterm.mobatek.net/"
HELP_EMAIL = "helpdesk@cecs.ucf.edu"
DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 300
BRIDGE_ROOT = Path(os.environ.get("EUSTIS_BRIDGE_DIR", "/tmp/eustis-mcp-bridge")).expanduser()


def text_block(value: str) -> Dict[str, Any]:
    return {"type": "text", "text": value}


def success_text(value: str) -> Dict[str, Any]:
    return {"content": [text_block(value)]}


def error_response(message_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def result_response(message_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def normalize_bool(value: Any) -> bool:
    return bool(value)


def get_required_string(arguments: Dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{key}' must be a non-empty string")
    return value.strip()


def get_optional_string(arguments: Dict[str, Any], key: str, default: str = "") -> str:
    value = arguments.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"'{key}' must be a string")
    return value.strip()


def get_timeout(arguments: Dict[str, Any]) -> int:
    value = arguments.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if not isinstance(value, int):
        raise ValueError("'timeout_seconds' must be an integer")
    if value < 1 or value > MAX_TIMEOUT_SECONDS:
        raise ValueError(f"'timeout_seconds' must be between 1 and {MAX_TIMEOUT_SECONDS}")
    return value


def format_list(items: List[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def resolve_nid(arguments: Dict[str, Any]) -> str:
    if "nid" in arguments:
        return get_required_string(arguments, "nid")
    nid = os.environ.get("EUSTIS_NID", "").strip()
    if nid:
        return nid
    raise ValueError("Missing 'nid'. Pass it explicitly or set EUSTIS_NID in the environment.")


def resolve_host(arguments: Dict[str, Any]) -> str:
    use_ip = normalize_bool(arguments.get("use_ip"))
    return EUSTIS_IP if use_ip else EUSTIS_HOST


def ensure_local_path_exists(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    if not path.exists():
        raise ValueError(f"Local path does not exist: {path}")
    return path


def bridge_enabled() -> bool:
    return os.environ.get("EUSTIS_USE_BRIDGE", "").strip().lower() in {"1", "true", "yes", "on"}


def bridge_paths() -> Dict[str, Path]:
    return {
        "root": BRIDGE_ROOT,
        "requests": BRIDGE_ROOT / "requests",
        "responses": BRIDGE_ROOT / "responses",
    }


def bridge_status_text() -> str:
    paths = bridge_paths()
    enabled = bridge_enabled()
    worker_file = paths["root"] / "worker.pid"
    lines = [
        f"Bridge enabled: {'yes' if enabled else 'no'}",
        f"Bridge directory: {paths['root']}",
        f"Requests dir exists: {'yes' if paths['requests'].exists() else 'no'}",
        f"Responses dir exists: {'yes' if paths['responses'].exists() else 'no'}",
        f"Worker pid file exists: {'yes' if worker_file.exists() else 'no'}",
    ]
    if not enabled:
        lines.append("Set EUSTIS_USE_BRIDGE=1 to force SSH/SCP calls through the filesystem bridge.")
    lines.append("Run bridge_agent.py in a normal terminal if your MCP client is sandboxed away from the VPN.")
    return "\n".join(lines)


def diagnose_runtime_mode(host: str, port: int, timeout_seconds: int) -> str:
    paths = bridge_paths()
    worker_file = paths["root"] / "worker.pid"
    lines = [f"Runtime diagnosis for {host}:{port}"]

    dns_ok = False
    tcp_ok = False
    resolved_ip = ""
    try:
        resolved_ip = socket.gethostbyname(host)
        dns_ok = True
        lines.append(f"DNS resolution: ok ({host} -> {resolved_ip})")
    except socket.gaierror as exc:
        lines.append(f"DNS resolution: failed ({exc})")

    if dns_ok:
        try:
            with socket.create_connection((host, port), timeout=timeout_seconds):
                tcp_ok = True
                lines.append("TCP connection: ok")
        except OSError as exc:
            lines.append(f"TCP connection: failed ({exc})")

    bridge_on = bridge_enabled()
    worker_on = worker_file.exists()
    lines.append(f"Bridge env enabled: {'yes' if bridge_on else 'no'}")
    lines.append(f"Bridge worker available: {'yes' if worker_on else 'no'}")

    if dns_ok and tcp_ok:
        lines.append("Conclusion: this runtime can reach Eustis directly.")
        if bridge_on:
            lines.append("Recommended mode: either direct mode or bridge mode will work, but bridge mode is not required.")
        else:
            lines.append("Recommended mode: direct SSH/SCP.")
        return "\n".join(lines)

    if worker_on:
        lines.append("Conclusion: this runtime does not have direct Eustis reachability, but a host-side bridge worker is available.")
        lines.append("Recommended mode: bridge SSH/SCP through the host terminal.")
        return "\n".join(lines)

    lines.append("Conclusion: this runtime cannot directly reach Eustis, and no bridge worker is available.")
    lines.append("Recommended mode: either run the MCP in a non-sandboxed environment or start bridge_agent.py in a normal terminal.")
    return "\n".join(lines)


def run_bridge_command(
    *,
    label: str,
    command: List[str],
    timeout_seconds: int,
) -> str:
    paths = bridge_paths()
    paths["requests"].mkdir(parents=True, exist_ok=True)
    paths["responses"].mkdir(parents=True, exist_ok=True)

    request_id = uuid.uuid4().hex
    request_path = paths["requests"] / f"{request_id}.json"
    response_path = paths["responses"] / f"{request_id}.json"
    payload = {
        "id": request_id,
        "label": label,
        "command": command,
        "timeout_seconds": timeout_seconds,
    }
    request_path.write_text(json.dumps(payload))

    deadline = time.time() + timeout_seconds + 5
    while time.time() < deadline:
        if response_path.exists():
            response = json.loads(response_path.read_text())
            response_path.unlink(missing_ok=True)
            request_path.unlink(missing_ok=True)
            return "\n".join(
                [
                    f"{label} exit code: {response.get('returncode', 1)}",
                    "",
                    "stdout:",
                    str(response.get("stdout", "")).strip(),
                    "",
                    "stderr:",
                    str(response.get("stderr", "")).strip(),
                ]
            ).strip()
        time.sleep(0.2)

    request_path.unlink(missing_ok=True)
    return (
        f"{label} bridge timed out after {timeout_seconds} seconds\n\n"
        "Make sure bridge_agent.py is running in a normal terminal with VPN access."
    )


def run_subprocess(command: List[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def summarize_process(name: str, process: subprocess.CompletedProcess[str]) -> str:
    stdout = process.stdout.strip()
    stderr = process.stderr.strip()
    lines = [f"{name} exit code: {process.returncode}"]
    if stdout:
        lines.extend(["", "stdout:", stdout])
    if stderr:
        lines.extend(["", "stderr:", stderr])
    return "\n".join(lines)


def detect_vpn_hint() -> str:
    hints: List[str] = []

    if sys.platform == "darwin":
        try:
            process = run_subprocess(["scutil", "--nc", "list"], timeout_seconds=5)
            combined = f"{process.stdout}\n{process.stderr}".lower()
            if "secure.vpn.ucf.edu" in combined or "connected" in combined:
                hints.append("macOS network services show at least one VPN entry; verify it is the active UCF connection.")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    for proc_name in ("Cisco Secure Client", "AnyConnect", "openconnect"):
        try:
            process = run_subprocess(["pgrep", "-fl", proc_name], timeout_seconds=5)
            if process.returncode == 0 and process.stdout.strip():
                hints.append(f"Detected a local VPN-related process matching '{proc_name}'.")
                break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    if not hints:
        return "No strong local VPN signal detected. If you are off campus, connect to the UCF Cisco VPN first."
    return " ".join(hints)


def build_ssh_base(arguments: Dict[str, Any]) -> List[str]:
    nid = resolve_nid(arguments)
    host = resolve_host(arguments)
    batch_mode = arguments.get("batch_mode", True)
    if not isinstance(batch_mode, bool):
        raise ValueError("'batch_mode' must be a boolean")

    command = ["ssh"]
    if batch_mode:
        command.extend(["-o", "BatchMode=yes"])

    disable_strict_host_key_checking = arguments.get("disable_strict_host_key_checking", False)
    if not isinstance(disable_strict_host_key_checking, bool):
        raise ValueError("'disable_strict_host_key_checking' must be a boolean")
    if disable_strict_host_key_checking:
        command.extend(["-o", "StrictHostKeyChecking=no"])

    port = arguments.get("port", 22)
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise ValueError("'port' must be an integer between 1 and 65535")
    if port != 22:
        command.extend(["-p", str(port)])

    return command + [f"{nid}@{host}"]


def build_scp_base(arguments: Dict[str, Any]) -> List[str]:
    nid = resolve_nid(arguments)
    host = resolve_host(arguments)
    recursive = arguments.get("recursive", False)
    if not isinstance(recursive, bool):
        raise ValueError("'recursive' must be a boolean")
    batch_mode = arguments.get("batch_mode", True)
    if not isinstance(batch_mode, bool):
        raise ValueError("'batch_mode' must be a boolean")

    command = ["scp"]
    if recursive:
        command.append("-r")
    if batch_mode:
        command.extend(["-o", "BatchMode=yes"])

    disable_strict_host_key_checking = arguments.get("disable_strict_host_key_checking", False)
    if not isinstance(disable_strict_host_key_checking, bool):
        raise ValueError("'disable_strict_host_key_checking' must be a boolean")
    if disable_strict_host_key_checking:
        command.extend(["-o", "StrictHostKeyChecking=no"])

    port = arguments.get("port", 22)
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise ValueError("'port' must be an integer between 1 and 65535")
    if port != 22:
        command.extend(["-P", str(port)])

    return command, f"{nid}@{host}"


def tool_get_quick_reference(_: Dict[str, Any]) -> Dict[str, Any]:
    return success_text(
        "\n".join(
            [
                "Eustis Quick Reference",
                f"- Hostname: {EUSTIS_HOST}",
                f"- Direct IP: {EUSTIS_IP}",
                "- Username: your UCF NID",
                "- Password: your NID password",
                f"- VPN portal: {VPN_URL}",
                f"- Help email: {HELP_EMAIL}",
                "- Campus Wi-Fi: UCF_WPA2 with your NID credentials usually works without the VPN",
                f"- MobaXTerm download: {MOBA_URL}",
                "- SSH port: 22",
                "- For direct MCP interaction, the host machine must already be on the VPN or an authenticated campus network",
                f"- Optional sandbox bridge directory: {BRIDGE_ROOT}",
            ]
        )
    )


def tool_check_eustis_access(arguments: Dict[str, Any]) -> Dict[str, Any]:
    host = resolve_host(arguments)
    port = arguments.get("port", 22)
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise ValueError("'port' must be an integer between 1 and 65535")

    timeout_seconds = get_timeout(arguments)
    lines = [f"Checking Eustis access for {host}:{port}"]
    if bridge_enabled():
        lines.append("Bridge mode is enabled for SSH/SCP tool execution.")

    try:
        resolved_ip = socket.gethostbyname(host)
        lines.append(f"DNS resolution: ok ({host} -> {resolved_ip})")
    except socket.gaierror as exc:
        lines.append(f"DNS resolution: failed ({exc})")
        lines.append(detect_vpn_hint())
        lines.append(f"If you are off campus, connect to the UCF VPN: {VPN_URL}")
        if host != EUSTIS_IP:
            lines.append(f"WSL fallback: try the direct IP {EUSTIS_IP}")
        return success_text("\n".join(lines))

    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            lines.append("TCP connection to port 22: ok")
    except OSError as exc:
        lines.append(f"TCP connection to port 22: failed ({exc})")
        lines.append(detect_vpn_hint())
        lines.append("This usually means the local machine is not on the UCF VPN or cannot reach the campus network path to Eustis.")
        return success_text("\n".join(lines))

    if shutil.which("ssh") is None:
        lines.append("ssh client: not found on this machine")
    else:
        lines.append("ssh client: available")

    lines.append("Network path looks good. Remote tool calls should work if SSH authentication is already set up.")
    lines.append("If password auth is your only option, open a manual SSH session first or configure SSH keys, because MCP tools run non-interactively by default.")
    return success_text("\n".join(lines))


def tool_diagnose_runtime(arguments: Dict[str, Any]) -> Dict[str, Any]:
    host = resolve_host(arguments)
    port = arguments.get("port", 22)
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise ValueError("'port' must be an integer between 1 and 65535")
    timeout_seconds = get_timeout(arguments)
    return success_text(diagnose_runtime_mode(host, port, timeout_seconds))


def tool_build_ssh_command(arguments: Dict[str, Any]) -> Dict[str, Any]:
    include_key_reset = normalize_bool(arguments.get("include_key_reset"))
    command = build_ssh_base(arguments)
    lines = [" ".join(command)]
    if include_key_reset:
        lines.extend(["", "If you see a host identification warning first, run:", f"ssh-keygen -R {EUSTIS_HOST}"])
    return success_text("\n".join(lines))


def tool_build_scp_command(arguments: Dict[str, Any]) -> Dict[str, Any]:
    local_path = get_required_string(arguments, "local_path")
    remote_path = get_optional_string(arguments, "remote_path", "~/")
    if not remote_path:
        raise ValueError("'remote_path' must be a non-empty string when provided")
    command, remote = build_scp_base(arguments)
    full_command = command + [local_path, f"{remote}:{remote_path}"]
    return success_text(" ".join(full_command))


HOSTNAME_TROUBLESHOOTING = [
    "If you are off campus, connect to the UCF VPN first.",
    "If you are on campus and already connected to the VPN, disconnect the VPN and try again.",
    "If you are on campus using UCF_GUEST, switch to UCF_WPA2 with your NID credentials.",
    "If you are on UCF_WPA2 and still cannot resolve the host, especially from a dorm, connect to the VPN and retry.",
    f"If you are using WSL and hostname resolution still fails, try the direct IP: ssh YOUR_NID@{EUSTIS_IP}",
]


def tool_troubleshoot_hostname(arguments: Dict[str, Any]) -> Dict[str, Any]:
    platform = str(arguments.get("platform", "general")).strip().lower()
    on_campus = arguments.get("on_campus")
    on_vpn = arguments.get("on_vpn")
    wifi = str(arguments.get("wifi_network", "")).strip()

    suggestions: List[str] = []
    if on_campus is False and on_vpn is not True:
        suggestions.append(f"You appear to be off campus without VPN access. Connect to {VPN_URL}.")
    if on_campus is True and on_vpn is True:
        suggestions.append("You appear to be on campus while still on VPN. Disconnect the VPN and retry.")
    if on_campus is True and wifi.upper() == "UCF_GUEST":
        suggestions.append("Use UCF_WPA2 instead of UCF_GUEST for Eustis access.")
    if platform in {"wsl", "windows subsystem for linux", "bash on windows"}:
        suggestions.append(f"WSL sometimes needs the direct IP instead of the hostname: {EUSTIS_IP}.")
    if not suggestions:
        suggestions.extend(HOSTNAME_TROUBLESHOOTING)

    suggestions.append(detect_vpn_hint())
    return success_text("Troubleshooting steps:\n" + format_list(suggestions))


LINUX_COMMANDS: Dict[str, str] = {
    "gcc": "\n".join(
        [
            "Compile one C file:",
            "gcc source.c",
            "",
            "Compile and name the output:",
            "gcc source.c -o whatever",
            "",
            "Compile multiple files:",
            "gcc source1.c source2.c source3.c",
            "",
            "Link the math library when using math.h:",
            "gcc source.c -lm",
        ]
    ),
    "./a.out": "Run the default executable produced by gcc:\n./a.out",
    "diff": "Compare two files exactly:\ndiff output.txt solution.txt",
    "ls": "List files in the current directory:\nls",
    "rm": "Delete a file:\nrm output.txt",
    "cat": "Print a file to the terminal:\ncat output.txt",
    "redirect": "Send program output to a file:\n./a.out > output.txt",
    "scp": "\n".join(
        [
            "Copy one file to Eustis:",
            "scp some_file.txt YOUR_NID@eustis3.eecs.ucf.edu:~/",
            "",
            "Copy a whole folder recursively:",
            "scp -r MyProjectFolder YOUR_NID@eustis3.eecs.ucf.edu:~/",
        ]
    ),
    "ssh": "Connect to Eustis:\nssh YOUR_NID@eustis3.eecs.ucf.edu",
}


def tool_linux_command_help(arguments: Dict[str, Any]) -> Dict[str, Any]:
    topic = get_required_string(arguments, "topic").lower()
    if topic in LINUX_COMMANDS:
        return success_text(LINUX_COMMANDS[topic])
    suggestions = ", ".join(sorted(LINUX_COMMANDS))
    return success_text(f"No exact match for '{topic}'. Available topics: {suggestions}")


def tool_connection_checklist(arguments: Dict[str, Any]) -> Dict[str, Any]:
    platform = str(arguments.get("platform", "mac-linux")).strip().lower()

    if platform in {"windows", "mobaxterm"}:
        checklist = [
            "If you are off campus, connect to the UCF VPN first.",
            "Open MobaXTerm and create a new SSH session.",
            f"Remote host: {EUSTIS_HOST}",
            "Port: 22",
            "Specify username: your NID",
            "Log in with your NID password.",
        ]
    elif platform in {"linux-vpn", "linux"}:
        checklist = [
            f"If needed, install Cisco AnyConnect from {VPN_URL}.",
            "Connect to the VPN using your NID and NID password.",
            f"Open a terminal and run: ssh YOUR_NID@{EUSTIS_HOST}",
            "Type your NID password even though no asterisks appear.",
        ]
    else:
        checklist = [
            "If you are off campus, connect to the UCF VPN first.",
            f"Open a terminal and run: ssh YOUR_NID@{EUSTIS_HOST}",
            "Type your NID password even though no asterisks appear.",
            "If you see a host key warning, remove the old key with ssh-keygen -R eustis3.eecs.ucf.edu.",
        ]

    checklist.append("For MCP-driven remote execution, make sure SSH authentication is already usable from this machine.")
    return success_text("Connection checklist:\n" + format_list(checklist))


def tool_run_remote_command(arguments: Dict[str, Any]) -> Dict[str, Any]:
    command_text = get_required_string(arguments, "command")
    timeout_seconds = get_timeout(arguments)
    ssh_command = build_ssh_base(arguments) + ["--", command_text]

    if bridge_enabled():
        return success_text(
            run_bridge_command(
                label="ssh",
                command=ssh_command,
                timeout_seconds=timeout_seconds,
            )
        )

    try:
        process = run_subprocess(ssh_command, timeout_seconds=timeout_seconds)
    except FileNotFoundError:
        raise ValueError("The local 'ssh' executable was not found")
    except subprocess.TimeoutExpired:
        return success_text(f"ssh command timed out after {timeout_seconds} seconds")

    summary = summarize_process("ssh", process)
    if process.returncode == 255:
        summary += "\n\nHint: this often means the VPN is disconnected, DNS cannot reach Eustis, or SSH auth is not ready for non-interactive use."
    return success_text(summary)


def tool_upload_to_eustis(arguments: Dict[str, Any]) -> Dict[str, Any]:
    local_path = ensure_local_path_exists(get_required_string(arguments, "local_path"))
    remote_path = get_optional_string(arguments, "remote_path", "~/")
    timeout_seconds = get_timeout(arguments)

    scp_command, remote = build_scp_base(arguments)
    if local_path.is_dir() and "-r" not in scp_command:
        raise ValueError("Local path is a directory; set 'recursive' to true")
    full_command = scp_command + [str(local_path), f"{remote}:{remote_path}"]

    if bridge_enabled():
        return success_text(
            run_bridge_command(
                label="scp upload",
                command=full_command,
                timeout_seconds=timeout_seconds,
            )
        )

    try:
        process = run_subprocess(full_command, timeout_seconds=timeout_seconds)
    except FileNotFoundError:
        raise ValueError("The local 'scp' executable was not found")
    except subprocess.TimeoutExpired:
        return success_text(f"scp upload timed out after {timeout_seconds} seconds")

    return success_text(summarize_process("scp upload", process))


def tool_download_from_eustis(arguments: Dict[str, Any]) -> Dict[str, Any]:
    remote_path = get_required_string(arguments, "remote_path")
    local_path = Path(get_required_string(arguments, "local_path")).expanduser()
    timeout_seconds = get_timeout(arguments)

    if local_path.parent and not local_path.parent.exists():
        raise ValueError(f"Local destination directory does not exist: {local_path.parent}")

    scp_command, remote = build_scp_base(arguments)
    full_command = scp_command + [f"{remote}:{remote_path}", str(local_path)]

    if bridge_enabled():
        return success_text(
            run_bridge_command(
                label="scp download",
                command=full_command,
                timeout_seconds=timeout_seconds,
            )
        )

    try:
        process = run_subprocess(full_command, timeout_seconds=timeout_seconds)
    except FileNotFoundError:
        raise ValueError("The local 'scp' executable was not found")
    except subprocess.TimeoutExpired:
        return success_text(f"scp download timed out after {timeout_seconds} seconds")

    return success_text(summarize_process("scp download", process))


def tool_list_remote_home(arguments: Dict[str, Any]) -> Dict[str, Any]:
    list_arguments = dict(arguments)
    list_arguments["command"] = "pwd && ls -la"
    return tool_run_remote_command(list_arguments)


def tool_bridge_status(_: Dict[str, Any]) -> Dict[str, Any]:
    return success_text(bridge_status_text())


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[[Dict[str, Any]], Dict[str, Any]]


COMMON_SSH_PROPERTIES: Dict[str, Any] = {
    "nid": {"type": "string", "description": "The student's UCF NID. Optional if EUSTIS_NID is set."},
    "use_ip": {"type": "boolean", "description": "Use the direct IP instead of the hostname."},
    "batch_mode": {
        "type": "boolean",
        "description": "Use BatchMode=yes to fail fast if SSH auth is not already available. Defaults to true.",
    },
    "disable_strict_host_key_checking": {
        "type": "boolean",
        "description": "Set StrictHostKeyChecking=no for first-time or changing host keys.",
    },
    "port": {"type": "integer", "description": "SSH port. Defaults to 22."},
}


TOOLS: Dict[str, ToolDefinition] = {
    "get_quick_reference": ToolDefinition(
        name="get_quick_reference",
        description="Return key Eustis connection details like hostname, VPN URL, SSH port, and support contact.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=tool_get_quick_reference,
    ),
    "bridge_status": ToolDefinition(
        name="bridge_status",
        description="Show whether filesystem bridge mode is enabled for sandboxed environments and where it expects the bridge worker.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=tool_bridge_status,
    ),
    "check_eustis_access": ToolDefinition(
        name="check_eustis_access",
        description="Check whether this machine can resolve and reach Eustis over the network before trying remote commands.",
        input_schema={
            "type": "object",
            "properties": {
                "use_ip": {"type": "boolean", "description": "Use the direct IP instead of the hostname."},
                "port": {"type": "integer", "description": "SSH port. Defaults to 22."},
                "timeout_seconds": {"type": "integer", "description": "Socket timeout in seconds. Defaults to 30."},
            },
            "additionalProperties": False,
        },
        handler=tool_check_eustis_access,
    ),
    "diagnose_runtime": ToolDefinition(
        name="diagnose_runtime",
        description="Diagnose whether this MCP runtime can reach Eustis directly or should use the bridge worker instead.",
        input_schema={
            "type": "object",
            "properties": {
                "use_ip": {"type": "boolean", "description": "Use the direct IP instead of the hostname."},
                "port": {"type": "integer", "description": "SSH port. Defaults to 22."},
                "timeout_seconds": {"type": "integer", "description": "Socket timeout in seconds. Defaults to 30."},
            },
            "additionalProperties": False,
        },
        handler=tool_diagnose_runtime,
    ),
    "build_ssh_command": ToolDefinition(
        name="build_ssh_command",
        description="Build an SSH command for connecting to Eustis with an optional direct-IP fallback.",
        input_schema={
            "type": "object",
            "properties": {
                **COMMON_SSH_PROPERTIES,
                "include_key_reset": {"type": "boolean", "description": "Include the ssh-keygen fix for stale host keys."},
            },
            "additionalProperties": False,
        },
        handler=tool_build_ssh_command,
    ),
    "build_scp_command": ToolDefinition(
        name="build_scp_command",
        description="Build an SCP command for uploading a file or directory to the user's Eustis home directory.",
        input_schema={
            "type": "object",
            "properties": {
                **COMMON_SSH_PROPERTIES,
                "local_path": {"type": "string", "description": "Local file or directory to copy."},
                "remote_path": {"type": "string", "description": "Destination path on Eustis. Defaults to ~/."},
                "recursive": {"type": "boolean", "description": "Whether to include -r for folders."},
            },
            "required": ["local_path"],
            "additionalProperties": False,
        },
        handler=tool_build_scp_command,
    ),
    "troubleshoot_hostname": ToolDefinition(
        name="troubleshoot_hostname",
        description="Provide likely fixes for 'Could not resolve hostname' errors when connecting to Eustis.",
        input_schema={
            "type": "object",
            "properties": {
                "platform": {"type": "string", "description": "Optional platform, such as wsl, mac, linux, or windows."},
                "on_campus": {"type": "boolean", "description": "Whether the user is physically on campus."},
                "on_vpn": {"type": "boolean", "description": "Whether the user is currently connected to the VPN."},
                "wifi_network": {"type": "string", "description": "Optional Wi-Fi network name, like UCF_GUEST or UCF_WPA2."},
            },
            "additionalProperties": False,
        },
        handler=tool_troubleshoot_hostname,
    ),
    "linux_command_help": ToolDefinition(
        name="linux_command_help",
        description="Explain common Linux and Eustis-related commands from the guide, such as gcc, ssh, scp, diff, or cat.",
        input_schema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Command or topic to explain."},
            },
            "required": ["topic"],
            "additionalProperties": False,
        },
        handler=tool_linux_command_help,
    ),
    "connection_checklist": ToolDefinition(
        name="connection_checklist",
        description="Return a short step-by-step checklist for connecting to Eustis from common platforms.",
        input_schema={
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "description": "Platform hint such as mac-linux, windows, mobaxterm, or linux-vpn.",
                },
            },
            "additionalProperties": False,
        },
        handler=tool_connection_checklist,
    ),
    "run_remote_command": ToolDefinition(
        name="run_remote_command",
        description="Run a shell command on Eustis over SSH and return stdout, stderr, and the exit code.",
        input_schema={
            "type": "object",
            "properties": {
                **COMMON_SSH_PROPERTIES,
                "command": {"type": "string", "description": "Remote shell command to execute on Eustis."},
                "timeout_seconds": {"type": "integer", "description": "Command timeout in seconds. Defaults to 30."},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        handler=tool_run_remote_command,
    ),
    "upload_to_eustis": ToolDefinition(
        name="upload_to_eustis",
        description="Upload a local file or directory to Eustis via scp.",
        input_schema={
            "type": "object",
            "properties": {
                **COMMON_SSH_PROPERTIES,
                "local_path": {"type": "string", "description": "Local file or directory to upload."},
                "remote_path": {"type": "string", "description": "Destination path on Eustis. Defaults to ~/."},
                "recursive": {"type": "boolean", "description": "Set true when uploading a directory."},
                "timeout_seconds": {"type": "integer", "description": "Transfer timeout in seconds. Defaults to 30."},
            },
            "required": ["local_path"],
            "additionalProperties": False,
        },
        handler=tool_upload_to_eustis,
    ),
    "download_from_eustis": ToolDefinition(
        name="download_from_eustis",
        description="Download a file or directory from Eustis via scp.",
        input_schema={
            "type": "object",
            "properties": {
                **COMMON_SSH_PROPERTIES,
                "remote_path": {"type": "string", "description": "Remote file or directory to download."},
                "local_path": {"type": "string", "description": "Local destination path."},
                "recursive": {"type": "boolean", "description": "Set true when downloading a directory."},
                "timeout_seconds": {"type": "integer", "description": "Transfer timeout in seconds. Defaults to 30."},
            },
            "required": ["remote_path", "local_path"],
            "additionalProperties": False,
        },
        handler=tool_download_from_eustis,
    ),
    "list_remote_home": ToolDefinition(
        name="list_remote_home",
        description="Run 'pwd && ls -la' on Eustis to quickly inspect the remote home directory.",
        input_schema={
            "type": "object",
            "properties": {
                **COMMON_SSH_PROPERTIES,
                "timeout_seconds": {"type": "integer", "description": "Command timeout in seconds. Defaults to 30."},
            },
            "additionalProperties": False,
        },
        handler=tool_list_remote_home,
    ),
}


SERVER_INFO = {"name": "eustis-mcp", "version": "0.2.0"}


def handle_initialize(message_id: Any, _: Dict[str, Any]) -> Dict[str, Any]:
    return result_response(
        message_id,
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        },
    )


def handle_tools_list(message_id: Any) -> Dict[str, Any]:
    tools = [
        {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.input_schema,
        }
        for tool in TOOLS.values()
    ]
    return result_response(message_id, {"tools": tools})


def handle_tools_call(message_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    name = params.get("name")
    if not isinstance(name, str) or name not in TOOLS:
        return error_response(message_id, -32602, "Unknown tool")

    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        return error_response(message_id, -32602, "'arguments' must be an object")

    try:
        result = TOOLS[name].handler(arguments)
    except ValueError as exc:
        return error_response(message_id, -32602, str(exc))
    except Exception as exc:  # pragma: no cover
        return error_response(message_id, -32000, f"Tool execution failed: {exc}")

    return result_response(message_id, result)


def read_message() -> Optional[Dict[str, Any]]:
    headers: Dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        decoded = line.decode("utf-8").strip()
        if ":" not in decoded:
            continue
        key, value = decoded.split(":", 1)
        headers[key.strip().lower()] = value.strip()

    content_length = headers.get("content-length")
    if content_length is None:
        return None

    body = sys.stdin.buffer.read(int(content_length))
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def write_message(payload: Dict[str, Any]) -> None:
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("utf-8"))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def handle_request(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = message.get("method")
    message_id = message.get("id")
    params = message.get("params", {})

    if method == "initialize":
        return handle_initialize(message_id, params if isinstance(params, dict) else {})
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return result_response(message_id, {})
    if method == "tools/list":
        return handle_tools_list(message_id)
    if method == "tools/call":
        if not isinstance(params, dict):
            return error_response(message_id, -32602, "'params' must be an object")
        return handle_tools_call(message_id, params)

    if message_id is None:
        return None
    return error_response(message_id, -32601, f"Method not found: {method}")


def main() -> int:
    while True:
        message = read_message()
        if message is None:
            return 0
        response = handle_request(message)
        if response is not None:
            write_message(response)


if __name__ == "__main__":
    raise SystemExit(main())
