#!/usr/bin/env bash
# =============================================================================
# Kairos X — start script
# =============================================================================
# Usage:
#   ./start.sh            # run full engine (feed + agents + dashboard)
#   ./start.sh feed       # feed pipeline only  (no dashboard)
#   ./start.sh gen        # regenerate sample data only
#   ./start.sh dash       # dashboard only (assumes feed ran already)
#
# Environment overrides:
#   ITCH_FILE=...  TICKERS=AAPL,MSFT  MAX_MSG=10000  DASHBOARD_PORT=8080
# =============================================================================

set -euo pipefail
cd "$(dirname "$0")"

ITCH_FILE="${ITCH_FILE:-$HOME/kairos-x/data/sample.NASDAQ_ITCH50}"
TICKERS="${TICKERS:-AAPL,MSFT,GOOGL}"
DASHBOARD_PORT="${DASHBOARD_PORT:-5001}"
DASHBOARD_HOST="${DASHBOARD_HOST:-127.0.0.1}"

MODE="${1:-all}"

banner() {
  echo ""
  echo "  ██╗  ██╗ █████╗ ██╗██████╗  ██████╗ ███████╗    ██╗  ██╗"
  echo "  ██║ ██╔╝██╔══██╗██║██╔══██╗██╔═══██╗██╔════╝    ╚██╗██╔╝"
  echo "  █████╔╝ ███████║██║██████╔╝██║   ██║███████╗     ╚███╔╝ "
  echo "  ██╔═██╗ ██╔══██║██║██╔══██╗██║   ██║╚════██║     ██╔██╗ "
  echo "  ██║  ██╗██║  ██║██║██║  ██║╚██████╔╝███████║    ██╔╝ ██╗"
  echo "  ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝    ╚═╝  ╚═╝"
  echo ""
  echo "  AI-Powered Algorithmic Trading Engine"
  echo "  ────────────────────────────────────────────────────────"
  echo "  Tickers    : $TICKERS"
  echo "  ITCH file  : $ITCH_FILE"
  echo "  Dashboard  : http://$DASHBOARD_HOST:$DASHBOARD_PORT"
  echo "  ────────────────────────────────────────────────────────"
  echo ""
}

check_python() {
  if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found." >&2
    exit 1
  fi
}

generate_data() {
  echo "  [*] Generating sample ITCH data..."
  python3 data/generate_sample.py
  echo "  [*] Data ready."
}

run_feed_only() {
  export ITCH_FILE TICKERS DASHBOARD_PORT DASHBOARD_HOST
  [[ -f "$ITCH_FILE" ]] || generate_data
  python3 feed/run_feed.py
}

run_all() {
  export ITCH_FILE TICKERS DASHBOARD_PORT DASHBOARD_HOST
  [[ -f "$ITCH_FILE" ]] || generate_data
  echo "  [*] Starting full engine..."
  echo "  [*] Dashboard → http://$DASHBOARD_HOST:$DASHBOARD_PORT"
  echo ""
  python3 run_all.py
}

# ---- dispatch ----
banner
check_python

case "$MODE" in
  gen)   generate_data ;;
  feed)  run_feed_only ;;
  all)   run_all ;;
  *)
    echo "Usage: $0 [all|feed|gen]"
    exit 1
    ;;
esac
