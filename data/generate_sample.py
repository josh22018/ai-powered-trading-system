"""
Synthetic NASDAQ ITCH 5.0 data generator for Kairos X testing.

Produces ~/kairos-x/data/sample.NASDAQ_ITCH50 with ~5000 messages
covering three tickers (AAPL, MSFT, GOOGL).

Message mix:
  55% Add Order (A)
  20% Delete Order (D)
  15% Execute Order (E)
  10% Cancel Order (X)
  + System Event (S) at start/end
  + Stock Directory (R) for each ticker

All messages are framed with a 2-byte big-endian length prefix as per
the ITCH 5.0 spec.  random.seed(42) ensures reproducibility.
"""

from __future__ import annotations

import random
import struct
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
random.seed(42)

OUTPUT = Path.home() / 'kairos-x' / 'data' / 'sample.NASDAQ_ITCH50'
TARGET_ORDER_MSGS = 8000   # more messages for richer chart history

# Ticker config: symbol → (stock_locate_id, baseline_price_cents*10000)
TICKERS = {
    'AAPL':  (1, 1_500_000),   # $150.0000
    'MSFT':  (2, 3_000_000),   # $300.0000
    'GOOGL': (3, 1_400_000),   # $140.0000
}

# Price walk parameters — produce visible bull/bear swings
TREND_DRIFT  = 0.0006   # 0.06% drift per message in trend direction
NOISE_SIGMA  = 0.004    # 0.4% Gaussian noise per message (much higher than old ±2% flat jitter)
ORDER_JITTER = 0.003    # ±0.3% order-level spread around the walk price

# ---------------------------------------------------------------------------
# Struct helpers — all big-endian, match ITCH 5.0 field widths exactly
# ---------------------------------------------------------------------------

def _pack_ts(ns: int) -> bytes:
    """Pack nanosecond timestamp into 6-byte big-endian bytes."""
    return ns.to_bytes(6, 'big')


def _pad_stock(sym: str) -> bytes:
    """Right-pad stock symbol with spaces to 8 bytes."""
    return sym.encode('ascii').ljust(8)


# ---- System Event (S) ----
# msg_type(1) + locate(2) + tracking(2) + ts(6) + event_code(1) = 12
_FMT_S = struct.Struct('>cHH6sc')


def build_system_event(ts_ns: int, code: str) -> bytes:
    """Build a System Event message body."""
    return _FMT_S.pack(b'S', 0, 0, _pack_ts(ts_ns), code.encode('ascii'))


# ---- Stock Directory (R) ----
# msg_type(1)+locate(2)+tracking(2)+ts(6)+stock(8)+market_cat(1)+
# fin_status(1)+round_lot(4)+round_lots_only(1)+issue_class(1)+
# issue_sub(2)+auth(1)+short_sale(1)+ipo_flag(1)+luld_tier(1)+
# etp_flag(1)+etp_leverage(4)+inverse(1) = 39
_FMT_R = struct.Struct('>cHH6s8sccIcc2scccccIc')


def build_stock_directory(ts_ns: int, locate: int, symbol: str) -> bytes:
    """Build a Stock Directory message body for the given ticker."""
    return _FMT_R.pack(
        b'R', locate, 0, _pack_ts(ts_ns),
        _pad_stock(symbol),
        b'Q',   # market_category = NASDAQ Global Select
        b'N',   # financial_status_indicator = Normal
        100,    # round_lot_size
        b'N',   # round_lots_only
        b'C',   # issue_classification = Common Stock
        b'  ',  # issue_sub_type
        b'P',   # authenticity = Production
        b' ',   # short_sale_threshold_indicator
        b' ',   # IPO_flag
        b' ',   # LULD_reference_price_tier
        b'N',   # ETP_flag
        1,      # ETP_leverage_factor
        b'N',   # inverse_indicator
    )


# ---- Add Order (A) ----
# msg_type(1)+locate(2)+tracking(2)+ts(6)+order_ref(8)+side(1)+
# shares(4)+stock(8)+price(4) = 36
_FMT_A = struct.Struct('>cHH6sQcI8sI')


