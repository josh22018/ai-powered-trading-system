"""
Kairos X — Phase 2 Agent Runner

Trains all 4 agents on synthetic data, runs a 100-iteration inference
demo, executes portfolio trades based on Strategist signals, and
prints a final valuation summary.
"""

from __future__ import annotations

import asyncio
import sys
import os
from collections import defaultdict
from pathlib import Path

# Ensure project root is on sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from feed.itch_parser import parse_feed
from feed.order_book import OrderBookManager
from shared.ring_buffer import RingBuffer
from shared.portfolio import Portfolio
from shared.signals_store import SignalsStore
from agents.oracle.oracle_agent import OracleAgent
from agents.analyst.analyst_agent import AnalystAgent
from agents.guardian.guardian_agent import GuardianAgent
from agents.strategist.strategist_agent import StrategistAgent

ITCH_FILE    = str(Path.home() / 'kairos-x' / 'data' / 'sample.NASDAQ_ITCH50')
TICKERS      = ['AAPL', 'MSFT', 'GOOGL']
PORTFOLIO_PATH = str(Path.home() / 'kairos-x' / 'shared' / 'portfolio.json')
DEMO_ITERS   = 100


# ---------------------------------------------------------------------------
# Step 1 — collect snapshots by replaying the ITCH file
# ---------------------------------------------------------------------------

async def collect_snapshots() -> dict:
    """Re-parse the ITCH file and collect all snapshots per ticker."""
    print('\n[FEED] Replaying ITCH file to collect training snapshots...')
    obm = OrderBookManager()
    rb  = RingBuffer(name='kairos_train', create=True)
    snapshots_all: list[dict] = []

    async def _capturing_parse():
        """Wrap parse_feed and capture every snapshot written."""
        from feed.itch_messages import (
            MSG_ADD_ORDER, MSG_ADD_ORDER_MPID, MSG_CANCEL_ORDER,
            MSG_DELETE_ORDER, MSG_EXECUTE_ORDER, MSG_EXECUTE_PRICE,
            MSG_REPLACE_ORDER, MSG_STOCK_DIRECTORY, MSG_SYSTEM_EVENT,
            STRUCT_ADD_ORDER, STRUCT_ADD_ORDER_MPID, STRUCT_CANCEL_ORDER,
            STRUCT_DELETE_ORDER, STRUCT_EXECUTE_ORDER, STRUCT_EXECUTE_PRICE,
            STRUCT_REPLACE_ORDER, STRUCT_STOCK_DIR,
            AddOrderMsg, CancelOrderMsg, DeleteOrderMsg,
            ExecuteOrderMsg, ReplaceOrderMsg,
            parse_price, parse_timestamp,
        )
        import struct as _struct

        _LEN = _struct.Struct('>H')
        _DISPATCH = {
            MSG_ADD_ORDER:      lambda b: _unpack_add(b),
            MSG_DELETE_ORDER:   lambda b: _unpack_del(b),
            MSG_CANCEL_ORDER:   lambda b: _unpack_can(b),
            MSG_EXECUTE_ORDER:  lambda b: _unpack_exe(b),
        }

        def _decode(raw): return raw.decode('ascii', errors='replace').strip()

        def _unpack_add(body):
            _, loc, _, ts, ref, side_b, sh, stk_b, pr = STRUCT_ADD_ORDER.unpack(body)
            return AddOrderMsg(loc, parse_timestamp(ts), ref,
                               side_b.decode(), sh, _decode(stk_b), parse_price(pr))

        def _unpack_del(body):
            _, loc, _, ts, ref = STRUCT_DELETE_ORDER.unpack(body)
            return DeleteOrderMsg(loc, parse_timestamp(ts), ref)

        def _unpack_can(body):
            _, loc, _, ts, ref, cancelled = STRUCT_CANCEL_ORDER.unpack(body)
            return CancelOrderMsg(loc, parse_timestamp(ts), ref, cancelled)

        def _unpack_exe(body):
            _, loc, _, ts, ref, exe, match = STRUCT_EXECUTE_ORDER.unpack(body)
            return ExecuteOrderMsg(loc, parse_timestamp(ts), ref, exe, match)

        with open(ITCH_FILE, 'rb') as fh:
            n = 0
            while True:
                raw_len = fh.read(2)
                if len(raw_len) < 2:
                    break
                (msg_len,) = _LEN.unpack(raw_len)
                body = fh.read(msg_len)
                if len(body) < msg_len:
                    break
                n += 1
                mtype = body[0:1]

                if mtype == MSG_STOCK_DIRECTORY:
                    try:
                        fields = STRUCT_STOCK_DIR.unpack(body)
                        obm.stock_locate_map[fields[1]] = _decode(fields[4])
                    except Exception:
                        pass
                    continue

                if mtype == MSG_SYSTEM_EVENT:
                    continue

                dispatcher = _DISPATCH.get(mtype)
                if dispatcher is None:
                    continue

                try:
                    msg_obj = dispatcher(body)
                except Exception:
                    continue

                ticker = obm.stock_locate_map.get(
                    getattr(msg_obj, 'stock_locate', None), '')
                if ticker not in TICKERS:
                    continue

                obm.route(msg_obj)
                snaps = obm.snapshot_all()
                snapshots_all.extend(snaps)

                if n % 1000 == 0:
                    await asyncio.sleep(0)

    await _capturing_parse()
    rb.cleanup()

    # Group by ticker
    by_ticker: dict = defaultdict(list)
    for s in snapshots_all:
        t = s.get('ticker')
        if t:
            by_ticker[t].append(s)

    total = sum(len(v) for v in by_ticker.values())
    print(f'  Collected {total:,} snapshots  '
          f'({", ".join(f"{t}:{len(v):,}" for t, v in by_ticker.items())})')
    return dict(by_ticker)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mid_price(snap: dict) -> float:
    return float(snap.get('mid_price') or 1.0)


