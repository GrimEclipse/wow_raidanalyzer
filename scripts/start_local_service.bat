@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_local_service.ps1"
if errorlevel 1 pause
