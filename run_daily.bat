@echo off
REM Daily question analysis — reads data\question_log.json and suggests
REM new dashboard features based on advisor question patterns.
REM
REM Before running:
REM   1. Open the Regime Desk dashboard → Ask ✦ tab
REM   2. Click "Download JSON" in the Daily Question Log card
REM   3. Save the file to:  regime-desk\data\question_log.json

cd /d %~dp0
echo.
echo ================================================
echo  Regime Desk — Daily Question Analysis
echo ================================================
echo.
python build\daily_suggestions.py
echo.
echo Done. Check wishlist.md for new Pending items.
echo.
pause
