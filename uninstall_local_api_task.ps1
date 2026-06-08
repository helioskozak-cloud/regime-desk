# uninstall_local_api_task.ps1
# Removes the "Regime Desk Local API" scheduled task and stops it if running.

$ErrorActionPreference = "Stop"

$TaskName = "Regime Desk Local API"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "No task named '$TaskName' is registered. Nothing to do." -ForegroundColor Yellow
    return
}

try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop } catch {}
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Removed '$TaskName'." -ForegroundColor Green

# Best-effort kill any pythonw still running the local_api.py script.
$apiProcs = Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq "pythonw.exe" -and $_.CommandLine -like "*local_api.py*" }
if ($apiProcs) {
    foreach ($p in $apiProcs) {
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch {}
    }
    Write-Host "Killed $($apiProcs.Count) lingering pythonw.exe process(es)." -ForegroundColor Green
}
