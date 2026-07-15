@echo off
cd /d "%~dp0"
echo Building offline package into dist\wow_raidanalyzer_offline\ ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_offline_package.ps1"
if errorlevel 1 (
  echo.
  echo Build FAILED.
  pause
  exit /b 1
)
echo.
echo Done. See dist\wow_raidanalyzer_offline\ and dist\wow_raidanalyzer_offline.zip
pause
