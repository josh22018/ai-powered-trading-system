"""
Kairos X — Live Orchestrator.

Launches all subsystems as concurrent asyncio tasks:

  1. Upstox Feed    — reads live websocket from Upstox, populates RingBuffer
  2. Snapshot pump  — drains RingBuffer into EngineState.snapshots
  3. Analyst agent  — computes indicators from snapshots
  4. Oracle agent   — generates BUY/SELL/HOLD signals
  5. Strategist agent — manages virtual positions and triggers Live Execution
  6. Guardian agent — enforces risk limits
  7. Dashboard      — FastAPI + uvicorn (port 8000)

"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import threading
from pathlib import Path

# ---- Ensure project root is importable ----
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ---- Config ----
TICKERS = [t.strip() for t in os.environ.get('TICKERS', 'RELIANCE,HDFCBANK,TCS,INFY').split(',') if t.strip()]
DASHBOARD_PORT = int(os.environ.get('DASHBOARD_PORT', '5001'))
DASHBOARD_HOST = os.environ.get('DASHBOARD_HOST', '127.0.0.1')

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s  %(levelname)-7s  %(name)s  %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('kairos.orchestrator')


# ---- Imports (after sys.path is set) ----
from agents.analyst.analyst        import AnalystAgent
from agents.guardian.guardian      import GuardianAgent
from agents.oracle.oracle          import OracleAgent
from agents.strategist.strategist  import StrategistAgent
from dashboard.backend.app         import create_app
from feed.upstox_feed              import UpstoxFeed
from shared.ring_buffer            import RingBuffer
from shared.state                  import EngineState
from run_all                       import snapshot_pump, run_dashboard

def start_upstox_feed_thread(tickers):
    """Run the blocking Upstox feed in a separate thread."""
    try:
        feed = UpstoxFeed(tickers)
        feed.start()
    except Exception as e:
        print(f"Error starting Upstox Feed: {e}")

async def main() -> None:
    """Wire up all components and run until Ctrl-C."""
    print('=' * 62)
    print('  Kairos X  —  LIVE Trading Engine (Upstox)')
    print('=' * 62)
    print(f'  Tickers   : {TICKERS}')
    print(f'  Dashboard : http://{DASHBOARD_HOST}:{DASHBOARD_PORT}')
    print()

    # Shared infrastructure
    state = EngineState(TICKERS)
    rb    = RingBuffer(name='kairos_ring', create=True)

    # Agent instances
    analyst    = AnalystAgent(state)
    oracle     = OracleAgent(state)
    strategist = StrategistAgent(state)
    guardian   = GuardianAgent(state)

    # Start Upstox Feed Thread
    feed_thread = threading.Thread(target=start_upstox_feed_thread, args=(TICKERS,), daemon=True)
    feed_thread.start()

    # Gather all long-running coroutines
    tasks = [
        asyncio.create_task(snapshot_pump(rb, state),   name='pump'),
        asyncio.create_task(analyst.run(),               name='analyst'),
        asyncio.create_task(oracle.run(),                name='oracle'),
        asyncio.create_task(strategist.run(),            name='strategist'),
        asyncio.create_task(guardian.run(),              name='guardian'),
        asyncio.create_task(run_dashboard(state),        name='dashboard'),
    ]

    # Register SIGINT/SIGTERM for graceful shutdown
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _shutdown(sig_name: str) -> None:
        print(f'\n[orchestrator] {sig_name} received — shutting down...')
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown, sig.name)
        except (NotImplementedError, RuntimeError):
            pass   # Windows fallback — Ctrl-C will raise KeyboardInterrupt

    print('[orchestrator] All systems online. Press Ctrl-C to stop.\n')

    try:
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_EXCEPTION,
        )

        for task in done:
            if task.exception():
                log.error('Task %s raised: %s', task.get_name(), task.exception())

        if not stop_event.is_set():
            await stop_event.wait()

    except KeyboardInterrupt:
        print('\n[orchestrator] KeyboardInterrupt — shutting down...')
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        rb.cleanup()
        print('[orchestrator] Shutdown complete.')

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
