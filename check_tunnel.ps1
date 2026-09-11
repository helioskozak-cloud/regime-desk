# check_tunnel.ps1  -  is the published tunnel actually answering?
#
# THE FAILURE THIS EXISTS FOR. On 2026-09-09 the tunnel published a URL, and at
# some point after that the tunnel died while cloudflared stayed running. The
# process was alive, the endpoint file looked current, every task read "Running"
#  -  and the hosted finvisible could not reach the signal API for most of a day.
# Nothing in the setup could tell the difference between a working tunnel and a
# dead one, because everything it checked was on this machine.
#
# So this checks the only thing that matters: whether the URL the DASHBOARD
# reads actually answers. If it does not, the tunnel is restarted and a fresh
# URL published.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File check_tunnel.ps1
#   powershell ... -File check_tunnel.ps1 -WhatIf     (report, change nothing)

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [int]$TimeoutSec = 25,
    [string]$TaskName = 'Regime Desk Tunnel'
)

$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$endpointFile = Join-Path $repo 'docs\api_endpoint.json'
$log = Join-Path $repo 'tunnel_health.log'

function Write-Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Write-Output $line
    Add-Content -Path $log -Value $line -Encoding utf8
}

if (-not (Test-Path $endpointFile)) {
    Write-Log "FAIL  no endpoint file at $endpointFile"
    exit 2
}

$url = (Get-Content $endpointFile -Raw | ConvertFrom-Json).url
if (-not $url) {
    Write-Log "FAIL  endpoint file carries no url"
    exit 2
}

# THE PUBLISHED URL, NOT LOCALHOST. Pinging 127.0.0.1 would have passed happily
# through the entire outage  -  the API was never the thing that was broken.
$ok = $false
try {
    $r = Invoke-WebRequest -Uri "$url/api/ping" -UseBasicParsing -TimeoutSec $TimeoutSec
    $ok = ($r.StatusCode -eq 200)
} catch {
    $ok = $false
}

if ($ok) {
    Write-Log "ok    $url answering"
    exit 0
}

Write-Log "DEAD  $url did not answer in ${TimeoutSec}s"

if (-not $PSCmdlet.ShouldProcess($TaskName, 'restart the tunnel')) {
    Write-Log "skip  -WhatIf given, leaving it alone"
    exit 1
}

# Stop the task AND any orphaned cloudflared. The process outliving its tunnel
# is exactly the state that caused the outage, so restarting the task alone is
# not enough  -  a stale process would keep the port and the new one would not
# take over.
try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue } catch {}
Get-Process cloudflared -ErrorAction SilentlyContinue | ForEach-Object {
    try { Stop-Process -Id $_.Id -Force -ErrorAction Stop; Write-Log "kill  cloudflared pid $($_.Id)" } catch {}
}
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName $TaskName
Write-Log "restart  $TaskName started, waiting for a new URL"

# A quick tunnel takes a few seconds to publish and rather longer to become
# routable  -  the first check after a restart failed for that reason alone, and
# treating that as a second failure would restart it forever.
$deadline = (Get-Date).AddSeconds(90)
$new = $null
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 8
    try { $candidate = (Get-Content $endpointFile -Raw | ConvertFrom-Json).url } catch { continue }
    if (-not $candidate -or $candidate -eq $url) { continue }
    try {
        $r = Invoke-WebRequest -Uri "$candidate/api/ping" -UseBasicParsing -TimeoutSec 15
        if ($r.StatusCode -eq 200) { $new = $candidate; break }
    } catch { }
}

if ($new) {
    Write-Log "fixed  $new answering"
    exit 0
}
Write-Log "FAIL  restarted but no working tunnel within 90s  -  needs a look"
exit 3
