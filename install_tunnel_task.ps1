# install_tunnel_task.ps1
# Registers a Windows scheduled task that runs run_tunnel.ps1 at logon and
# restarts it if it dies. Pairs with the existing 'Regime Desk Local API'
# task; together they keep both the local API server AND the public
# cloudflare tunnel up across reboots/sleep.

$ErrorActionPreference = "Stop"

$TaskName = "Regime Desk Tunnel"
$RepoDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script   = Join-Path $RepoDir "run_tunnel.ps1"

if (-not (Test-Path $Script)) {
    Write-Host "ERROR: $Script not found." -ForegroundColor Red
    exit 1
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$Action = New-ScheduledTaskAction `
    -Execute  "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Script`"" `
    -WorkingDirectory $RepoDir

$CurrentUser = "$env:USERDOMAIN\$env:USERNAME"
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $CurrentUser

# Wait a little after logon so the local API (which has its own task) has time
# to start. Quick tunnels grab the URL fast; no point binding it to a dead
# upstream.
$Trigger.Delay = 'PT30S'

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 99 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew

$Principal = New-ScheduledTaskPrincipal `
    -UserId $CurrentUser `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName  $TaskName `
    -Action    $Action `
    -Trigger   $Trigger `
    -Settings  $Settings `
    -Principal $Principal `
    -Description "Cloudflare quick-tunnel exposing localhost:7534 to the public dashboard. Auto-publishes URL to docs/api_endpoint.json on each launch."

Start-ScheduledTask -TaskName $TaskName

Write-Host ""
Write-Host "Task '$TaskName' registered and started." -ForegroundColor Green
Write-Host "Watch the publish: 'gh run list' or check docs/api_endpoint.json a few seconds from now."
