# setup_scheduled_tasks.ps1 - (re)create the self-healing scheduled tasks for the
# local signal API and the Cloudflare tunnel. Run ONCE, ELEVATED:
#   Right-click PowerShell -> "Run as administrator", then:
#   powershell -ExecutionPolicy Bypass -File C:\Portfolizer\regime-desk\setup_scheduled_tasks.ps1
#
# Both tasks start AT LOGON and RESTART ON FAILURE every minute (indefinitely),
# which is what makes the tunnel survive a transient Cloudflare outage without
# anyone noticing. MultipleInstances=IgnoreNew so a logon never stacks a second
# copy on one already running.

$ErrorActionPreference = 'Stop'
$repo = "C:\Portfolizer\regime-desk"

# Must be elevated - creating tasks in the Task Scheduler root needs admin.
$admin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "NOT elevated. Re-run this from an admin PowerShell (Run as administrator)." -ForegroundColor Red
    exit 1
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$trigger   = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

$apiAction = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument "/c `"$repo\run_local_api.bat`"" -WorkingDirectory $repo
Register-ScheduledTask -TaskName "RegimeDesk-SignalAPI" -Action $apiAction `
    -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "[ok] RegimeDesk-SignalAPI registered" -ForegroundColor Green

$tunAction = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$repo\run_tunnel.ps1`"" `
    -WorkingDirectory $repo
Register-ScheduledTask -TaskName "RegimeDesk-SignalTunnel" -Action $tunAction `
    -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "[ok] RegimeDesk-SignalTunnel registered" -ForegroundColor Green

Get-ScheduledTask -TaskName "RegimeDesk-Signal*" | Select-Object TaskName, State | Format-Table -AutoSize

# Take over the running session cleanly (idempotent):
Write-Host "`nHanding the live session over to the tasks..." -ForegroundColor Cyan

# Tunnel: stop any cloudflared / stray run_tunnel.ps1 first, so the task's copy
# is the only one publishing a URL, then start the task.
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -like '*run_tunnel.ps1*' -and $_.ProcessId -ne $PID } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-ScheduledTask -TaskName "RegimeDesk-SignalTunnel"
Write-Host "[ok] tunnel task started (fresh URL will publish in a few seconds)" -ForegroundColor Green

# API: only start the task copy if nothing is already listening on 7534, so we
# don't collide with an API you started manually. It's task-managed at next logon.
$apiUp = $false
try { $apiUp = (New-Object Net.Sockets.TcpClient).ConnectAsync('127.0.0.1',7534).Wait(800) } catch {}
if (-not $apiUp) {
    Start-ScheduledTask -TaskName "RegimeDesk-SignalAPI"
    Write-Host "[ok] API task started" -ForegroundColor Green
} else {
    Write-Host "[skip] API already listening on 7534 - left as-is; task manages it next logon." -ForegroundColor DarkGray
}
Write-Host "`nDone. API + tunnel now self-start at every logon and self-heal on failure." -ForegroundColor Green
