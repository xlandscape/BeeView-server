# Bootstrap of the BeeView / xPollinator host. Runs once from EC2 user data (as SYSTEM);
# can be re-run via SSM to pick up new artefacts: it stops the service, replaces the
# application folders (keeping xPollinator\run and the database) and starts again.
#
# Expects in s3://$env:BEEVIEW_DEPLOY_BUCKET/$env:BEEVIEW_ARTIFACT_PREFIX/:
#   xpollinator.zip     xPollinator repo tree (model, scenario, scripts, template.xrun)
#   beeview-server.zip  BeeView-server tree without venv/data (includes frontend/)
#   data.zip            BeeView-server\data (beeview.duckdb, cache, shapefile, arr.dat, csv)
#   python-3.11-amd64.exe  CPython installer
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$root = "C:\xLandscape"
$logDir = "$root\logs"
$staging = "$root\staging"
$bucket = [System.Environment]::GetEnvironmentVariable("BEEVIEW_DEPLOY_BUCKET", "Machine")
$prefix = [System.Environment]::GetEnvironmentVariable("BEEVIEW_ARTIFACT_PREFIX", "Machine")
$region = (Invoke-RestMethod -Headers @{ "X-aws-ec2-metadata-token" = (Invoke-RestMethod -Method PUT -Uri "http://169.254.169.254/latest/api/token" -Headers @{ "X-aws-ec2-metadata-token-ttl-seconds" = "60" }) } -Uri "http://169.254.169.254/latest/dynamic/instance-identity/document").region
New-Item -ItemType Directory -Force -Path $logDir, $staging | Out-Null
Start-Transcript -Path "$logDir\bootstrap_$(Get-Date -Format yyyyMMdd_HHmmss).log" -Append

$awsCli = @("C:\Program Files\Amazon\AWSCLIV2\aws.exe", "aws.exe") | Where-Object { Get-Command $_ -ErrorAction SilentlyContinue } | Select-Object -First 1
Import-Module AWSPowerShell -ErrorAction SilentlyContinue
if (-not $awsCli -and -not (Get-Command Read-S3Object -ErrorAction SilentlyContinue)) {
    throw "Neither AWS CLI v2 nor AWS Tools for PowerShell available on this image"
}

function Get-Artifact($key, $file) {
    Write-Host "downloading s3://$bucket/$prefix/$key"
    if ($awsCli) {
        & $awsCli s3 cp "s3://$bucket/$prefix/$key" $file --region $region --only-show-errors
        if ($LASTEXITCODE -ne 0) { throw "download of $key failed" }
    } else {
        Read-S3Object -BucketName $bucket -Key "$prefix/$key" -File $file -Region $region | Out-Null
    }
}

# ---------------------------------------------------------------- stop a running service
$taskName = "BeeViewServer"
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$root\BeeView-server\*" } | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
}

# ---------------------------------------------------------------- Python 3.11
$python = "C:\Program Files\Python311\python.exe"
if (-not (Test-Path $python)) {
    try { Get-Artifact "python-3.11-amd64.exe" "$staging\python-3.11-amd64.exe" }
    catch { Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -OutFile "$staging\python-3.11-amd64.exe" }
    $sig = Get-AuthenticodeSignature "$staging\python-3.11-amd64.exe"
    if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notlike "*Python Software Foundation*") { throw "Python installer signature invalid: $($sig.Status)" }
    Write-Host "installing Python 3.11"
    Start-Process -Wait -FilePath "$staging\python-3.11-amd64.exe" -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_launcher=0"
    if (-not (Test-Path $python)) { throw "Python installation failed" }
}

# ---------------------------------------------------------------- application archives
foreach ($name in @("xpollinator", "beeview-server", "data")) {
    Get-Artifact "$name.zip" "$staging\$name.zip"
}

# xPollinator: replace the tree but keep run/ (simulation results) across redeploys
$xp = "$root\xPollinator"
if (Test-Path "$xp\run") { Move-Item "$xp\run" "$root\xPollinator_run_keep" -Force }
if (Test-Path $xp) { Remove-Item $xp -Recurse -Force }
Expand-Archive "$staging\xpollinator.zip" -DestinationPath $root -Force
if (Test-Path "$root\xPollinator_run_keep") { Move-Item "$root\xPollinator_run_keep" "$xp\run" -Force } else { New-Item -ItemType Directory -Force -Path "$xp\run" | Out-Null }

# BeeView-server: replace code, keep data/ and venv/
$srv = "$root\BeeView-server"
$keepData = Test-Path "$srv\data\beeview.duckdb"
if ($keepData) { Move-Item "$srv\data" "$root\BeeView_data_keep" -Force }
if (Test-Path "$srv\venv") { Move-Item "$srv\venv" "$root\BeeView_venv_keep" -Force }
if (Test-Path $srv) { Remove-Item $srv -Recurse -Force }
Expand-Archive "$staging\beeview-server.zip" -DestinationPath $root -Force
if ($keepData) {
    Move-Item "$root\BeeView_data_keep" "$srv\data" -Force
} else {
    Expand-Archive "$staging\data.zip" -DestinationPath $srv -Force   # creates $srv\data
}
if (Test-Path "$root\BeeView_venv_keep") { Move-Item "$root\BeeView_venv_keep" "$srv\venv" -Force }

# ---------------------------------------------------------------- virtual environment
if (-not (Test-Path "$srv\venv\Scripts\python.exe")) {
    & $python -m venv "$srv\venv"
}
& "$srv\venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& "$srv\venv\Scripts\python.exe" -m pip install --quiet -r "$srv\requirements.txt"

# ---------------------------------------------------------------- environment
[System.Environment]::SetEnvironmentVariable("XPOLLINATOR_PATH", $xp, "Machine")
$env:XPOLLINATOR_PATH = $xp

# Windows firewall: the security group already restricts the source to the ALB.
if (-not (Get-NetFirewallRule -DisplayName "BeeView 32000" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "BeeView 32000" -Direction Inbound -Protocol TCP -LocalPort 32000 -Action Allow | Out-Null
}

# ---------------------------------------------------------------- service as scheduled task (SYSTEM, at startup)
$runner = "$root\run-beeview.cmd"
@"
@echo off
cd /d $srv
set XPOLLINATOR_PATH=$xp
"$srv\venv\Scripts\python.exe" main.py >> "$logDir\beeview-server.log" 2>&1
"@ | Set-Content -Path $runner -Encoding ASCII

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
    try { $ok = (Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:32000/api/runs" -TimeoutSec 5).StatusCode -eq 200 } catch { }
}
Write-Host ("BeeView-server healthy: {0}" -f $ok)
Stop-Transcript
if (-not $ok) { exit 1 }
