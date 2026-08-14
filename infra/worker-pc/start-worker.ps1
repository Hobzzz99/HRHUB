# Starts the scraping worker on this PC.
#
# Run tunnel.ps1 in another window first. Then leave this one open: when a
# recruiter starts a search on the website, a Chromium window opens here, and
# the first run of the day will ask you to sign in to LinkedIn and clear a
# CAPTCHA by hand. That is the design — nothing types a password.
#
#   .\start-worker.ps1

param(
    [string]$EnvFile = ".env.worker",
    [int]$PostgresPort = 15432,
    [int]$RedisPort = 16379
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Resolve-Path (Join-Path $here "..\..\backend")

function Test-Port([int]$Port) {
    $probe = New-Object Net.Sockets.TcpClient
    try { $probe.Connect("127.0.0.1", $Port); $probe.Close(); return $true }
    catch { return $false }
}

# A missing tunnel otherwise surfaces as a confusing database connection error
# several seconds into startup.
foreach ($check in @(@{Port = $PostgresPort; Name = "Postgres" },
                     @{Port = $RedisPort; Name = "Redis" })) {
    if (-not (Test-Port $check.Port)) {
        Write-Host "$($check.Name) is not reachable on 127.0.0.1:$($check.Port)." -ForegroundColor Red
        Write-Host "The SSH tunnel is not running. Open another window and run:"
        Write-Host "  .\tunnel.ps1 -Server <your-server> -User <your-user>"
        exit 1
    }
}

$envPath = Join-Path $here $EnvFile
if (-not (Test-Path $envPath)) {
    Write-Host "$EnvFile not found in $here." -ForegroundColor Red
    Write-Host "Copy .env.worker.example to .env.worker and fill it in."
    exit 1
}

# Celery reads configuration from the process environment, so the file is
# loaded here rather than passed as a flag.
Get-Content $envPath | ForEach-Object {
    if ($_ -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$') {
        $name = $matches[1]
        $value = $matches[2]
        # Drop a trailing " # comment". The templates keep comments on their own
        # lines, but values get copied across from .env.example, which does not —
        # and a password that silently absorbs "# reuse a cached profile" fails
        # in a way nobody would think to look for. Safe for our values: the
        # passwords and Fernet keys are base64, which has no '#'.
        $value = ($value -replace '\s+#.*$', '').Trim()
        if ($value -match '^#') { $value = "" }
        # Strip surrounding quotes if someone added them.
        if ($value -match '^"(.*)"$' -or $value -match "^'(.*)'$") { $value = $matches[1] }
        Set-Item -Path "env:$name" -Value $value
    }
}

if ($env:CREDENTIAL_ENC_KEY -like "REPLACE_*" -or -not $env:CREDENTIAL_ENC_KEY) {
    Write-Host "CREDENTIAL_ENC_KEY is not set in $EnvFile." -ForegroundColor Red
    Write-Host "It must be the same key as the server, or stored sessions cannot be read."
    exit 1
}

# This laptop scrapes with one recruiter's LinkedIn account, so it must take
# only that recruiter's searches. Listening to the shared queue would mean
# collecting a colleague's search and running it against the wrong account.
if ($env:WORKER_USER_ID -like "REPLACE_*" -or -not $env:WORKER_USER_ID) {
    Write-Host "WORKER_USER_ID is not set in $EnvFile." -ForegroundColor Red
    Write-Host "It is the recruiter's user id, from Supabase (Authentication > Users)."
    Write-Host "Without it this laptop would pick up other recruiters' searches."
    exit 1
}
$queue = "user-$($env:WORKER_USER_ID)"

if ($env:SCRAPE_STATE_DIR -and -not (Test-Path $env:SCRAPE_STATE_DIR)) {
    New-Item -ItemType Directory -Force $env:SCRAPE_STATE_DIR | Out-Null
}

Write-Host "Worker starting." -ForegroundColor Cyan
Write-Host "  provider   $($env:PROVIDER)"
Write-Host "  queue      $queue   (this recruiter's searches only)"
Write-Host "  hourly cap $($env:SCRAPE_MAX_PROFILES_PER_HOUR) profiles"
Write-Host "  budget     $($env:SCRAPE_STATE_DIR)"
Write-Host ""
Write-Host "A browser window will open when a search runs. Sign in when asked." -ForegroundColor Yellow
Write-Host ""

Push-Location $backend
try {
    # --concurrency=1 and --pool=solo are both deliberate. One browser at a
    # time keeps the hourly budget honest (each process keeps its own count),
    # and solo avoids the prefork pool, which does not work on Windows.
    # -Q restricts this worker to its own recruiter's queue.
    celery -A app.workers.celery_app.celery_app worker `
        --loglevel=info --pool=solo --concurrency=1 -Q $queue
}
finally {
    Pop-Location
}
