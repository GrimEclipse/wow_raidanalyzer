param(
    [Parameter(Mandatory = $true)]
    [string]$WowToolsLocalExe,

    [string]$WowFolder = "D:\World of Warcraft",
    [string]$WowProduct = "wow",
    [string]$Region = "cn",
    [string]$Locale = "zhCN"
)

$exe = Resolve-Path -LiteralPath $WowToolsLocalExe -ErrorAction Stop
$folder = Resolve-Path -LiteralPath $WowFolder -ErrorAction Stop

& $exe.Path `
    -wowFolder $folder.Path `
    -wowProduct $WowProduct `
    -region $Region `
    -locale $Locale
