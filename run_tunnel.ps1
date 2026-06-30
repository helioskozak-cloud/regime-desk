# run_tunnel.ps1 - orchestrates Cloudflare quick-tunnel for the local API.
#
# What it does:
#   1. Starts cloudflared as a quick tunnel pointed at http://localhost:7534
#   2. Watches cloudflared's stderr for the https://*.trycloudflare.com URL
#   3. Writes the URL to docs/data/api_endpoint.json
#   4. git add/commit/push so the deployed dashboard picks it up
#   5. Keeps cloudflared running. If it dies, this script exits - the
#      scheduled task's restart-on-failure brings it back inside a minute.
#
# Quick tunnels get a NEW URL on every restart, which is why we publish to
# git on each launch. The dashboard reads docs/data/api_endpoint.json on
# load to find the current URL.

$ErrorActionPreference = 'Continue'
$repo         = Split-Path -Parent $MyInvocation.MyCommand.Path
$cf           = Join-Path $repo 'cloudflared.exe'
$endpointFile = Join-Path $repo 'docs\api_endpoint.json'
$logDir       = Join-Path $repo 'tunnel_logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logOut       = Join-Path $logDir 'tunnel.out'
$logErr       = Join-Path $logDir 'tunnel.err'

Set-Location $repo

# Clean previous logs so we only match the URL from the current session
foreach ($f in @($logOut, $logErr)) {
    if (Test-Path $f) { Remove-Item $f -Force }
}

Write-Host "[tunnel] launching cloudflared..." -ForegroundColor Cyan
$proc = Start-Process -FilePath $cf `
    -ArgumentList 'tunnel','--url','http://localhost:7534','--no-autoupdate','--protocol','http2' `
    -NoNewWindow -PassThru `
    -RedirectStandardOutput $logOut `
    -RedirectStandardError  $logErr

# Cloudflared prints the trycloudflare.com URL to stderr within ~3-10 seconds.
# Watch both streams just in case future versions move it.
$tunnelUrl = $null
$deadline  = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline -and -not $tunnelUrl) {
    Start-Sleep -Milliseconds 500
    foreach ($f in @($logErr, $logOut)) {
        if (-not (Test-Path $f)) { continue }
        $content = Get-Content $f -Raw -ErrorAction SilentlyContinue
        # Fast-fail: cloudflared couldn't even reach trycloudflare.com (DNS/network down)
        if ($content -match 'failed to request quick Tunnel') {
            Write-Host "[tunnel] cloudflared failed to request tunnel (network not ready?) — exiting" -ForegroundColor Red
            try { Stop-Process -Id $proc.Id -Force -ErrorAction Stop } catch {}
            exit 1
        }
        # Require a hyphenated subdomain — real quick-tunnel URLs always look like
        # abc-def-ghi.trycloudflare.com; this excludes api.trycloudflare.com which
        # appears in cloudflared's own error messages and caused false matches.
        if ($content -match 'https://([a-z0-9]+-[a-z0-9-]+\.trycloudflare\.com)') {
            $tunnelUrl = "https://$($matches[1])"
            break
        }
    }
}

if (-not $tunnelUrl) {
    Write-Host "[tunnel] FAILED to capture URL within 60s" -ForegroundColor Red
    try { Stop-Process -Id $proc.Id -Force -ErrorAction Stop } catch {}
    exit 1
}

Write-Host "[tunnel] URL: $tunnelUrl" -ForegroundColor Green

# Only commit if the URL changed — the timestamp alone isn't worth a commit.
$prevUrl = ""
if (Test-Path $endpointFile) {
    try {
        $prev = Get-Content $endpointFile -Raw | ConvertFrom-Json
        $prevUrl = $prev.url
    } catch {}
}

# Write the endpoint file (UTF-8, no BOM)
$payload = @{
    url       = $tunnelUrl
    generated = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
} | ConvertTo-Json -Compress
[System.IO.File]::WriteAllText($endpointFile, $payload + "`n",
    (New-Object System.Text.UTF8Encoding($false)))

if ($tunnelUrl -ne $prevUrl) {
    Write-Host "[tunnel] URL changed ($prevUrl -> $tunnelUrl) — publishing to git..." -ForegroundColor Cyan
    git add docs/api_endpoint.json 2>&1 | Out-Null
    git commit -m "ops: update api tunnel endpoint" 2>&1 | Out-Null
    git push 2>&1 | Out-Null
} else {
    Write-Host "[tunnel] URL unchanged — skipping git commit." -ForegroundColor DarkGray
}

Write-Host "[tunnel] cloudflared running with PID $($proc.Id). watchdog starting." -ForegroundColor Green

# ─────────────────────────────────────────────────────────────────────────────
# Watchdog: probe the published tunnel URL every 5 minutes. Quick tunnels
# can internally roll their URL without cloudflared exiting, leaving the
# published URL dead while the process still appears healthy. On two
# consecutive failures, kill cloudflared so the scheduled task's
# restart-on-failure brings us back fresh - run_tunnel.ps1 then captures
# the new URL and publishes it.
$probeIntervalSec = 300   # 5 minutes
$failThreshold    = 2     # consecutive failures before restarting
$failCount        = 0
$probeUrl         = "$tunnelUrl/api/ping"

while ($true) {
    Start-Sleep -Seconds $probeIntervalSec

    if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) {
        Write-Host "[tunnel] cloudflared exited; script done." -ForegroundColor Yellow
        exit 0
    }

    $ok = $false
    try {
        $r = Invoke-WebRequest -Uri $probeUrl -TimeoutSec 8 -UseBasicParsing
        if ($r.StatusCode -eq 200) { $ok = $true }
    } catch { }

    if ($ok) {
        if ($failCount -gt 0) {
            Write-Host "[tunnel] probe recovered after $failCount failure(s)" -ForegroundColor Green
        }
        $failCount = 0
        continue
    }

    $failCount++
    Write-Host "[tunnel] probe failure #$failCount on $probeUrl" -ForegroundColor Yellow
    if ($failCount -ge $failThreshold) {
        Write-Host "[tunnel] $failCount consecutive failures - killing cloudflared to force fresh URL" -ForegroundColor Red
        try { Stop-Process -Id $proc.Id -Force -ErrorAction Stop } catch {}
        exit 1
    }
}
