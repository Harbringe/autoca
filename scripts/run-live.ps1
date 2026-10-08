# Runs the API on this PC (http://localhost:8000) against the LIVE database, through the tunnel from live-tunnel.ps1.
#
#   scripts\run-live.ps1
#   cd web; npm run dev            # then open http://localhost:5173 and sign in with your real account
#
# Settings come from .env.live (copy deploy\live.env.example; it is ignored by git and must never be committed or pasted
# anywhere). Only runserver, check, showmigrations and shell are allowed with these settings (config/settings/live.py); the
# tests refuse to run in a window that was started this way. Everything you do in the app is real: it changes real books.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path .env.live)) {
    Write-Error ".env.live is missing. Copy deploy\live.env.example to .env.live and fill it in (docs/LIVE.md)."
}

$port = 5433
if (-not (Test-NetConnection -ComputerName localhost -Port $port -InformationLevel Quiet -WarningAction SilentlyContinue)) {
    Write-Error "Nothing is listening on localhost:$port. Start scripts\live-tunnel.ps1 in another window first."
}

Get-Content .env.live | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
        $key, $value = $line.Split("=", 2)
        [Environment]::SetEnvironmentVariable($key.Trim(), $value.Trim(), "Process")
    }
}
$env:DJANGO_SETTINGS_MODULE = "config.settings.live"
$env:AUTOCA_LIVE_DB = "1"

Write-Host ""
Write-Host "  CONNECTED TO THE LIVE DATABASE. What you do here is real." -ForegroundColor Red
Write-Host ""
& .\.venv\Scripts\python.exe manage.py runserver 8000
