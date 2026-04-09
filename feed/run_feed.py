"""
Entry point for the Kairos X feed pipeline.

Reads config from environment variables (with hardcoded defaults), wires up
the OrderBookManager and RingBuffer, runs the async ITCH parser, then prints
final order-book snapshots and ring-buffer statistics before shutting down.

Environment variables:
    ITCH_FILE   Path to the ITCH 5.0 binary file
                (default: ~/kairos-x/data/sample.NASDAQ_ITCH50)
    TICKERS     Comma-separated ticker list
                (default: AAPL,MSFT,GOOGL)
    MAX_MSG     Maximum messages to parse — empty = no limit
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Ensure project root is importable regardless of working directory
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from feed.itch_parser import parse_feed
from feed.order_book import OrderBookManager
from shared.ring_buffer import RingBuffer

logging.basicConfig(
    level=logging.WARNING,
    format='%(levelname)s  %(name)s  %(message)s',
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_DEFAULT_FILE    = str(Path.home() / 'kairos-x' / 'data' / 'sample.NASDAQ_ITCH50')
_DEFAULT_TICKERS = ['AAPL', 'MSFT', 'GOOGL']

ITCH_FILE = os.environ.get('ITCH_FILE', _DEFAULT_FILE)
TICKERS   = [t.strip() for t in os.environ.get('TICKERS', ','.join(_DEFAULT_TICKERS)).split(',') if t.strip()]
_max_raw  = os.environ.get('MAX_MSG', '').strip()
MAX_MSG   = int(_max_raw) if _max_raw else None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_price(p: object) -> str:
    """Format an optional float price for display."""
    return f'${p:.4f}' if p is not None else 'N/A'


def _print_snapshot(snap: dict) -> None:
    """Pretty-print a single order-book snapshot."""
    ticker = snap.get('ticker', '???')
    ts     = snap.get('timestamp_ns', 0)
    mid    = snap.get('mid_price')
    spread = snap.get('spread')
    bids   = snap.get('bids', [])
    asks   = snap.get('asks', [])
    bid_vol = snap.get('total_bid_volume', 0)
    ask_vol = snap.get('total_ask_volume', 0)

    print(f'\n  ┌─ {ticker} ─────────────────────────────────────')
    print(f'  │  timestamp : {ts:,} ns')
    print(f'  │  mid price : {_fmt_price(mid)}    spread: {_fmt_price(spread)}')
    print(f'  │  bid vol   : {bid_vol:,}    ask vol: {ask_vol:,}')
    print(f'  │  {"BID PRICE":>14}  {"SHARES":>10}    {"ASK PRICE":>14}  {"SHARES":>10}')

    levels = max(len(bids), len(asks))
    for i in range(min(levels, 5)):
        b_str = f'  ${bids[i][0]:.4f}  {bids[i][1]:>8,}' if i < len(bids) else ' ' * 26
        a_str = f'  ${asks[i][0]:.4f}  {asks[i][1]:>8,}' if i < len(asks) else ''
        print(f'  │  {b_str}    {a_str}')

    print(f'  └{"─" * 52}')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    """Wire up components, run the parser, print results, shut down cleanly."""
    print('=' * 60)
    print('  Kairos X  —  Feed Pipeline')
    print('=' * 60)
    print(f'  File    : {ITCH_FILE}')
    print(f'  Tickers : {TICKERS}')
    print(f'  Max msg : {MAX_MSG or "unlimited"}')
    print()

    obm = OrderBookManager()
    rb  = RingBuffer(name='kairos_ring', create=True)

    try:
        print('  [*] Starting parser...')
        stats = await parse_feed(
            filepath=ITCH_FILE,
            order_book_manager=obm,
            ring_buffer=rb,
            tickers_filter=TICKERS if TICKERS else None,
            max_messages=MAX_MSG,
        )
    except FileNotFoundError:
        print(f'\n  ERROR: File not found — {ITCH_FILE}')
        print('  Run:  python3 data/generate_sample.py   to create test data.')
        rb.cleanup()
        return

    # ---- Stats ----
    print()
    print('─' * 60)
    print('  PARSE STATS')
    print('─' * 60)
    print(f'  Messages parsed  : {stats["messages_parsed"]:,}')
    print(f'  Messages skipped : {stats["messages_skipped"]:,}')
    print(f'  Parse errors     : {stats["parse_errors"]:,}')
    print(f'  Elapsed time     : {stats["elapsed_time"]:.3f}s')
    print(f'  Slots written    : {stats["slots_written"]:,}')

    # ---- Order book snapshots ----
    print()
    print('─' * 60)
    print('  FINAL ORDER BOOK SNAPSHOTS')
    print('─' * 60)

    if not obm.books:
        print('  (no order books built — check tickers_filter and stock_locate_map)')
    else:
        for snap in obm.snapshot_all():
            _print_snapshot(snap)

    # ---- Ring buffer stats ----
    print()
    print('─' * 60)
    print('  RING BUFFER STATS')
    print('─' * 60)
    print(f'  Total slots written : {rb.slots_written:,}')
    latest = rb.read_latest()
    if latest:
        print(f'  Latest snapshot     : ticker={latest.get("ticker", "?")}  '
              f'mid={_fmt_price(latest.get("mid_price"))}')
    else:
        print('  Latest snapshot     : (none)')

    print()
    print('  [*] Done. Cleaning up shared memory...')
    rb.cleanup()
    print('  [*] Shutdown complete.')
    print()


if __name__ == '__main__':
    asyncio.run(main())
