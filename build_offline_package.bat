@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_offline_package.ps1"
if errorlevel 1 (
    echo Offline package build failed.
    pause
    exit /b 1
)
echo Offline package build complete.
pause
