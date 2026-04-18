# eustis-mcp

MCP server for UCF's Eustis environment.

It helps an MCP client connect to `eustis3.eecs.ucf.edu`, run remote commands over SSH, transfer files with SCP, and diagnose whether the current runtime can reach the host directly or should use a bridge worker.

## Features

- SSH-backed remote command execution
- SCP upload and download helpers
- runtime diagnosis for sandboxed clients
- filesystem bridge mode for clients that cannot see the host VPN
- zero external Python dependencies

## Requirements

- `python3`
- SSH access to `eustis3.eecs.ucf.edu`
- UCF network access:
  either Cisco AnyConnect / Cisco Secure Client, or an authenticated campus network

Recommended:

- SSH keys for Eustis
- bridge mode for sandboxed clients like Codex when the client process cannot see the host VPN

## Quick Start

1. Clone the repo.
2. Install the MCP in your client config.
3. If your client is sandboxed, enable bridge mode.
4. Call `diagnose_runtime`.
5. Use `list_remote_home` or `run_remote_command`.

### Codex Quick Start

```bash
./install.sh --nid ab123456 --bridge
```

This writes a Codex MCP config entry for `eustis` and enables bridge mode in the MCP env block.

Then start the bridge worker once:

```bash
./bridge.sh
```

If you want bridge auto-start, see `Bridge Automation` below.

## How It Works

There are two supported execution modes:

### Direct Mode

The MCP server itself can resolve and reach `eustis3.eecs.ucf.edu`.

Use this when:

- your MCP client can see the same network and DNS context as your normal terminal
- `ssh your_nid@eustis3.eecs.ucf.edu` works from the same runtime

### Bridge Mode

The MCP client is sandboxed and cannot see the host VPN, but your normal terminal can.

In bridge mode:

- the MCP server writes SSH and SCP jobs to a private per-user bridge directory under the system temp folder
- `bridge_agent.py` runs outside the sandbox on the same machine
- the bridge worker executes the real SSH and SCP commands

Use this when:

- `ssh` works in Terminal
- `diagnose_runtime` says direct reachability is unavailable
- your MCP client cannot resolve `eustis3.eecs.ucf.edu`

## Install

### Codex

Install into `~/.codex/config.toml`:

```bash
./install.sh --nid ab123456 --bridge
```

Useful options:

```bash
./install.sh --help
./install.sh --dry-run
./install.sh --name eustis-ucf
./install.sh --config-path ~/.codex/config.toml
./install.sh --bridge-dir /tmp/eustis-mcp-youruser
```

Example generated TOML:

```toml
[mcp_servers.eustis]
command = "python3"
args = ["/absolute/path/to/eustis-mcp/server.py"]

[mcp_servers.eustis.env]
EUSTIS_NID = "ab123456"
EUSTIS_USE_BRIDGE = "1"
```

### Other MCP Clients

The server command is always:

```bash
python3 /absolute/path/to/eustis-mcp/server.py
```

Common env vars:

```bash
EUSTIS_NID=ab123456
EUSTIS_USE_BRIDGE=1
EUSTIS_BRIDGE_DIR=/tmp/eustis-mcp-youruser
```

### Claude Desktop

```json
{
  "mcpServers": {
    "eustis": {
      "command": "python3",
      "args": ["/absolute/path/to/eustis-mcp/server.py"],
      "env": {
        "EUSTIS_NID": "ab123456",
        "EUSTIS_USE_BRIDGE": "1"
      }
    }
  }
}
```

Typical config paths:

```text
macOS: ~/Library/Application Support/Claude/claude_desktop_config.json
Windows: %APPDATA%\Claude\claude_desktop_config.json
```

### Cursor And Other JSON-Based MCP Clients

Use the same `mcpServers` shape as the Claude Desktop example above.

## Bridge Setup

Start the bridge worker manually:

```bash
./bridge.sh
```

Expected output:

