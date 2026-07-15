@echo off
cd /d "%~dp0"
if exist "dist\wow_raidanalyzer_offline\RaidAnalyzer.exe" (
  start "" "%~dp0dist\wow_raidanalyzer_offline\RaidAnalyzer.exe"
) else if exist "RaidAnalyzer.exe" (
  start "" "%~dp0RaidAnalyzer.exe"
) else (
  echo Please run build_offline_package.bat first.
  pause
)
