# Installs or updates BeeView + xPollinator on a plain Windows server (no AWS, no auth proxy).
# Uses the same artefacts as the AWS deployment (deploy/aws/deploy.sh package), taken from a local folder:
#   xpollinator.zip     xPollinator repo tree (bundled Python 3.9.7, JDK 24, NetLogo included)
#   beeview-server.zip  BeeView-server tree without venv/data (includes frontend/)
#   data.zip            BeeView-server\data (beeview.duckdb, cache, shapefile, arr.dat, csv)
#
# No separate Python install: the BeeView-server venv is created from the Python bundled with xPollinator
# (model\core\bin\python-3.9.7-amd64). Internet access is needed once for pip (PyPI).
#
# Run as administrator from the folder holding the zips (or pass -Source):
#   powershell -ExecutionPolicy Bypass -File install.ps1 [-Source D:\drop] [-Root C:\xLandscape] [-Port 32000] [-NoService]
#
# Re-running with new zips updates the code and keeps xPollinator\run, BeeView-server\data and the venv.
# Serves http://<host>:<Port> to everyone who can reach the machine (no authentication): rely on the
# university firewall or put a reverse proxy in front if access must be restricted.
param(
    [string]$Source = $PSScriptRoot,
    [string]$Root = "C:\xLandscape",
    [int]$Port = 32000,
    [int]$MaxConcurrentJobs = 2,
    [switch]$NoService   # only install; start manually with $Root\run-beeview.cmd
)
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$logDir = "$Root\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Start-Transcript -Path "$logDir\install_$(Get-Date -Format yyyyMMdd_HHmmss).log" -Append

foreach ($name in @("xpollinator", "beeview-server", "data")) {
    if (-not (Test-Path "$Source\$name.zip")) { throw "$Source\$name.zip not found" }
}

# Expand-Archive rejects the ZIP64 archives bsdtar writes for the 1.3 GB xPollinator tree; tar.exe reads them.
function Expand-Zip($zip, $dest) {
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    & "$env:SystemRoot\System32\tar.exe" -xf $zip -C $dest
    if ($LASTEXITCODE -ne 0) { throw "extraction of $zip failed" }
}

# ---------------------------------------------------------------- stop a running service
$taskName = "BeeViewServer"
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
}
Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$Root\BeeView-server\*" } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3

# ---------------------------------------------------------------- xPollinator: replace tree, keep run/
$xp = "$Root\xPollinator"
if (Test-Path "$xp\run") { Move-Item "$xp\run" "$Root\xPollinator_run_keep" -Force }
if (Test-Path $xp) { Remove-Item $xp -Recurse -Force }
Expand-Zip "$Source\xpollinator.zip" $Root
if (Test-Path "$Root\xPollinator_run_keep") { Move-Item "$Root\xPollinator_run_keep" "$xp\run" -Force } else { New-Item -ItemType Directory -Force -Path "$xp\run" | Out-Null }

$python = "$xp\model\core\bin\python-3.9.7-amd64\python.exe"
if (-not (Test-Path $python)) { throw "bundled Python not found at $python" }

# ---------------------------------------------------------------- BeeView-server: replace code, keep data/ and venv/
$srv = "$Root\BeeView-server"
$keepData = Test-Path "$srv\data\beeview.duckdb"
if ($keepData) { Move-Item "$srv\data" "$Root\BeeView_data_keep" -Force }
if (Test-Path "$srv\venv") { Move-Item "$srv\venv" "$Root\BeeView_venv_keep" -Force }
if (Test-Path $srv) { Remove-Item $srv -Recurse -Force }
Expand-Zip "$Source\beeview-server.zip" $Root
if ($keepData) { Move-Item "$Root\BeeView_data_keep" "$srv\data" -Force } else { Expand-Zip "$Source\data.zip" $srv }
if (Test-Path "$Root\BeeView_venv_keep") { Move-Item "$Root\BeeView_venv_keep" "$srv\venv" -Force }

# ---------------------------------------------------------------- virtual environment (from the bundled Python)
if (-not (Test-Path "$srv\venv\Scripts\python.exe")) { & $python -m venv "$srv\venv" }
& "$srv\venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& "$srv\venv\Scripts\python.exe" -m pip install --quiet -r "$srv\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "pip install failed (internet access to PyPI needed; behind a TLS-inspecting proxy set PIP_CERT to the CA bundle)" }

# ---------------------------------------------------------------- firewall
if (-not (Get-NetFirewallRule -DisplayName "BeeView $Port" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "BeeView $Port" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
}

# ---------------------------------------------------------------- runner + service (scheduled task, SYSTEM, at startup)
$runner = "$Root\run-beeview.cmd"
@"
@echo off
cd /d $srv
set XPOLLINATOR_PATH=$xp
set MAX_CONCURRENT_JOBS=$MaxConcurrentJobs
set BEEVIEW_PORT=$Port
"$srv\venv\Scripts\python.exe" main.py >> "$logDir\beeview-server.log" 2>&1
"@ | Set-Content -Path $runner -Encoding ASCII

if ($NoService) {
    Write-Host "installed without service; start with $runner"
    Stop-Transcript
    exit 0
}
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$runner`"" -WorkingDirectory $srv
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName $taskName

# ---------------------------------------------------------------- health check
$ok = $false
for ($i = 0; $i -lt 60 -and -not $ok; $i++) {
    Start-Sleep -Seconds 5
    try { $ok = (Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:$Port/api/runs" -TimeoutSec 5).StatusCode -eq 200 } catch { }
}
Write-Host ("BeeView-server healthy: {0}  ->  http://{1}:{2}/" -f $ok, $env:COMPUTERNAME, $Port)
Stop-Transcript
if (-not $ok) { exit 1 }
