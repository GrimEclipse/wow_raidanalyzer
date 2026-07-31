$ErrorActionPreference = "Stop"

# 离线包打包脚本：把场面复盘 / 开庭 / 记事本前端与宿主编译进 dist\
# 用法：
#   .\build_offline_package.ps1
#   或双击 build_offline_package.bat
#
# 产出：
#   dist\wow_raidanalyzer_offline\     可分发目录
#   dist\wow_raidanalyzer_offline.zip  压缩包

$root = [IO.Path]::GetFullPath($PSScriptRoot)
$dist = [IO.Path]::GetFullPath((Join-Path $root "dist"))
$target = [IO.Path]::GetFullPath((Join-Path $dist "wow_raidanalyzer_offline"))
$zip = [IO.Path]::GetFullPath((Join-Path $dist "wow_raidanalyzer_offline.zip"))
$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"

if (-not $target.StartsWith($dist + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to build outside the dist directory: $target"
}

Write-Host "Root : $root"
Write-Host "Dist : $dist"
Write-Host "Out  : $target"

New-Item -ItemType Directory -Force -Path $dist | Out-Null
if (Test-Path -LiteralPath $target) {
    try { Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction Stop }
    catch { Write-Warning "Cannot wipe $target (in use). Syncing into existing folder." }
}
New-Item -ItemType Directory -Force -Path $target | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $target "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $target "scoreboard") | Out-Null

# —— 前端与入口页 ——
$files = @(
    "index.html",
    "boss_catalog.json",
    "README_OFFLINE.txt"
)
foreach ($file in $files) {
    $src = Join-Path $root $file
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $target $file) -Force
        Write-Host "  + $file"
    } else {
        Write-Warning "Missing: $file"
    }
}

# —— 前端插件 / 独立工具 / 静态资源 ——
Copy-Item -LiteralPath (Join-Path $root "frontend") -Destination (Join-Path $target "frontend") -Recurse -Force
Write-Host "  + frontend\"
Copy-Item -LiteralPath (Join-Path $root "assets") -Destination (Join-Path $target "assets") -Recurse -Force
Write-Host "  + assets\"
New-Item -ItemType Directory -Force -Path (Join-Path $target "boss_plugins") | Out-Null
Copy-Item -LiteralPath (Join-Path $root "boss_plugins\assets") -Destination (Join-Path $target "boss_plugins\assets") -Recurse -Force
Write-Host "  + boss_plugins\assets\"

# —— 分析 JSON：复制 data\ 下全部 wcl_*.json（体积可能较大，按需再删）——
$dataSrc = Join-Path $root "data"
if (Test-Path -LiteralPath $dataSrc) {
    Get-ChildItem -LiteralPath $dataSrc -Filter "wcl_*.json" -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $target "data\$($_.Name)") -Force
        Write-Host "  + data\$($_.Name)"
    }
    $manifest = Join-Path $dataSrc "manifest.json"
    if (Test-Path -LiteralPath $manifest) {
        Copy-Item -LiteralPath $manifest -Destination (Join-Path $target "data\manifest.json") -Force
        Write-Host "  + data\manifest.json"
    }
}
# —— 终审 Excel：浏览器端 verdict-xlsx.js 已随 assets\ 复制；再附带 Python 导出器供本机有 Python+openpyxl 时由宿主调用 ——
# 注意：离线包本身不内嵌 openpyxl；最终用户无需安装 Python。openpyxl 仅本机 server.py / OfflineHost 调 Python 时需要。
New-Item -ItemType Directory -Force -Path (Join-Path $target "tools\templates") | Out-Null
foreach ($toolFile in @("tools\__init__.py", "tools\export_verdict_excel.py", "tools\templates\verdict_excel_style.xlsx")) {
    $src = Join-Path $root $toolFile
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $target $toolFile) -Force
        Write-Host "  + $toolFile"
    } else {
        Write-Warning "Missing: $toolFile"
    }
}

