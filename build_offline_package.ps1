$ErrorActionPreference = "Stop"

$root = [IO.Path]::GetFullPath($PSScriptRoot)
$dist = [IO.Path]::GetFullPath((Join-Path $root "dist"))
$target = [IO.Path]::GetFullPath((Join-Path $dist "wow_raidanalyzer_offline"))
$zip = [IO.Path]::GetFullPath((Join-Path $dist "wow_raidanalyzer_offline.zip"))

if (-not $target.StartsWith($dist + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to build outside the dist directory: $target"
}

New-Item -ItemType Directory -Force -Path $dist | Out-Null
if (Test-Path -LiteralPath $target) {
    try {
        Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction Stop
    } catch {
        Write-Warning "Cannot wipe $target (in use). Syncing files into existing folder instead."
    }
}
New-Item -ItemType Directory -Force -Path $target | Out-Null

$files = @(
    "offline_index.html", "report.html", "verdict.html", "verdict_data.json", "crown-fight-audit.html",
    "boss_catalog.json", "offline_server.py", "start_offline.bat", "README_OFFLINE.txt"
)
if (Test-Path -LiteralPath (Join-Path $root "wcl_hardcore_api.json")) { $files += "wcl_hardcore_api.json" }
foreach ($file in $files) {
    $src = Join-Path $root $file
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $target $file) -Force
    }
}
Move-Item -LiteralPath (Join-Path $target "offline_index.html") -Destination (Join-Path $target "index.html") -Force

Copy-Item -LiteralPath (Join-Path $root "assets") -Destination (Join-Path $target "assets") -Recurse -Force
New-Item -ItemType Directory -Force -Path (Join-Path $target "boss_plugins") | Out-Null
Copy-Item -LiteralPath (Join-Path $root "boss_plugins\assets") -Destination (Join-Path $target "boss_plugins\assets") -Recurse -Force
New-Item -ItemType Directory -Force -Path (Join-Path $target "verdicts") | Out-Null
Set-Content -LiteralPath (Join-Path $target "verdicts\.gitkeep") -Value "" -Encoding utf8
if (Test-Path -LiteralPath (Join-Path $root "verdicts")) {
    Get-ChildItem -LiteralPath (Join-Path $root "verdicts") -Filter "verdict-*.json" -ErrorAction SilentlyContinue |
        ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $target "verdicts\$($_.Name)") -Force }
}

# Copy data/ wcl_*.json + manifest for multi-log switching offline.
New-Item -ItemType Directory -Force -Path (Join-Path $target "data") | Out-Null
Set-Content -LiteralPath (Join-Path $target "data\.gitkeep") -Value "" -Encoding utf8
if (Test-Path -LiteralPath (Join-Path $root "data")) {
    Get-ChildItem -LiteralPath (Join-Path $root "data") -Filter "wcl_*.json" -ErrorAction SilentlyContinue |
        ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $target "data\$($_.Name)") -Force }
    $manifestSrc = Join-Path $root "data\manifest.json"
    if (Test-Path -LiteralPath $manifestSrc) {
        Copy-Item -LiteralPath $manifestSrc -Destination (Join-Path $target "data\manifest.json") -Force
    }
}

# Also ship analyzer_core/wcl_paths.py so offline_server can list data files when Python exists.
New-Item -ItemType Directory -Force -Path (Join-Path $target "analyzer_core") | Out-Null
Set-Content -LiteralPath (Join-Path $target "analyzer_core\__init__.py") -Value "" -Encoding utf8
$wclPaths = Join-Path $root "analyzer_core\wcl_paths.py"
if (Test-Path -LiteralPath $wclPaths) {
    Copy-Item -LiteralPath $wclPaths -Destination (Join-Path $target "analyzer_core\wcl_paths.py") -Force
}