def build_add_order(ts_ns: int, locate: int, order_ref: int,
                    side: str, shares: int, symbol: str, price: int) -> bytes:
    """Build an Add Order (A) message body."""
    return _FMT_A.pack(
        b'A', locate, 0, _pack_ts(ts_ns),
        order_ref,
        side.encode('ascii'),
        shares,
        _pad_stock(symbol),
        price,
    )


# ---- Delete Order (D) ----
# msg_type(1)+locate(2)+tracking(2)+ts(6)+order_ref(8) = 19
_FMT_D = struct.Struct('>cHH6sQ')


def build_delete_order(ts_ns: int, locate: int, order_ref: int) -> bytes:
    """Build a Delete Order (D) message body."""
    return _FMT_D.pack(b'D', locate, 0, _pack_ts(ts_ns), order_ref)


# ---- Execute Order (E) ----
# msg_type(1)+locate(2)+tracking(2)+ts(6)+order_ref(8)+
# executed(4)+match(8) = 31
_FMT_E = struct.Struct('>cHH6sQIQ')


def build_execute_order(ts_ns: int, locate: int, order_ref: int,
                        executed: int, match: int) -> bytes:
    """Build an Execute Order (E) message body."""
    return _FMT_E.pack(b'E', locate, 0, _pack_ts(ts_ns),
                       order_ref, executed, match)


# ---- Cancel Order (X) ----
# msg_type(1)+locate(2)+tracking(2)+ts(6)+order_ref(8)+cancelled(4) = 23
_FMT_X = struct.Struct('>cHH6sQI')


def build_cancel_order(ts_ns: int, locate: int, order_ref: int,
                       cancelled: int) -> bytes:
    """Build a Cancel Order (X) message body."""
    return _FMT_X.pack(b'X', locate, 0, _pack_ts(ts_ns), order_ref, cancelled)


# ---------------------------------------------------------------------------
# Message framing
# ---------------------------------------------------------------------------

