"""
Technical indicator computation for the Analyst agent.

All functions are pure (no side effects) and operate on raw order-book
snapshot dicts produced by OrderBook.snapshot().

Indicators computed:
  - order_imbalance   : signed bid/ask volume ratio  [-1, +1]
  - spread_pct        : bid-ask spread as % of mid price
  - momentum          : deviation of mid price from its short EMA
  - vwap              : running volume-weighted average price (stateful)
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Stateless indicators
# ---------------------------------------------------------------------------

def order_imbalance(snapshot: Dict[str, Any]) -> float:
    """
    Compute order-book imbalance from top-N bid/ask volumes.

    Returns a value in [-1.0, +1.0]:
        +1.0 = only bids (max buy pressure)
        -1.0 = only asks (max sell pressure)
         0.0 = perfectly balanced
    """
    bid_vol = snapshot.get('total_bid_volume', 0)
    ask_vol = snapshot.get('total_ask_volume', 0)
    total   = bid_vol + ask_vol
    if total == 0:
        return 0.0
    return (bid_vol - ask_vol) / total


def spread_pct(snapshot: Dict[str, Any]) -> Optional[float]:
    """
    Bid-ask spread expressed as a percentage of mid price.

    Returns None if mid_price is zero or unavailable.
    """
    mid    = snapshot.get('mid_price')
    spread = snapshot.get('spread')
    if mid is None or spread is None or mid == 0:
        return None
    return abs(spread) / mid * 100.0


# ---------------------------------------------------------------------------
# Stateful indicators  (callers hold persistent state dicts)
# ---------------------------------------------------------------------------

def update_ema(
    current_price: float,
    state: Dict[str, float],
    alpha: float = 0.1,
) -> Tuple[float, float]:
    """
    Update and return the exponential moving average of price.

    Args:
        current_price: Latest mid price.
        state:         Mutable dict with key 'ema' (initialised on first call).
        alpha:         Smoothing factor; smaller = slower EMA.

    Returns:
        (ema, momentum) where momentum = current_price - ema.
    """
    if 'ema' not in state:
        state['ema'] = current_price
    ema = alpha * current_price + (1.0 - alpha) * state['ema']
    state['ema'] = ema
    return ema, current_price - ema


def update_vwap(
    snapshot: Dict[str, Any],
    state: Dict[str, float],
) -> float:
    """
    Update and return the running VWAP approximation.

    Uses total visible volume (bid + ask) at the current mid price as a
    proxy for executed volume — sufficient for an order-book-only feed
    that lacks tick-level trade data.

    Args:
        snapshot: Raw OB snapshot dict.
        state:    Mutable dict with keys 'cum_vol' and 'cum_pv'.

    Returns:
        Current VWAP (float, USD).
    """
    mid    = snapshot.get('mid_price') or 0.0
    volume = (snapshot.get('total_bid_volume', 0) +
              snapshot.get('total_ask_volume', 0))

    if 'cum_pv' not in state:
        state['cum_pv']  = 0.0
        state['cum_vol'] = 0

    state['cum_pv']  += mid * volume
    state['cum_vol'] += volume

    if state['cum_vol'] == 0:
        return mid
    return state['cum_pv'] / state['cum_vol']
