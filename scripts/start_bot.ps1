# Start a bot (under the supervisor) in the background, hidden.
#
#   .\scripts\start_bot.ps1                        # the paper bot
#   .\scripts\start_bot.ps1 -Config configs\core.toml
#
# Safe to run twice: the bot's lock makes a second instance refuse to start.
param(
    [string]$Config = "configs\paper-core.toml"
)

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "no virtualenv at $python - run: py -m venv .venv" }
New-Item -ItemType Directory -Force (Join-Path $root "logs") | Out-Null

$name = [IO.Path]::GetFileNameWithoutExtension($Config)
$proc = Start-Process -FilePath $python `
    -ArgumentList "scripts\supervise.py", "--config", $Config `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $root "logs\$name.supervisor.out") `
    -RedirectStandardError  (Join-Path $root "logs\$name.supervisor.err")

Start-Sleep -Seconds 6
Write-Host "started $name (supervisor pid $($proc.Id))"
$log = Join-Path $root "logs\$name.log"
if (Test-Path $log) { Get-Content $log -Tail 3 }
Write-Host "`nwatch it with:  Get-Content logs\$name.log -Wait -Tail 5"