# —— 编译离线宿主（最终用户无需 Python）——
if (-not (Test-Path -LiteralPath $csc)) { throw "csc.exe not found: $csc" }
$hostCs = Join-Path $root "host\OfflineHost.cs"
$hostExe = Join-Path $target "RaidAnalyzer.exe"
& $csc /nologo /optimize+ /target:exe /out:$hostExe $hostCs
if ($LASTEXITCODE -ne 0) { throw "Failed to compile RaidAnalyzer.exe" }
Write-Host "Compiled RaidAnalyzer.exe"

@"
@echo off
cd /d "%~dp0"
title WoW Raid Analyzer Offline
echo Starting local host...
echo (若 8765 被占用会自动换端口；保持本窗口开启)
"%~dp0RaidAnalyzer.exe"
if errorlevel 1 (
  echo.
  echo 启动失败。若仍提示端口占用，可手动: RaidAnalyzer.exe --port 8877
  pause
)
"@ | Set-Content -LiteralPath (Join-Path $target "start.bat") -Encoding ASCII

@"
离线包使用说明（无需安装 Python / openpyxl）
==========================================

1. 解压后应得到外层文件夹 wow_raidanalyzer_offline\，再进入该目录使用。
2. 分析 JSON 已放入 data\（也可之后自行覆盖/追加）。
   命名建议：data/wcl_<reportId>_<bossKey>_<开荒日YYYYMMDD>.json
3. 双击 start.bat（或 RaidAnalyzer.exe）。
4. 浏览器会打开本地页面：
   - 首页：选择「场面复盘」或「智商记事本」
   - report：场面分析 / 开庭 / 终审（顶部可切换 data\ 多份日志）
   - scoreboard：日记式记事本（判定明细默认可收起）
5. 终审「导出 Excel」：优先走本机 API；若无 Python+openpyxl，
   浏览器会用 assets\vendor\verdict-xlsx.js 直接生成 .xlsx（无需额外依赖）。

计分板数据保存在 scoreboard\ 目录。
关闭 RaidAnalyzer.exe 黑窗口即停止服务。

若 8765 端口被占用：
  RaidAnalyzer.exe --port 8877
"@ | Set-Content -LiteralPath (Join-Path $target "README_OFFLINE.txt") -Encoding utf8

# —— Zip ——
Add-Type -AssemblyName System.IO.Compression.FileSystem
function Remove-PathWithRetry {
    param([string]$Path, [int]$Attempts = 8, [int]$DelayMs = 400)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    for ($i = 1; $i -le $Attempts; $i++) {
        try { Remove-Item -LiteralPath $Path -Force -Recurse -ErrorAction Stop; return }
        catch {
            if ($i -eq $Attempts) { throw }
            Start-Sleep -Milliseconds $DelayMs
        }
    }
}

Remove-PathWithRetry -Path $zip
$zipTmp = Join-Path $dist ("wow_raidanalyzer_offline.{0}.zip.tmp" -f [guid]::NewGuid().ToString("N"))
Remove-PathWithRetry -Path $zipTmp
$zipOk = $false
$lastErr = $null
for ($attempt = 1; $attempt -le 6; $attempt++) {
    try {
        if (Test-Path -LiteralPath $zipTmp) { Remove-Item -LiteralPath $zipTmp -Force -ErrorAction Stop }
        # includeBaseDirectory=$true → zip 内含外层文件夹 wow_raidanalyzer_offline\
        [System.IO.Compression.ZipFile]::CreateFromDirectory(
            $target, $zipTmp,
            [System.IO.Compression.CompressionLevel]::Optimal, $true
        )
        Move-Item -LiteralPath $zipTmp -Destination $zip -Force
        $zipOk = $true
        break
    } catch {
        $lastErr = $_
        Write-Warning ("Zip attempt {0}/6 failed: {1}" -f $attempt, $_.Exception.Message)
        Start-Sleep -Milliseconds (500 * $attempt)
    }
}
if (-not $zipOk) { throw "Failed to create offline zip: $lastErr" }
Write-Host ""
Write-Host "Offline package created:"
Write-Host "  Folder: $target"
Write-Host "  Zip   : $zip"
