$ErrorActionPreference = "Stop"
$TaskName = "Regime Desk Tunnel"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop } catch {}
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed '$TaskName'." -ForegroundColor Green
} else {
    Write-Host "No task '$TaskName' registered." -ForegroundColor Yellow
}

Get-Process cloudflared -ErrorAction SilentlyContinue | ForEach-Object {
    try { Stop-Process -Id $_.Id -Force -ErrorAction Stop; Write-Host "Killed cloudflared PID $($_.Id)" } catch {}
}
