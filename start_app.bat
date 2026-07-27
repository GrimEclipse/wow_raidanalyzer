@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -c "import openpyxl" 1>nul 2>nul
    if errorlevel 1 (
        echo Installing openpyxl into .venv ...
        "%~dp0.venv\Scripts\python.exe" -m pip install "openpyxl>=3.1.0"
    )
    "%~dp0.venv\Scripts\python.exe" server.py --open
    exit /b %errorlevel%
)

where python >nul 2>nul
if %errorlevel% equ 0 (
    python server.py --open
    exit /b %errorlevel%
)

where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 server.py --open
    exit /b %errorlevel%
)

echo Python was not found. Please run server.py from your configured Python environment.
pause
exit /b 1
