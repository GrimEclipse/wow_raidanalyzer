param(
    [string]$BaseUrl = "http://localhost:5000",
    [string]$Build = "12.0.7.68275",
    [string]$Locale = "zhCN",
    [string]$OutputDir = ".\db2_exports\live_12_0_7_68275",
    [switch]$UseHotfixes = $true,
    [string[]]$Tables = @(
        "SpellName",
        "Spell",
        "SpellEffect",
        "SpellDescriptionVariables",
        "SpellXDescriptionVariables",
        "SpellTooltip",
        "SpellMisc",
        "SpellDuration",
        "SpellRadius",
        "SpellRange",
        "SpellTargetRestrictions",
        "SpellAuraOptions",
        "SpellAuraRestrictions",
        "SpellAuraNames",
        "SpellEffectAutoDescription",
        "SpellCastTimes",
        "SpellCooldowns",
        "SpellInterrupts",
        "SpellLabel",
        "SpellScript",
        "SpellXSpellVisual",
        "CreatureSpellData",
        "Creature",
        "DungeonEncounter",
        "JournalEncounter",
        "JournalEncounterSection",
        "JournalEncounterCreature",
        "JournalInstance"
    )
)

$ErrorActionPreference = "Stop"

$resolvedOutput = Resolve-Path -LiteralPath $OutputDir -ErrorAction SilentlyContinue
if (-not $resolvedOutput) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    $resolvedOutput = Resolve-Path -LiteralPath $OutputDir
}

$hotfixArg = ""
if ($UseHotfixes) {
    $hotfixArg = "&useHotfixes=true"
}

foreach ($table in $Tables) {
    $name = $table.ToLowerInvariant()
    $url = "$BaseUrl/dbc/export/?name=$name&build=$Build&locale=$Locale$hotfixArg"
    $outFile = Join-Path $resolvedOutput.Path "$table.csv"
    Write-Host "Exporting $table -> $outFile"
    try {
        Invoke-WebRequest -Uri $url -OutFile $outFile -UseBasicParsing -TimeoutSec 300
    } catch {
        $statusCode = $null
        if ($_.Exception.Response) {
            $statusCode = [int]$_.Exception.Response.StatusCode
        }
        if ($statusCode -eq 400 -or $statusCode -eq 404) {
            Write-Warning "Skipping $table because WTL returned HTTP $statusCode for this build."
            if (Test-Path -LiteralPath $outFile) {
                Remove-Item -LiteralPath $outFile -Force
            }
            continue
        }
        throw
    }
}

Write-Host "Done. Exported $($Tables.Count) tables to $($resolvedOutput.Path)"
