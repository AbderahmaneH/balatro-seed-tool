@echo off
cd /d "%~dp0"
where py >nul 2>nul && (py src\app.py) || (python src\app.py)
pause
