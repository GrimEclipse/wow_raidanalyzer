@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo ========================================
echo  WoW Raid Analyzer 离线包
echo  编者：卫宇珩
echo ========================================
echo.

set "ENTRY=index.html"
if not exist "%ENTRY%" if exist "offline_index.html" set "ENTRY=offline_index.html"
if not exist "%ENTRY%" set "ENTRY=report.html"

set "BAKED=assets\vendor\wcl_hardcore_api.js"
set "HAS_BAKE=0"
if exist "%BAKED%" (
    findstr /C:"__WCL_DATA_BY_SOURCE__" "%BAKED%" >nul 2>nul
    if not errorlevel 1 set "HAS_BAKE=1"
    if "%HAS_BAKE%"=="0" (
        findstr /C:"__WCL_HARDCORE_DATA__" "%BAKED%" >nul 2>nul
        if not errorlevel 1 set "HAS_BAKE=1"
    )
)

if "%HAS_BAKE%"=="1" (
    echo [OK] 已内嵌复盘 JSON 完整映射，打开报告页可下拉切换多天日志。
) else (
    echo [注意] 未检测到内嵌复盘数据。
    echo         若没有 Python，请打开 HTML 后按提示手动选择 data\ 下的 JSON。
)
echo.

rem Prefer local HTTP when Python exists (optional). Browser opens via offline_server.py.
where py >nul 2>nul
if %errorlevel% equ 0 (
    echo 检测到 Python，启动本机静态服务 http://127.0.0.1:8765/ ...
    echo 关闭本窗口即停止服务。
    echo.
    py -3 offline_server.py
    exit /b %errorlevel%
)
where python >nul 2>nul
if %errorlevel% equ 0 (
    echo 检测到 Python，启动本机静态服务 http://127.0.0.1:8765/ ...
    echo 关闭本窗口即停止服务。
    echo.
    python offline_server.py
    exit /b %errorlevel%
)

echo 未找到 Python — 直接打开静态页面（依赖内嵌数据，无需服务器^）。
start "" "%ENTRY%"
if "%HAS_BAKE%"=="0" (
    echo.
    echo 若页面要求手动选 JSON：请选本目录 data\ 下的 wcl_*.json（或根目录兼容文件）。
    echo 重新运行 build_offline_package.bat 可把 data/ 全部日志完整映射烘焙进离线包。
)
echo.
pause
exit /b 0
