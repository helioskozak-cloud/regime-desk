@echo off
REM Daily question analysis — reads data\question_log.json and suggests
REM new dashboard features based on advisor question patterns.
REM
REM Suggestions go to data\suggestions\YYYY-MM-DD.md for your review.
REM They are NOT automatically added to wishlist.md.
REM Copy any approved items into wishlist.md under ## Pending.
REM
REM Before running:
REM   1. Open the Regime Desk dashboard → Ask ✦ tab
REM   2. Click "Download JSON" in the Daily Question Log card
REM   3. Save the file to:  regime-desk\data\question_log.json

cd /d %~dp0
if not exist "data\suggestions" mkdir "data\suggestions"
echo.
echo ================================================
echo  Regime Desk — Daily Question Analysis
echo ================================================
echo.
python build\daily_suggestions.py
echo.
echo Review the suggestions file in data\suggestions\
echo Copy approved items into wishlist.md under ## Pending
echo.
pause
