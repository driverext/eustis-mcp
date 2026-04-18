$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BridgeDir = if ($env:EUSTIS_BRIDGE_DIR) { $env:EUSTIS_BRIDGE_DIR } else { Join-Path $env:TEMP ("eustis-mcp-" + $env:USERNAME) }
$Python = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }
$TaskName = "eustis-mcp-bridge"
$BridgeScript = Join-Path $ScriptDir "bridge_agent.py"
$Command = "set EUSTIS_BRIDGE_DIR=$BridgeDir && `"$Python`" `"$BridgeScript`""

$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $Command"
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Starts the Eustis MCP bridge worker at logon" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Installed Windows bridge autostart task: $TaskName"
Write-Host "Bridge directory: $BridgeDir"
Write-Host "The bridge worker will now start automatically at logon."