def frame(body: bytes) -> bytes:
    """Prepend a 2-byte big-endian length prefix to a message body."""
    return struct.pack('>H', len(body)) + body


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def generate() -> None:
    """Generate the synthetic ITCH file and write it to OUTPUT."""
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    # Per-ticker state: list of (order_ref, locate, shares) for live orders
    live_orders: dict[str, list] = {sym: [] for sym in TICKERS}

    # Per-ticker price walk: floats in same units as base_price (×10000)
    walk_price      = {sym: float(base) for sym, (_, base) in TICKERS.items()}
    walk_trend      = {sym: random.choice([-1.0, 1.0]) for sym in TICKERS}
    walk_trend_life = {sym: random.randint(150, 400) for sym in TICKERS}

    order_ref_counter = 1
    match_counter     = 1
    ts_ns             = 34_200_000_000_000   # 09:30:00.000 in ns since midnight

    messages: list[bytes] = []

    # ---- Session start ----
    messages.append(frame(build_system_event(ts_ns, 'O')))   # Start of Messages
    ts_ns += 1_000_000

    messages.append(frame(build_system_event(ts_ns, 'S')))   # Start of System Hours
    ts_ns += 1_000_000

    messages.append(frame(build_system_event(ts_ns, 'Q')))   # Start of Market Hours
    ts_ns += 1_000_000

    # ---- Stock Directory entries ----
    for sym, (locate, _) in TICKERS.items():
        messages.append(frame(build_stock_directory(ts_ns, locate, sym)))
        ts_ns += 100_000

    # ---- Order mix ----
    ticker_list  = list(TICKERS.keys())
    mix_weights  = [0.55, 0.20, 0.15, 0.10]   # Add, Delete, Execute, Cancel
    mix_types    = ['A', 'D', 'E', 'X']

    generated = 0
    while generated < TARGET_ORDER_MSGS:
        sym        = random.choice(ticker_list)
        locate, _ = TICKERS[sym]
        ts_ns     += random.randint(10_000, 500_000)   # 10µs–500µs between msgs
        msg_type   = random.choices(mix_types, mix_weights)[0]

        # Advance the price walk for this ticker every message
        walk_trend_life[sym] -= 1
        if walk_trend_life[sym] <= 0:
            walk_trend[sym]      = random.choice([-1.0, 1.0])
            walk_trend_life[sym] = random.randint(150, 400)
        noise = random.gauss(0, NOISE_SIGMA)
        drift = TREND_DRIFT * walk_trend[sym]
        walk_price[sym] = max(10_000.0, walk_price[sym] * (1.0 + drift + noise))

        if msg_type == 'A' or not live_orders[sym]:
            # Always add if book is empty
            side   = random.choice(['B', 'S'])
            # Tight jitter around the trending walk price
            jitter = random.uniform(-ORDER_JITTER, ORDER_JITTER)
            price  = max(1, int(walk_price[sym] * (1.0 + jitter)))
            shares = random.choice([100, 200, 300, 500, 1000])
            ref    = order_ref_counter
            order_ref_counter += 1

            messages.append(frame(
                build_add_order(ts_ns, locate, ref, side, shares, sym, price)
            ))
            live_orders[sym].append((ref, locate, shares))
            generated += 1

        elif msg_type == 'D' and live_orders[sym]:
            idx     = random.randrange(len(live_orders[sym]))
            ref, loc, _ = live_orders[sym].pop(idx)
            messages.append(frame(build_delete_order(ts_ns, loc, ref)))
            generated += 1

        elif msg_type == 'E' and live_orders[sym]:
            idx     = random.randrange(len(live_orders[sym]))
            ref, loc, shares = live_orders[sym][idx]
            executed = random.randint(1, shares)
            match    = match_counter
            match_counter += 1
            messages.append(frame(
                build_execute_order(ts_ns, loc, ref, executed, match)
            ))
            remaining = shares - executed
            if remaining <= 0:
                live_orders[sym].pop(idx)
            else:
                live_orders[sym][idx] = (ref, loc, remaining)
            generated += 1

        elif msg_type == 'X' and live_orders[sym]:
            idx      = random.randrange(len(live_orders[sym]))
            ref, loc, shares = live_orders[sym][idx]
            cancelled = random.randint(1, shares)
            messages.append(frame(
                build_cancel_order(ts_ns, loc, ref, cancelled)
            ))
            remaining = shares - cancelled
            if remaining <= 0:
                live_orders[sym].pop(idx)
            else:
                live_orders[sym][idx] = (ref, loc, remaining)
            generated += 1

        else:
            # Fallback: generate an add
            side   = random.choice(['B', 'S'])
            jitter = random.uniform(-ORDER_JITTER, ORDER_JITTER)
            price  = max(1, int(walk_price[sym] * (1.0 + jitter)))
            shares = random.choice([100, 200, 300, 500, 1000])
            ref    = order_ref_counter
            order_ref_counter += 1
            messages.append(frame(
                build_add_order(ts_ns, locate, ref, side, shares, sym, price)
            ))
            live_orders[sym].append((ref, locate, shares))
            generated += 1

    # ---- Session end ----
    ts_ns += 5_000_000_000   # 5 second gap
    messages.append(frame(build_system_event(ts_ns, 'M')))   # End of Market Hours
    ts_ns += 1_000_000
    messages.append(frame(build_system_event(ts_ns, 'E')))   # End of System Hours
    ts_ns += 1_000_000
    messages.append(frame(build_system_event(ts_ns, 'C')))   # End of Messages

    # ---- Write file ----
    with open(OUTPUT, 'wb') as fh:
        for msg in messages:
            fh.write(msg)

    total = len(messages)
    size  = OUTPUT.stat().st_size
    print(f'Generated {OUTPUT}')
    print(f'  Total messages : {total:,}  (including system/directory)')
    print(f'  Order events   : {generated:,}')
    print(f'  File size      : {size:,} bytes  ({size / 1024:.1f} KB)')


if __name__ == '__main__':
    generate()
