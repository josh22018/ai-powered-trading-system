"""
Kairos X — main orchestrator.

Launches all subsystems as concurrent asyncio tasks:

  1. Feed parser    — reads ITCH file, populates OrderBookManager + RingBuffer
  2. Snapshot pump  — drains RingBuffer into EngineState.snapshots
  3. Analyst agent  — computes indicators from snapshots
  4. Oracle agent   — generates BUY/SELL/HOLD signals
  5. Strategist agent — manages virtual positions
  6. Guardian agent — enforces risk limits
  7. Dashboard      — FastAPI + uvicorn (port 8000)

After the ITCH file is fully parsed the engine continues running with the
last order-book state so the dashboard stays live for inspection.

Environment variables (all optional):
  ITCH_FILE     path to ITCH 5.0 binary  (default: ~/kairos-x/data/sample.NASDAQ_ITCH50)
  TICKERS       comma-separated tickers  (default: AAPL,MSFT,GOOGL)
  MAX_MSG       max messages to parse    (default: unlimited)
  DASHBOARD_PORT uvicorn port           (default: 8000)
  DASHBOARD_HOST uvicorn host           (default: 127.0.0.1)
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

# ---- Ensure project root is importable ----
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ---- Config ----
_DEFAULT_FILE = str(Path.home() / 'kairos-x' / 'data' / 'sample.NASDAQ_ITCH50')
ITCH_FILE      = os.environ.get('ITCH_FILE', _DEFAULT_FILE)
TICKERS        = [t.strip() for t in os.environ.get('TICKERS', 'AAPL,MSFT,GOOGL').split(',') if t.strip()]
_max_raw       = os.environ.get('MAX_MSG', '').strip()
MAX_MSG        = int(_max_raw) if _max_raw else None
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
from feed.itch_parser              import parse_feed
from feed.order_book               import OrderBookManager
from shared.ring_buffer            import RingBuffer
from shared.state                  import EngineState


# ---------------------------------------------------------------------------
# Snapshot pump — drains RingBuffer into EngineState
# ---------------------------------------------------------------------------

async def snapshot_pump(rb: RingBuffer, state: EngineState) -> None:
    """
    Continuously drain new snapshots from the RingBuffer into EngineState.

    Reads all new slots since the last check and updates state.snapshots
    with the most recent entry per ticker.  Yields to the event loop
    between polls so other coroutines can run.
    """
    last_idx = 0
    while True:
        try:
            snapshots, last_idx = rb.read_all_new(last_idx)
            if snapshots:
                # snapshots is a list of per-ticker dicts (or lists of dicts)
                # The ring buffer stores one snapshot per write call;
                # parse_feed writes snapshot_all() which is a list.
                latest: dict = {}
                for item in snapshots:
                    if isinstance(item, list):
                        for snap in item:
                            if isinstance(snap, dict) and 'ticker' in snap:
                                latest[snap['ticker']] = snap
                    elif isinstance(item, dict) and 'ticker' in item:
                        latest[item['ticker']] = item

                if latest:
                    async with state.lock_snapshots:
                        state.snapshots.update(latest)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            log.warning('Snapshot pump error: %s', exc)
        await asyncio.sleep(0.1)


# ---------------------------------------------------------------------------
# Dashboard runner
# ---------------------------------------------------------------------------

async def run_dashboard(state: EngineState) -> None:
    """
    Start uvicorn serving the FastAPI dashboard app.

    Runs in the current event loop via uvicorn's programmatic API.
    """
    import uvicorn

    app = create_app(state)
    config = uvicorn.Config(
        app,
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        log_level='warning',
        loop='none',          # use existing event loop
    )
    server = uvicorn.Server(config)
    try:
        await server.serve()
    except asyncio.CancelledError:
        server.should_exit = True


# ---------------------------------------------------------------------------
# Feed runner
# ---------------------------------------------------------------------------

async def run_feed(obm: OrderBookManager, rb: RingBuffer) -> None:
    """Run the ITCH parser once then return (feed file is finite)."""
    print(f'\n[feed] Parsing {ITCH_FILE} ...')
    try:
        stats = await parse_feed(
            filepath=ITCH_FILE,
            order_book_manager=obm,
            ring_buffer=rb,
            tickers_filter=TICKERS if TICKERS else None,
            max_messages=MAX_MSG,
        )
        print(
            f'[feed] Done — {stats["messages_parsed"]:,} msgs  '
            f'{stats["slots_written"]:,} slots  '
            f'{stats["elapsed_time"]:.2f}s  '
            f'errors={stats["parse_errors"]}'
        )
    except FileNotFoundError:
        print(f'[feed] ERROR: file not found — {ITCH_FILE}')
        print('[feed] Run:  python3 data/generate_sample.py')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    """Wire up all components and run until Ctrl-C."""
    print('=' * 62)
    print('  Kairos X  —  Full Trading Engine')
    print('=' * 62)
    print(f'  Tickers   : {TICKERS}')
    print(f'  ITCH file : {ITCH_FILE}')
    print(f'  Dashboard : http://{DASHBOARD_HOST}:{DASHBOARD_PORT}')
    print()

    # Shared infrastructure
    state = EngineState(TICKERS)
    obm   = OrderBookManager()
    rb    = RingBuffer(name='kairos_ring', create=True)

    # Agent instances
    analyst   = AnalystAgent(state)
    oracle    = OracleAgent(state)
    strategist = StrategistAgent(state)
    guardian  = GuardianAgent(state)

    # Gather all long-running coroutines
    tasks = [
        asyncio.create_task(run_feed(obm, rb),          name='feed'),
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
        # Wait until stop is requested or all tasks finish naturally
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_EXCEPTION,
        )

        # Surface any exceptions from completed tasks
        for task in done:
            if task.exception():
                log.error('Task %s raised: %s', task.get_name(), task.exception())

        # If we got here without stop_event, wait for it (keeps dashboard up)
        if not stop_event.is_set():
            print('[orchestrator] Feed complete. Dashboard still running — Ctrl-C to exit.')
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
