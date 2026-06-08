@echo off
REM Regime Desk — Local API Server
REM
REM Starts api_server.py on localhost:7534. Keep this window open while
REM using the dashboard. The dashboard auto-detects the server and uses it
REM to compute signals for tickers that aren't in today's snapshot.
REM
REM Run once per session, or install it as a Windows scheduled task with
REM install_local_api_task.ps1 so it auto-starts at logon.

cd /d %~dp0
set PORT=7534

echo.
echo ================================================
echo  Regime Desk - Local Signal API (port 7534)
echo ================================================
echo.

python api_server.py
echo.
pause
