@echo off
REM Regime Desk — Local API Server
REM
REM Starts a local HTTP server on localhost:7534 that computes ticker signals
REM on demand.  Keep this window open while using the dashboard.
REM
REM The dashboard detects this server automatically and will instantly compute
REM signals for any ticker you pin that is not already in the snapshot.
REM Results are also written to data\watchlist.txt and data\ticker_cache.json
REM so the next scheduled build keeps them permanently.
REM
REM Run once per session (or add to Windows startup).

cd /d %~dp0
echo.
echo ================================================
echo  Regime Desk — Local Signal API
echo ================================================
echo.
if exist build\__pycache__ (
    echo Clearing Python cache...
    rmdir /s /q build\__pycache__
)
python build\local_api.py
echo.
pause