def _print_signal_table(ticker: str, analyst_sig: dict,
                        oracle_sig: dict, strategist_sig: dict,
                        guardian_sig: dict) -> None:
    W = 14
    print(f'\n  Ticker: {ticker}')
    print(f'  ┌{"─"*14}┬{"─"*11}┬{"─"*12}┬{"─"*15}┐')
    print(f'  │ {"Agent":<12} │ {"Signal":<9} │ {"Confidence":<10} │ {"Detail":<13} │')
    print(f'  ├{"─"*14}┼{"─"*11}┼{"─"*12}┼{"─"*15}┤')

    def row(agent, signal, conf, detail):
        c = f'{conf:.2f}' if isinstance(conf, float) else '—'
        print(f'  │ {agent:<12} │ {signal:<9} │ {c:<10} │ {detail:<13} │')

    row('Analyst',    analyst_sig.get('sentiment', '?').capitalize(),
        analyst_sig.get('confidence', 0),
        analyst_sig.get('headline', '')[:13])
    row('Oracle',     oracle_sig.get('direction', '?').capitalize(),
        oracle_sig.get('confidence', 0), ticker)
    row('Strategist', strategist_sig.get('action', '?'),
        strategist_sig.get('confidence', 0), ticker)
    alert = guardian_sig.get('alert_level', 'normal')
    score = guardian_sig.get('anomaly_score', 0.0)
    row('Guardian',   alert.capitalize(), None, f'score={score:.4f}')
    print(f'  └{"─"*14}┴{"─"*11}┴{"─"*12}┴{"─"*15}┘')


