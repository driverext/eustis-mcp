# eustis-mcp

Unofficial MCP server for UCF's Eustis Linux server.

This project is not affiliated with or maintained by UCF.

It lets an MCP client run SSH commands on `eustis3.eecs.ucf.edu`, transfer files with SCP, and detect whether it should use direct network access or a local bridge worker.

## Before You Start

- If you are not on UCF Wi-Fi or another UCF network, connect to the UCF VPN first with Cisco AnyConnect / Cisco Secure Client at `https://secure.vpn.ucf.edu`.
- You need SSH access to `eustis3.eecs.ucf.edu`.
- For best results, set up SSH keys for Eustis.

## Quick Start

### Codex

Install the MCP:

```bash
./install.sh --nid your_nid --bridge
```

If your client is sandboxed, start the bridge worker:

```bash
./bridge.sh
```

Then in the MCP client, call:

```json
{
  "name": "diagnose_runtime",
  "arguments": {}
}
```

If that looks good, test:

```json
{
  "name": "list_remote_home",
  "arguments": {
    "timeout_seconds": 10
  }
}
```

## When To Use The Bridge

Use bridge mode when:

- `ssh your_nid@eustis3.eecs.ucf.edu` works in your normal terminal
- but your MCP client cannot resolve or reach Eustis

Bridge mode lets the MCP server hand SSH and SCP work to a helper process running outside the sandbox on the same machine.

## Client Setup

The MCP server command is:

```bash
python3 /absolute/path/to/eustis-mcp/server.py
```

Useful environment variables:

```bash
EUSTIS_NID=your_nid
EUSTIS_USE_BRIDGE=1
```

### Codex Config

`./install.sh --nid your_nid --bridge` writes the Codex config for you.

### Claude Desktop / Cursor / Other JSON MCP Clients

```json
{
  "mcpServers": {
    "eustis": {
      "command": "python3",
      "args": ["/absolute/path/to/eustis-mcp/server.py"],
      "env": {
        "EUSTIS_NID": "your_nid",
        "EUSTIS_USE_BRIDGE": "1"
      }
    }
  }
}
```

## SSH Key Setup

If you have not set up SSH keys yet:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_eustis -C "your_nid@eustis3.eecs.ucf.edu"
ssh-copy-id -i ~/.ssh/id_ed25519_eustis.pub your_nid@eustis3.eecs.ucf.edu
ssh -o BatchMode=yes your_nid@eustis3.eecs.ucf.edu -- pwd
```

If the last command prints your home directory, MCP remote execution should work much more smoothly.

## Bridge Automation

Start bridge auto-launch at login:

### macOS

```bash
./install_bridge_macos.sh
```

### Linux

```bash
./install_bridge_linux.sh
```

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\install_bridge_windows.ps1
```

## Most Useful Tools

- `diagnose_runtime`
- `bridge_status`
- `list_remote_home`
- `run_remote_command`
- `upload_to_eustis`
- `download_from_eustis`

## Troubleshooting

### `Could not resolve hostname`

Usually means:

- you are not connected to UCF VPN
- or your MCP client cannot see the host network

If `ssh` works in your terminal but not in the MCP client, use bridge mode.

### Bridge Mode Times Out

Make sure:

- `./bridge.sh` is running
- your normal terminal can SSH to Eustis
- your SSH keys are installed on Eustis

### Test SSH Directly

```bash
ssh -o BatchMode=yes your_nid@eustis3.eecs.ucf.edu -- pwd
```

## Security Notes

- Do not store your NID password in this repo or client config.
- This project does not automate the UCF VPN login flow.
- Bridge mode is local-only and uses a private per-user temp directory.
