@echo off
REM Silent runner for Windows Task Scheduler — no pause, output logged to file.
REM Interactive use: run_daily.bat instead.
cd /d C:\Portfolizer\regime-desk
if not exist "data\suggestions" mkdir "data\suggestions"
C:\Users\Helios\AppData\Local\Programs\Python\Python314\python.exe build\daily_suggestions.py >> data\suggestions\scheduler.log 2>&1