```text
Bridge root: /tmp/eustis-mcp-youruser
Watching for requests. Press Ctrl+C to stop.
```

Keep that process running while your MCP client uses bridge mode.

## Bridge Automation

### macOS

Installs a `launchd` agent that starts the bridge worker at login:

```bash
./install_bridge_macos.sh
```

It writes:

```text
~/Library/LaunchAgents/com.eustis-mcp.bridge.plist
```

### Linux

Installs a user-level `systemd` service that starts automatically:

```bash
./install_bridge_linux.sh
```

It writes:

```text
~/.config/systemd/user/eustis-mcp-bridge.service
```

This requires a Linux environment with `systemd --user`.

### Windows

Registers a Scheduled Task that starts the bridge worker at logon:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_bridge_windows.ps1
```

This uses the task name:

```text
eustis-mcp-bridge
```

## SSH Key Setup

Bridge mode works best with SSH keys, because MCP tool calls are non-interactive.

Example:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_eustis -C "your_nid@eustis3.eecs.ucf.edu"
ssh-copy-id -i ~/.ssh/id_ed25519_eustis.pub your_nid@eustis3.eecs.ucf.edu
ssh -o BatchMode=yes your_nid@eustis3.eecs.ucf.edu -- pwd
```

If the last command prints your home directory, key-based auth is ready.

## Recommended First Calls

Call these in order:

### 1. Diagnose The Runtime

```json
{
  "name": "diagnose_runtime",
  "arguments": {}
}
```

### 2. Inspect Bridge State

```json
{
  "name": "bridge_status",
  "arguments": {}
}
```

### 3. Test Remote Access

```json
{
  "name": "list_remote_home",
  "arguments": {
    "timeout_seconds": 10
  }
}
```

## Tools

- `diagnose_runtime`
- `bridge_status`
- `check_eustis_access`
- `list_remote_home`
- `run_remote_command`
- `upload_to_eustis`
- `download_from_eustis`
- `build_ssh_command`
- `build_scp_command`
- `get_quick_reference`
- `connection_checklist`
- `troubleshoot_hostname`
- `linux_command_help`

## Files

- `server.py`: MCP server
- `bridge_agent.py`: host-side bridge worker
- `bridge.sh`: starts the bridge worker
- `install.py`: Codex MCP config installer
- `install.sh`: shell wrapper for `install.py`
- `install_bridge_macos.sh`: macOS bridge auto-start installer
- `install_bridge_linux.sh`: Linux bridge auto-start installer
- `install_bridge_windows.ps1`: Windows bridge auto-start installer
- `bootstrap.sh`: clone-and-install helper for GitHub use

## Troubleshooting

### `diagnose_runtime` says direct reachability is unavailable

That means the current MCP runtime cannot resolve or connect to `eustis3.eecs.ucf.edu`.

Use bridge mode if:

- SSH works in your normal terminal
- the MCP client itself is sandboxed

### Bridge worker is running but SSH fails

Most likely causes:

- the host machine is not on the UCF VPN
- SSH keys are not installed on Eustis
- the wrong username or host is configured

Test in a normal terminal:

```bash
ssh -o BatchMode=yes your_nid@eustis3.eecs.ucf.edu -- pwd
```

### VPN works in Terminal but not in the MCP client

That is the main use case for bridge mode.

### `openconnect` support

UCF's `UCF Students` group plus Microsoft web login did not prove reliable enough to use as the default VPN automation path for this project. The recommended approach is still:

- connect Cisco AnyConnect manually on the host
- use SSH keys
- use bridge mode when the MCP client is sandboxed

## Security Notes

- This project does not store your Eustis password.
- Bridge mode only works on the same machine because it uses a local filesystem queue in a private per-user temp directory.
- The bridge now validates directory ownership, file permissions, and a shared bridge token before executing queued jobs.
- SSH keys are preferred over password prompts for MCP use.
