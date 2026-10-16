$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$localUrl = 'http://127.0.0.1:8765/'

function Test-AnalyzerReady {
    try {
        $page = Invoke-WebRequest -Uri $localUrl -UseBasicParsing -TimeoutSec 2
        return $page.StatusCode -eq 200 -and $page.Content -match '/frontend/assets/theme/favicon.png'
    } catch {
        return $false
    }
}

try {
    if (-not (Test-AnalyzerReady)) {
        $listener = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
        if ($listener) {
            throw 'Port 8765 is occupied by another service. Close that service and try again.'
        }
        $runtimeDir = Join-Path $projectRoot 'data/local-service'
        New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
        $venvPython = Join-Path $projectRoot '.venv/Scripts/python.exe'
        if (Test-Path -LiteralPath $venvPython) {
            $pythonCommand = $venvPython
            $serverArgs = @('server.py', '--host', '127.0.0.1', '--port', '8765')
        } else {
            $pythonCommand = (Get-Command py.exe -ErrorAction Stop).Source
            $serverArgs = @('-3.9', 'server.py', '--host', '127.0.0.1', '--port', '8765')
        }
        Start-Process -FilePath $pythonCommand -ArgumentList $serverArgs -WorkingDirectory $projectRoot -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $runtimeDir 'server.stdout.log') `
            -RedirectStandardError (Join-Path $runtimeDir 'server.stderr.log') | Out-Null
        $deadline = [DateTime]::UtcNow.AddSeconds(30)
        while (-not (Test-AnalyzerReady)) {
            if ([DateTime]::UtcNow -ge $deadline) {
                throw "Server startup timed out. Check logs in $runtimeDir"
            }
            Start-Sleep -Milliseconds 250
        }
    }
    Start-Process $localUrl
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
