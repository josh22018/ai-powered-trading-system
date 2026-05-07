@echo off
REM =============================================================================
REM Kairos X — Windows start script
REM =============================================================================
REM Usage:
REM   start.bat            (run full engine: feed + agents + dashboard)
REM   start.bat feed       (feed pipeline only, no dashboard)
REM   start.bat gen        (regenerate sample data only)
REM   start.bat agents     (run Phase 2 agent training + demo)
REM   start.bat spoof      (run spoofing detection demo)
REM
REM Environment overrides:
REM   set ITCH_FILE=...  set TICKERS=AAPL,MSFT  set DASHBOARD_PORT=8080
REM =============================================================================

setlocal

REM ---- Defaults ----
if not defined ITCH_FILE set "ITCH_FILE=%USERPROFILE%\kairos-x\data\sample.NASDAQ_ITCH50"
if not defined TICKERS set "TICKERS=AAPL,MSFT,GOOGL"
if not defined DASHBOARD_PORT set "DASHBOARD_PORT=5001"
if not defined DASHBOARD_HOST set "DASHBOARD_HOST=127.0.0.1"

set "MODE=%~1"
if "%MODE%"=="" set "MODE=all"

echo.
echo   ██╗  ██╗ █████╗ ██╗██████╗  ██████╗ ███████╗    ██╗  ██╗
echo   ██║ ██╔╝██╔══██╗██║██╔══██╗██╔═══██╗██╔════╝    ╚██╗██╔╝
echo   █████╔╝ ███████║██║██████╔╝██║   ██║███████╗     ╚███╔╝
echo   ██╔═██╗ ██╔══██║██║██╔══██╗██║   ██║╚════██║     ██╔██╗
echo   ██║  ██╗██║  ██║██║██║  ██║╚██████╔╝███████║    ██╔╝ ██╗
echo   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝    ╚═╝  ╚═╝
echo.
echo   AI-Powered Algorithmic Trading Engine
echo   ────────────────────────────────────────────────────────
echo   Tickers    : %TICKERS%
echo   ITCH file  : %ITCH_FILE%
echo   Dashboard  : http://%DASHBOARD_HOST%:%DASHBOARD_PORT%
echo   ────────────────────────────────────────────────────────
echo.

REM ---- Check Python ----
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: python not found in PATH.
    exit /b 1
)

REM ---- Dispatch ----
if /i "%MODE%"=="gen" goto :gen
if /i "%MODE%"=="feed" goto :feed
if /i "%MODE%"=="agents" goto :agents
if /i "%MODE%"=="spoof" goto :spoof
if /i "%MODE%"=="all" goto :all

echo Usage: %~nx0 [all^|feed^|gen^|agents^|spoof]
exit /b 1

:gen
echo   [*] Generating sample ITCH data...
python data\generate_sample.py
echo   [*] Data ready.
goto :eof

:feed
if not exist "%ITCH_FILE%" goto :gen
python feed\run_feed.py
goto :eof

:agents
if not exist "%ITCH_FILE%" (
    echo   [*] Generating sample data first...
    python data\generate_sample.py
)
python agents\run_agents.py
goto :eof

:spoof
python tools\spoof_demo.py
goto :eof

:all
if not exist "%ITCH_FILE%" (
    echo   [*] Generating sample data first...
    python data\generate_sample.py
)
echo   [*] Starting full engine...
echo   [*] Dashboard: http://%DASHBOARD_HOST%:%DASHBOARD_PORT%
echo.
python run_all.py
goto :eof
