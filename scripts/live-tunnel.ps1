# Opens a tunnel from this PC to the live server's database, and keeps it open until you close this window.
#
#   scripts\live-tunnel.ps1            # the database appears at localhost:5433
#
# Nothing is opened to the internet. This is an AWS Systems Manager port-forwarding session: you sign in with your own AWS
# login, the session is logged, and the database port on the server listens on the server's own loopback only (compose.prod.yaml).
# See docs/LIVE.md.

param(
    [int]$LocalPort = 5433,
    [string]$InstanceId = $env:AUTOCA_INSTANCE_ID,
    [string]$Region = "ap-south-1"
)

$ErrorActionPreference = "Stop"

if (-not $InstanceId) {
    Write-Error "Say which server: set AUTOCA_INSTANCE_ID (the instance id, i-...) or pass -InstanceId."
}

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-Error "The AWS CLI is not installed. Install it with:  winget install Amazon.AWSCLI   then open a new window."
}
if (-not (Get-Command session-manager-plugin -ErrorAction SilentlyContinue)) {
    Write-Error "The Session Manager plugin is not installed. Install it with:  winget install Amazon.SessionManagerPlugin   then open a new window."
}

Write-Host "Opening the tunnel to the LIVE database on localhost:$LocalPort. Close this window to close it." -ForegroundColor Yellow
# AWS ends a Session Manager session after 20 minutes without traffic, which would leave the app talking to a closed port.
# So when it ends, open it again (Ctrl+C stops the loop; a failure to start twice in a row stops it too).
$failures = 0
while ($true) {
    $started = Get-Date
    aws ssm start-session `
        --target $InstanceId `
        --region $Region `
        --document-name AWS-StartPortForwardingSession `
        --parameters "portNumber=5432,localPortNumber=$LocalPort"
    if (((Get-Date) - $started).TotalSeconds -lt 10) { $failures++ } else { $failures = 0 }
    if ($failures -ge 2) { Write-Error "The tunnel would not stay open. Check your AWS sign-in and the instance id."; break }
    Write-Host "The tunnel closed (idle timeout). Opening it again..." -ForegroundColor Yellow
}
