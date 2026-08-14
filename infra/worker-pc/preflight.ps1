# Checks this laptop can actually run searches, before a recruiter needs it to.
#
# Every failure below has a fix, and none of them is obvious from the error the
# worker would otherwise produce hours later — usually while somebody waits for
# a shortlist. Run it after setup, and again whenever something stops working.
#
#   .\preflight.ps1

param(
    [string]$EnvFile = ".env.worker",
    [int]$PostgresPort = 15432,
    [int]$RedisPort = 16379
)

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$problems = @()

function Ok($m)   { Write-Host "  [ok]   $m" -ForegroundColor Green }
function Bad($m, $fix) {
    Write-Host "  [FAIL] $m" -ForegroundColor Red
    Write-Host "         fix: $fix" -ForegroundColor Yellow
    $script:problems += $m
}

Write-Host ""
Write-Host "TalentFinder worker preflight" -ForegroundColor Cyan
Write-Host ""

# --- The tools --------------------------------------------------------------
Write-Host "Tools"
if (Get-Command python -ErrorAction SilentlyContinue) {
    $v = (python --version 2>&1) -replace 'Python\s*',''
    if ([version]($v -split '\+')[0] -ge [version]"3.12") { Ok "Python $v" }
    else { Bad "Python $v is too old" "install Python 3.12 or newer" }
} else {
    Bad "Python not on PATH" "reinstall Python with 'Add Python to PATH' ticked"
}

if (Get-Command ssh -ErrorAction SilentlyContinue) { Ok "OpenSSH client" }
else { Bad "ssh not found" "Settings > System > Optional features > OpenSSH Client" }

python -c "import celery, playwright" 2>$null
if ($LASTEXITCODE -eq 0) { Ok "Python dependencies installed" }
else { Bad "backend dependencies missing" "cd ..\..\backend; pip install ." }

# --- The browser ------------------------------------------------------------
Write-Host ""
Write-Host "Browser"
$browsers = $env:PLAYWRIGHT_BROWSERS_PATH
if (-not $browsers) { $browsers = Join-Path $env:LOCALAPPDATA "ms-playwright" }
if ((Test-Path $browsers) -and (Get-ChildItem $browsers -Filter "chromium*" -ErrorAction SilentlyContinue)) {
    Ok "Chromium present"
} else {
    Bad "Chromium not installed" "playwright install chromium"
}

# --- Configuration ----------------------------------------------------------
Write-Host ""
Write-Host "Configuration"
$envPath = Join-Path $here $EnvFile
if (-not (Test-Path $envPath)) {
    Bad "$EnvFile missing" "copy .env.worker.example .env.worker and fill it in"
} else {
    Ok "$EnvFile present"
    $conf = @{}
    Get-Content $envPath | ForEach-Object {
        if ($_ -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$') {
            $conf[$matches[1]] = ($matches[2] -replace '\s+#.*$', '').Trim()
        }
    }

    foreach ($key in @("WORKER_USER_ID", "CREDENTIAL_ENC_KEY", "DATABASE_URL")) {
        $val = $conf[$key]
        if (-not $val -or $val -like "REPLACE_*") {
            Bad "$key is not set" "fill it in in $EnvFile"
        } else { Ok "$key set" }
    }

    # The one people get wrong by copying a colleague's file. Nothing
    # server-side checks it, and getting it wrong means this laptop quietly
    # runs someone else's searches against the wrong LinkedIn account.
    if ($conf["WORKER_USER_ID"] -and $conf["WORKER_USER_ID"] -notlike "REPLACE_*") {
        Write-Host "  [check] this laptop will run searches for user id:" -ForegroundColor Cyan
        Write-Host "          $($conf['WORKER_USER_ID'])"
        Write-Host "          Confirm that is the person sitting here." -ForegroundColor Yellow
    }

    if ($conf["SCRAPE_HEADLESS"] -eq "true") {
        Bad "SCRAPE_HEADLESS is true" "set it false — sign-in and CAPTCHAs need a visible window"
    }

    $stateDir = $conf["SCRAPE_STATE_DIR"]
    if ($stateDir) {
        try {
            New-Item -ItemType Directory -Force $stateDir -ErrorAction Stop | Out-Null
            Ok "state directory writable ($stateDir)"
        } catch {
            Bad "cannot write $stateDir" "pick a writable path — the hourly cap lives here, and without it a fresh budget is handed out on every restart"
        }
    }
}

# --- The server -------------------------------------------------------------
Write-Host ""
Write-Host "Connection (needs tunnel.ps1 running)"
foreach ($check in @(@{Port=$PostgresPort; Name="Postgres"}, @{Port=$RedisPort; Name="Redis"})) {
    $probe = New-Object Net.Sockets.TcpClient
    try {
        $probe.Connect("127.0.0.1", $check.Port); $probe.Close()
        Ok "$($check.Name) reachable on 127.0.0.1:$($check.Port)"
    } catch {
        Bad "$($check.Name) unreachable" "run .\tunnel.ps1 -Server <host> -User <user> in another window"
    }
}

# --- Power ------------------------------------------------------------------
Write-Host ""
Write-Host "Power"
$standby = (powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 2>$null | Select-String "Current AC Power Setting Index" | Select-Object -First 1)
if ($standby -and $standby -match "0x00000000") {
    Ok "does not sleep on AC power"
} else {
    Bad "this laptop sleeps on AC power" "powercfg /change standby-timeout-ac 0 — a sleeping laptop leaves searches queued and never run"
}

Write-Host ""
if ($problems.Count -eq 0) {
    Write-Host "Ready. Start the worker with .\start-worker.ps1" -ForegroundColor Green
    exit 0
}
Write-Host "$($problems.Count) problem(s) to fix before this laptop can run searches." -ForegroundColor Red
exit 1
