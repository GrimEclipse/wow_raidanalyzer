param(
    [string]$Target = "D:\World of Warcraft\_retail_\Interface\AddOns\WCLMechanicMiner"
)

$ErrorActionPreference = "Stop"
$source = Join-Path $PSScriptRoot "WCLMechanicMiner"

if (-not (Test-Path -LiteralPath $source -PathType Container)) {
    throw "Addon source directory not found: $source"
}

New-Item -ItemType Directory -Path $Target -Force | Out-Null

foreach ($fileName in @("WCLMechanicMiner.toc", "WCLMechanicMiner.lua", "README.md")) {
    Copy-Item -LiteralPath (Join-Path $source $fileName) -Destination (Join-Path $Target $fileName) -Force
}

Write-Host "WCLMechanicMiner synced to $Target"