def _print_valuation(val: dict) -> None:
    pnl = val['total_pnl']
    pct = val['total_pnl_pct']
    sign = '+' if pnl >= 0 else ''
    print(f'\n  Portfolio Value: ${val["total_portfolio_value"]:,.2f}  '
          f'PnL: {sign}${pnl:.2f} ({sign}{pct:.2f}%)  '
          f'Cash: ${val["cash"]:,.2f}')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print('=' * 65)
    print('  Kairos X — Phase 2: AI Agents + Portfolio Demo')
    print('=' * 65)

    # ---- Step 1: collect snapshots ----
    by_ticker = await collect_snapshots()
    all_snaps = [s for snaps in by_ticker.values() for s in snaps]

    if not all_snaps:
        print('ERROR: No snapshots collected. Run generate_sample.py first.')
        return

    # ---- Step 2: train agents ----
    oracle     = OracleAgent()
    analyst    = AnalystAgent()
    guardian   = GuardianAgent()
    strategist = StrategistAgent()

    print('\n[ORACLE] Training LSTM on snapshot history...')
    oracle.train(by_ticker, epochs=50)

    print('\n[GUARDIAN] Training Autoencoder on normal snapshots...')
    n80 = int(len(all_snaps) * 0.8)
    guardian.train(all_snaps[:n80], epochs=100)

    # Build oracle + analyst signals over all_snaps for strategist training
    print('\n[SIGNALS] Pre-computing oracle + analyst signals for PPO training...')
    oracle_sigs  = []
    analyst_sigs = []
    for snap in all_snaps:
        ticker = snap.get('ticker', 'AAPL')
        oracle_sigs.append(oracle.predict(ticker, snap))
        analyst_sigs.append(analyst.predict(ticker, snap.get('timestamp_ns', 0)))

    print('\n[STRATEGIST] Training PPO agent...')
    strategist.train(all_snaps, oracle_sigs, analyst_sigs, total_timesteps=20_000)

    # ---- Step 3: Demo inference loop ----
    print('\n' + '=' * 65)
    print('  INFERENCE DEMO  (100 iterations)')
    print('=' * 65)

    store     = SignalsStore()
    portfolio = Portfolio(initial_capital=10_000.0)

    # Use last DEMO_ITERS snapshots cycling over tickers
    demo_snaps_by_ticker = {t: snaps[-DEMO_ITERS:] for t, snaps in by_ticker.items()}
    max_len = max(len(v) for v in demo_snaps_by_ticker.values())

    # Track per-ticker position for the demo portfolio
    position:  dict[str, int]   = defaultdict(int)
    avg_price: dict[str, float] = defaultdict(float)

    for i in range(min(DEMO_ITERS, max_len)):
        for ticker in TICKERS:
            snaps = demo_snaps_by_ticker.get(ticker, [])
            if not snaps:
                continue
            snap = snaps[i % len(snaps)]
            ts   = snap.get('timestamp_ns', 0)
            mid  = _mid_price(snap)

            # Get signals
            a_sig = analyst.predict(ticker, ts)
            o_sig = oracle.predict(ticker, snap)
            g_sig = guardian.predict(snap)

            obs = {
                'snapshot':      snap,
                'oracle':        o_sig,
                'analyst':       a_sig,
                'position':      position[ticker],
                'avg_buy_price': avg_price[ticker],
                'cash':          portfolio.cash,
                'timestamp_ns':  ts,
            }
            s_sig = strategist.predict(obs)

            # Update signals store
            store.update_oracle(ticker, o_sig)
            store.update_analyst(ticker, a_sig)
            store.update_strategist(ticker, s_sig)
            store.update_guardian(ticker, g_sig)

            # Print signal table every 25 iterations for first ticker
            if i % 25 == 0 and ticker == TICKERS[0]:
                _print_signal_table(ticker, a_sig, o_sig, s_sig, g_sig)

            # Execute portfolio trades
            action = s_sig.get('action', 'Hold')
            if g_sig.get('halt_signal'):
                action = 'Hold'   # guardian override

            if action == 'Buy' and portfolio.cash >= mid * 10:
                result = portfolio.buy(ticker, 10, mid)
                if result['success']:
                    position[ticker] += 10
                    # update avg price
                    total = position[ticker]
                    avg_price[ticker] = (
                        avg_price[ticker] * (total - 10) + mid * 10
                    ) / total
                    if i % 25 == 0:
                        print(f'    → BUY  10 {ticker} @ ${mid:.2f}')
            elif action == 'Sell' and position[ticker] >= 10:
                result = portfolio.sell(ticker, 10, mid)
                if result['success']:
                    position[ticker] -= 10
                    if position[ticker] == 0:
                        avg_price[ticker] = 0.0
                    if i % 25 == 0:
                        print(f'    → SELL 10 {ticker} @ ${mid:.2f}  '
                              f'PnL={result["pnl"]:+.2f}')

    # ---- Step 4: Final portfolio valuation ----
    print('\n' + '=' * 65)
    print('  FINAL PORTFOLIO VALUATION')
    print('=' * 65)

    # Get last known mid prices
    current_prices = {}
    for ticker, snaps in by_ticker.items():
        if snaps:
            current_prices[ticker] = _mid_price(snaps[-1])

    val = portfolio.current_valuation(current_prices)

    print(f'\n  Initial Capital  : ${val["initial_capital"]:>10,.2f}')
    print(f'  Cash Remaining   : ${val["cash"]:>10,.2f}')
    print(f'  Position Value   : ${val["total_position_value"]:>10,.2f}')
    print(f'  Total Value      : ${val["total_portfolio_value"]:>10,.2f}')
    sign = '+' if val['total_pnl'] >= 0 else ''
    print(f'  Total PnL        : {sign}${val["total_pnl"]:>9.2f}  '
          f'({sign}{val["total_pnl_pct"]:.2f}%)')
    print(f'  Realized PnL     : ${val["realized_pnl"]:>+10.2f}')

    if val['positions']:
        print('\n  Open Positions:')
        for ticker, pos in val['positions'].items():
            upnl = pos['unrealized_pnl']
            upct = pos['unrealized_pnl_pct']
            sign2 = '+' if upnl >= 0 else ''
            print(f'    {ticker:6s}  {pos["shares"]:4d} shares  '
                  f'avg=${pos["avg_buy_price"]:.2f}  '
                  f'now=${pos["current_price"]:.2f}  '
                  f'uPnL={sign2}${upnl:.2f} ({sign2}{upct:.1f}%)')

    if val['best_performer']:
        print(f'\n  Best performer   : {val["best_performer"]}')
    if val['worst_performer']:
        print(f'  Worst performer  : {val["worst_performer"]}')

    print(f'\n  Trades executed  : {len(portfolio.trade_history)}')

    portfolio.save(PORTFOLIO_PATH)
    print(f'\n  Portfolio saved → {PORTFOLIO_PATH}')
    print('\n  [*] Phase 2 complete.')


if __name__ == '__main__':
    asyncio.run(main())
