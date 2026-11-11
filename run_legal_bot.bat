@echo off
cd /d C:\apps\Legal-Automation
set PLAYWRIGHT_BROWSERS_PATH=C:\apps\Legal-Automation\browsers
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist logs mkdir logs
:loop
.venv\Scripts\python.exe bot_main.py >> logs\console.log 2>&1
timeout /t 10 /nobreak >nul
goto loop
