@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel% equ 0 (
    python server.py --open
    exit /b %errorlevel%
)

where py >nul 2>nul
if %errorlevel% equ 0 (
    py server.py --open
    exit /b %errorlevel%
)

echo Python was not found. Please run server.py from your configured Python environment.
pause
exit /b 1
