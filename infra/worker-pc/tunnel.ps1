# Opens the encrypted path from this PC to the server's database and job queue.
#
# The server keeps Postgres and Redis on loopback, so they are unreachable from
# the internet. This forwards two local ports across SSH instead of exposing
# them: everything travels inside the SSH session, and the ports it opens here
# are visible only to this machine.
#
#   .\tunnel.ps1 -Server talent.yourcompany.com -User deploy
#
# Leave the window open while the worker runs. start-worker.ps1 checks that
# this is up before it starts, and says so if it is not.

param(
    [Parameter(Mandatory = $true)][string]$Server,
    [string]$User = "deploy",
    [int]$PostgresPort = 15432,
    [int]$RedisPort = 16379
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    Write-Host "ssh not found." -ForegroundColor Red
    Write-Host "Install it: Settings > System > Optional features > OpenSSH Client."
    exit 1
}

Write-Host "Tunnelling to $Server" -ForegroundColor Cyan
Write-Host "  postgres  127.0.0.1:$PostgresPort  ->  server localhost:5432"
Write-Host "  redis     127.0.0.1:$RedisPort  ->  server localhost:6379"
Write-Host ""
Write-Host "Keep this window open. Ctrl+C closes the tunnel and stops the worker."
Write-Host ""

# -N: no remote command, just forwarding.
# ServerAliveInterval: a dropped tunnel otherwise looks like a hung worker.
ssh -N `
    -o ServerAliveInterval=30 `
    -o ServerAliveCountMax=3 `
    -o ExitOnForwardFailure=yes `
    -L "${PostgresPort}:localhost:5432" `
    -L "${RedisPort}:localhost:6379" `
    "$User@$Server"
