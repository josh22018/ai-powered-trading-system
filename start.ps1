<#
.SYNOPSIS
    Kairos X — PowerShell start script.
.DESCRIPTION
    Launches the Kairos X AI-Powered Trading Engine in various modes.
.PARAMETER Mode
    Execution mode: all (default), feed, gen, agents, spoof
.EXAMPLE
    .\start.ps1
    .\start.ps1 -Mode gen
    .\start.ps1 feed
#>

param(
    [Parameter(Position=0)]
    [ValidateSet('all','feed','gen','agents','spoof')]
    [string]$Mode = 'all'
)

$ErrorActionPreference = 'Stop'

# ---- Config ----
$ITCH_FILE      = if ($env:ITCH_FILE)      { $env:ITCH_FILE }      else { Join-Path $HOME 'kairos-x\data\sample.NASDAQ_ITCH50' }
$TICKERS        = if ($env:TICKERS)        { $env:TICKERS }        else { 'AAPL,MSFT,GOOGL' }
$DASHBOARD_PORT = if ($env:DASHBOARD_PORT) { $env:DASHBOARD_PORT } else { '5001' }
$DASHBOARD_HOST = if ($env:DASHBOARD_HOST) { $env:DASHBOARD_HOST } else { '127.0.0.1' }

$env:ITCH_FILE      = $ITCH_FILE
$env:TICKERS        = $TICKERS
$env:DASHBOARD_PORT = $DASHBOARD_PORT
$env:DASHBOARD_HOST = $DASHBOARD_HOST

# ---- Banner ----
Write-Host ''
Write-Host '  ██╗  ██╗ █████╗ ██╗██████╗  ██████╗ ███████╗    ██╗  ██╗' -ForegroundColor Cyan
Write-Host '  ██║ ██╔╝██╔══██╗██║██╔══██╗██╔═══██╗██╔════╝    ╚██╗██╔╝' -ForegroundColor Cyan
Write-Host '  █████╔╝ ███████║██║██████╔╝██║   ██║███████╗     ╚███╔╝ ' -ForegroundColor Cyan
Write-Host '  ██╔═██╗ ██╔══██║██║██╔══██╗██║   ██║╚════██║     ██╔██╗ ' -ForegroundColor Cyan
Write-Host '  ██║  ██╗██║  ██║██║██║  ██║╚██████╔╝███████║    ██╔╝ ██╗' -ForegroundColor Cyan
Write-Host '  ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝    ╚═╝  ╚═╝' -ForegroundColor Cyan
Write-Host ''
Write-Host '  AI-Powered Algorithmic Trading Engine' -ForegroundColor White
Write-Host '  ────────────────────────────────────────────────────────'
Write-Host "  Tickers    : $TICKERS"
Write-Host "  ITCH file  : $ITCH_FILE"
Write-Host "  Dashboard  : http://${DASHBOARD_HOST}:${DASHBOARD_PORT}"
Write-Host '  ────────────────────────────────────────────────────────'
Write-Host ''

# ---- Python check ----
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error 'python not found in PATH.'
    exit 1
}

function Generate-Data {
    Write-Host '  [*] Generating sample ITCH data...' -ForegroundColor Yellow
    python data\generate_sample.py
    Write-Host '  [*] Data ready.' -ForegroundColor Green
}

# ---- Dispatch ----
switch ($Mode) {
    'gen' {
        Generate-Data
    }
    'feed' {
        if (-not (Test-Path $ITCH_FILE)) { Generate-Data }
        python feed\run_feed.py
    }
    'agents' {
        if (-not (Test-Path $ITCH_FILE)) { Generate-Data }
        python agents\run_agents.py
    }
    'spoof' {
        python tools\spoof_demo.py
    }
    'all' {
        if (-not (Test-Path $ITCH_FILE)) { Generate-Data }
        Write-Host '  [*] Starting full engine...' -ForegroundColor Yellow
        Write-Host "  [*] Dashboard -> http://${DASHBOARD_HOST}:${DASHBOARD_PORT}" -ForegroundColor Green
        Write-Host ''
        python run_all.py
    }
}
