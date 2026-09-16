# Start a bot automatically whenever you log in, so a reboot does not silently stop trading.
#
#   .\scripts\install_autostart.ps1                          # register for the paper bot
#   .\scripts\install_autostart.ps1 -Config configs\core.toml -TaskName qtrading-core
#   .\scripts\install_autostart.ps1 -Remove                   # unregister
#
# Uses a per-user scheduled task, so no administrator rights are needed. The bot's lock means the task starting
# while a bot is already running is harmless: the second instance refuses and exits.
param(
    [string]$Config = "configs\paper-core.toml",
    [string]$TaskName = "qtrading-paper",
    [switch]$Remove
)

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "removed scheduled task $TaskName"
    return
}

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "no virtualenv at $python - run: py -m venv .venv" }

$action = New-ScheduledTaskAction -Execute $python `
    -Argument "scripts\supervise.py --config $Config" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn
# keep it running indefinitely and restart it if Windows ever stops it
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "qtrading: keep $Config trading across logins" -Force | Out-Null

Write-Host "registered scheduled task '$TaskName' - $Config starts at every logon"
Write-Host "remove it with:  .\scripts\install_autostart.ps1 -Remove -TaskName $TaskName"