# Bake ALL data/*.json (+ legacy root) into a source map for file:// switching.
New-Item -ItemType Directory -Force -Path (Join-Path $root "tmp") | Out-Null
$bakeScript = Join-Path $root "tmp\_bake_offline_data.py"
@(
    '# -*- coding: utf-8 -*-'
    '"""Bake all WCL JSON files into vendor JS for file:// multi-source load. Author: Wei."""'
    'from pathlib import Path'
    'import json'
    'import sys'
    ''
    'target = Path(sys.argv[1])'
    'root = Path(sys.argv[2])'
    'vendor = target / "assets" / "vendor"'
    'vendor.mkdir(parents=True, exist_ok=True)'
    ''
    'def web_key(path: Path) -> str:'
    '    try:'
    '        return path.resolve().relative_to(root.resolve()).as_posix()'
    '    except ValueError:'
    '        return path.name'
    ''
    'candidates = []'
    'legacy = root / "wcl_hardcore_api.json"'
    'if legacy.is_file():'
    '    candidates.append(legacy)'
    'data_dir = root / "data"'
    'if data_dir.is_dir():'
    '    candidates.extend(sorted(data_dir.glob("wcl_*.json"), key=lambda p: p.stat().st_mtime, reverse=True))'
    ''
    'source_map = {}'
    'for path in candidates:'
    '    raw = path.read_text(encoding="utf-8-sig")'
    '    json.loads(raw)  # validate'
    '    source_map[web_key(path)] = json.loads(raw)'
    '    print("bake candidate:", web_key(path), path.stat().st_size, "bytes")'
    ''
    'parts = ['
    '    "// Auto-baked by build_offline_package.ps1",'
    '    "// Prefer window.__WCL_DATA_BY_SOURCE__[path]; fall back to __WCL_HARDCORE_DATA__.",'
    ']'
    'if source_map:'
    '    parts.append("window.__WCL_DATA_BY_SOURCE__ = " + json.dumps(source_map, ensure_ascii=False) + ";")'
    '    primary_key = next(iter(source_map))'
    '    if "wcl_hardcore_api.json" in source_map:'
    '        primary_key = "wcl_hardcore_api.json"'
    '    parts.append("window.__WCL_HARDCORE_DATA__ = window.__WCL_DATA_BY_SOURCE__[" + json.dumps(primary_key) + "];")'
    '    parts.append("window.__OFFLINE_DATA__ = window.__WCL_HARDCORE_DATA__;")'
    '    print("baked", len(source_map), "sources; primary =", primary_key)'
    'else:'
    '    parts.append("// No wcl_*.json found at build time.")'
    '    print("WARNING: no wcl json files to bake")'
    ''
    'verdict = root / "verdict_data.json"'
    'if verdict.exists():'
    '    raw = verdict.read_text(encoding="utf-8-sig")'
    '    json.loads(raw)'
    '    parts.append("window.__VERDICT_DATA__ = " + raw + ";")'
    '    print("baked verdict_data.json ->", verdict.stat().st_size, "bytes")'
    ''
    '# Refresh packaged manifest from baked keys.'
    'manifest = {'
    '    "schemaVersion": 1,'
    '    "files": ['
    '        {"path": key, "name": key.split("/")[-1], "label": key, "size": 0, "mtime": 0}'
    '        for key in source_map'
    '    ],'
    '}'
    'data_out = target / "data"'
    'data_out.mkdir(parents=True, exist_ok=True)'
    '(data_out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")'
    ''
    'out = vendor / "wcl_hardcore_api.js"'
    'out.write_text("\n".join(parts) + "\n", encoding="utf-8")'
    'print("wrote", out, "size", out.stat().st_size)'
) | Set-Content -LiteralPath $bakeScript -Encoding utf8

$baked = $false
$pyCmds = @(
    @{ Exe = "py"; Args = @("-3", $bakeScript, $target, $root) },
    @{ Exe = "python"; Args = @($bakeScript, $target, $root) }
)
foreach ($cmd in $pyCmds) {
    $exe = Get-Command $cmd.Exe -ErrorAction SilentlyContinue
    if (-not $exe) { continue }
    & $cmd.Exe @($cmd.Args)
    if ($LASTEXITCODE -eq 0) {
        $baked = $true
        break
    }
}
if (-not $baked) {
    Write-Warning "Python unavailable - writing empty bake stub."
    $stubPath = Join-Path $target "assets\vendor\wcl_hardcore_api.js"
    New-Item -ItemType Directory -Force -Path (Split-Path $stubPath) | Out-Null
    Set-Content -LiteralPath $stubPath -Value "// Auto-baked stub. Rebuild with Python to embed JSON." -Encoding utf8
}

# Zip via temp file + .NET ZipFile to avoid Compress-Archive Dispose failures when
# Defender/indexer memory-maps the fresh ~12MB baked JS or an existing .zip handle.
Add-Type -AssemblyName System.IO.Compression.FileSystem
function Remove-PathWithRetry {
    param([string]$Path, [int]$Attempts = 8, [int]$DelayMs = 400)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            Remove-Item -LiteralPath $Path -Force -Recurse -ErrorAction Stop
            return
        } catch {
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
        [System.IO.Compression.ZipFile]::CreateFromDirectory(
            $target,
            $zipTmp,
            [System.IO.Compression.CompressionLevel]::Optimal,
            $false
        )
        Move-Item -LiteralPath $zipTmp -Destination $zip -Force
        $zipOk = $true
        break
    } catch {
        $lastErr = $_
        Write-Warning ("Zip attempt {0}/6 failed: {1}" -f $attempt, $_.Exception.Message)
        Start-Sleep -Milliseconds (500 * $attempt)
        try { if (Test-Path -LiteralPath $zipTmp) { Remove-Item -LiteralPath $zipTmp -Force -ErrorAction SilentlyContinue } } catch {}
    }
}
if (-not $zipOk) {
    throw "Failed to create offline zip after retries: $lastErr"
}
Write-Host "Offline package created: $zip"
