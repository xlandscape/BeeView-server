# Installs or updates BeeView + xPollinator on a plain Windows server (no AWS, no authentication).
# See INSTALL.md next to this script. Input files, built by deploy/package.sh, in one folder:
#   xpollinator.zip     xPollinator with model core, BeeHaveEcotox, scenario (bundled Python 3.9.7, JDK, NetLogo)
#   beeview-server.zip  BeeView-server with the built web frontend
#   data.zip            BeeView database (all imported runs), forage array, land-use shapefile, caches
#   wheels.zip          optional: Python packages for an install without internet access
#
# Run in an elevated PowerShell from the folder holding the files (or pass -Source):
#   powershell -ExecutionPolicy Bypass -File install.ps1 [-Source D:\drop] [-Root C:\xLandscape] [-Port 32000]
#                                                        [-MaxConcurrentJobs 2] [-NoService] [-ReplaceData]
#
# Re-running with new files updates the code and keeps xPollinator\run (simulation results),
# BeeView-server\data (database) and the venv. -ReplaceData replaces the database with the one in data.zip
# (the previous data folder is kept as data_backup_<timestamp>).
param(
    [string]$Source = $PSScriptRoot,
    [string]$Root = "C:\xLandscape",
    [int]$Port = 32000,
    [int]$MaxConcurrentJobs = 2,
    [switch]$NoService,    # no scheduled task and no firewall rule; start by hand with $Root\run-beeview.cmd
    [switch]$ReplaceData   # replace an existing database with the one from data.zip
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
Write-Host "installing xPollinator"
$xp = "$Root\xPollinator"
if (Test-Path "$xp\run") { Move-Item "$xp\run" "$Root\xPollinator_run_keep" -Force }
if (Test-Path $xp) { Remove-Item $xp -Recurse -Force }
Expand-Zip "$Source\xpollinator.zip" $Root
if (Test-Path "$Root\xPollinator_run_keep") { Move-Item "$Root\xPollinator_run_keep" "$xp\run" -Force } else { New-Item -ItemType Directory -Force -Path "$xp\run" | Out-Null }

$python = "$xp\model\core\bin\python-3.9.7-amd64\python.exe"
if (-not (Test-Path $python)) { throw "bundled Python not found at $python" }

# ---------------------------------------------------------------- BeeView-server: replace code, keep data/ and venv/
Write-Host "installing BeeView-server"
$srv = "$Root\BeeView-server"
$keepData = (Test-Path "$srv\data\beeview.duckdb") -and -not $ReplaceData
if ($keepData) { Move-Item "$srv\data" "$Root\BeeView_data_keep" -Force }
elseif (Test-Path "$srv\data") { Move-Item "$srv\data" "$Root\BeeView_data_backup_$(Get-Date -Format yyyyMMdd_HHmmss)" -Force }
if (Test-Path "$srv\venv") { Move-Item "$srv\venv" "$Root\BeeView_venv_keep" -Force }
if (Test-Path $srv) { Remove-Item $srv -Recurse -Force }
Expand-Zip "$Source\beeview-server.zip" $Root
if ($keepData) { Move-Item "$Root\BeeView_data_keep" "$srv\data" -Force; Write-Host "kept existing database" }
else { Expand-Zip "$Source\data.zip" $srv; Write-Host "database installed from data.zip" }
if (Test-Path "$Root\BeeView_venv_keep") { Move-Item "$Root\BeeView_venv_keep" "$srv\venv" -Force }

# ---------------------------------------------------------------- virtual environment (from the bundled Python)
Write-Host "installing Python packages"
if (-not (Test-Path "$srv\venv\Scripts\python.exe")) { & $python -m venv "$srv\venv" }
$venvPython = "$srv\venv\Scripts\python.exe"
if (Test-Path "$Source\wheels.zip") {
    $wheels = "$Root\wheels"
    if (Test-Path $wheels) { Remove-Item $wheels -Recurse -Force }
    Expand-Zip "$Source\wheels.zip" $Root
    & $venvPython -m pip install --quiet --no-index --find-links $wheels --upgrade pip
    & $venvPython -m pip install --quiet --no-index --find-links $wheels -r "$srv\requirements.txt"
} else {
    & $venvPython -m pip install --quiet --upgrade pip
    & $venvPython -m pip install --quiet -r "$srv\requirements.txt"
}
if ($LASTEXITCODE -ne 0) { throw "pip install failed (without wheels.zip, internet access to PyPI is needed; behind a TLS-inspecting proxy set PIP_CERT to the CA bundle)" }

foreach ($f in @("VERSIONS.txt", "INSTALL.md")) {
    if (Test-Path "$Source\$f") { Copy-Item "$Source\$f" "$Root\$f" -Force }
}

# ---------------------------------------------------------------- runner
$runner = "$Root\run-beeview.cmd"
@"
@echo off
cd /d $srv
set XPOLLINATOR_PATH=$xp
set MAX_CONCURRENT_JOBS=$MaxConcurrentJobs
set BEEVIEW_PORT=$Port
"$venvPython" main.py >> "$logDir\beeview-server.log" 2>&1
"@ | Set-Content -Path $runner -Encoding ASCII

if ($NoService) {
    Write-Host "installed without service; start with $runner, then open http://localhost:$Port/"
    Stop-Transcript
    exit 0
}

# ---------------------------------------------------------------- firewall + service (scheduled task, SYSTEM, at startup)
if (-not (Get-NetFirewallRule -DisplayName "BeeView $Port" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "BeeView $Port" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
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
