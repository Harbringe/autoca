# A READ-ONLY report on one client's learned rules and parties, run against the LIVE database through the tunnel (live-tunnel.ps1).
#
#   scripts\live-rules-report.ps1 -Firm <firm uuid> -Client "Mauli"
#
# It writes nothing. Settings come from .env.live, as in run-live.ps1.
param([Parameter(Mandatory = $true)][string]$Firm, [Parameter(Mandatory = $true)][string]$Client)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path .env.live)) { Write-Error ".env.live is missing (docs/LIVE.md)." }
Get-Content .env.live | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
        $key, $value = $line.Split("=", 2)
        [Environment]::SetEnvironmentVariable($key.Trim(), $value.Trim(), "Process")
    }
}
$env:DJANGO_SETTINGS_MODULE = "config.settings.live"
$env:AUTOCA_LIVE_DB = "1"
& .\.venv\Scripts\python.exe manage.py rules_report --firm $Firm --client $Client
