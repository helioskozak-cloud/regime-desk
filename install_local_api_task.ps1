# install_local_api_task.ps1
# Registers a Windows Scheduled Task that auto-starts the regime-desk
# local API at user logon and restarts it if it stops. Runs as the
# current user (no admin required). To remove, run uninstall_local_api_task.ps1.
#
# Usage (in PowerShell, from this folder):
#   .\install_local_api_task.ps1
# If you see "running scripts is disabled on this system", run this once
# in the same shell first:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

$ErrorActionPreference = "Stop"

$TaskName    = "Regime Desk Local API"
$RepoDir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script      = Join-Path $RepoDir "build\local_api.py"
$LogFile     = Join-Path $RepoDir "local_api_task.log"

# ── Locate pythonw.exe (suppresses console window) ───────────────────────────
$PyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $PyCmd) {
    Write-Host "ERROR: python.exe not on PATH. Install Python first, or edit `$PythonW below." -ForegroundColor Red
    exit 1
}
$PythonW = Join-Path (Split-Path -Parent $PyCmd.Source) "pythonw.exe"
if (-not (Test-Path $PythonW)) {
    Write-Host "ERROR: pythonw.exe not found at $PythonW" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $Script)) {
    Write-Host "ERROR: $Script not found." -ForegroundColor Red
    exit 1
}

Write-Host "Will register task:" -ForegroundColor Cyan
Write-Host "  Name        : $TaskName"
Write-Host "  Script      : $Script"
Write-Host "  Working dir : $RepoDir"
Write-Host "  pythonw.exe : $PythonW"
Write-Host "  Log file    : $LogFile"
Write-Host ""

# ── Remove any existing instance so re-running this script is idempotent ────
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task with same name..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# ── Action: run pythonw with the local_api.py script ────────────────────────
# Note: pythonw.exe has no stdout — we let local_api.py write its own
# console logs into local_api_task.log via Python's logging or print to a
# file. If the script crashes, the task restart logic catches it.
$Action = New-ScheduledTaskAction `
    -Execute  $PythonW `
    -Argument "`"$Script`"" `
    -WorkingDirectory $RepoDir

# ── Trigger: at the current user's logon ─────────────────────────────────────
$CurrentUser = "$env:USERDOMAIN\$env:USERNAME"
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser

# ── Settings: restart on failure, run on battery, no time limit ──────────────
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 99 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew

# ── Principal: run as current user, no admin ─────────────────────────────────
$Principal = New-ScheduledTaskPrincipal `
    -UserId $CurrentUser `
    -LogonType Interactive `
    -RunLevel Limited

# ── Register and immediately start ───────────────────────────────────────────
Register-ScheduledTask `
    -TaskName  $TaskName `
    -Action    $Action `
    -Trigger   $Trigger `
    -Settings  $Settings `
    -Principal $Principal `
    -Description "Auto-starts the regime-desk local signal API on localhost:7534. Restarts if it stops."

Start-ScheduledTask -TaskName $TaskName

Write-Host ""
Write-Host "Task registered and started." -ForegroundColor Green
Write-Host ""
Write-Host "Verify with:"
Write-Host "  Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host "  curl http://localhost:7534/health"
Write-Host ""
Write-Host "Open Task Scheduler (taskschd.msc) to inspect / modify; the task is"
Write-Host "under Task Scheduler Library at the root."
