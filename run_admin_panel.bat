@echo off
rem ── پنل مدیریت Legal-Automation ── (پورت پیش‌فرض 8300؛ 3000 و 3100 آزاد می‌مانند)
cd /d C:\apps\Legal-Automation
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist logs mkdir logs
:loop
.venv\Scripts\python.exe -m legal_admin >> logs\admin_panel.log 2>&1
timeout /t 10 /nobreak >nul
goto loop
