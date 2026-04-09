"""
Position management utilities for the Strategist agent.

Provides helpers for opening, closing, and marking-to-market virtual
positions without any real order routing.
"""

from __future__ import annotations

from typing import Optional, Tuple

from shared.state import EngineState, Position

# Simulated round-trip transaction cost per share (spread approximation)
TRANSACTION_COST_PER_SHARE = 0.01   # $0.01 per share
POSITION_SIZE_SHARES        = 100   # fixed lot size for every trade


def open_position(
    state: EngineState,
    ticker: str,
    side: str,
    price: float,
) -> Optional[Position]:
    """
    Open a new virtual position for ticker.

    Args:
        state:  Shared EngineState (modified in place).
        ticker: Ticker symbol.
        side:   'LONG' or 'SHORT'.
        price:  Simulated fill price (typically mid-price).

    Returns:
        The new Position, or None if a position is already open.
    """
    if state.positions.get(ticker) is not None:
        return None

    cost = POSITION_SIZE_SHARES * price + POSITION_SIZE_SHARES * TRANSACTION_COST_PER_SHARE
    if state.cash < cost and side == 'LONG':
        return None   # insufficient cash

    pos = Position(
        ticker=ticker,
        side=side,
        shares=POSITION_SIZE_SHARES,
        entry_price=price,
        current_price=price,
    )
    state.positions[ticker] = pos
    if side == 'LONG':
        state.cash -= cost
    return pos


def close_position(
    state: EngineState,
    ticker: str,
    price: float,
) -> Tuple[Optional[float], str]:
    """
    Close an existing virtual position and update cash + realized P&L.

    Args:
        state:  Shared EngineState (modified in place).
        ticker: Ticker symbol.
        price:  Simulated exit price.

    Returns:
        (realized_pnl, summary_string) — pnl is None if no position existed.
    """
    pos = state.positions.get(ticker)
    if pos is None:
        return None, 'No open position'

    tc   = POSITION_SIZE_SHARES * TRANSACTION_COST_PER_SHARE
    sign = 1 if pos.side == 'LONG' else -1
    pnl  = sign * pos.shares * (price - pos.entry_price) - tc

    pos.realized_pnl += pnl
    state.realized_pnl_total += pnl
    pos.trade_count  += 1

    # Return cash for LONG (we receive sale proceeds)
    if pos.side == 'LONG':
        state.cash += pos.shares * price - tc
    else:
        # SHORT: we return borrowed shares at current price
        state.cash += sign * pos.shares * (pos.entry_price - price) - tc

    state.positions[ticker] = None
    summary = (
        f'{ticker} {pos.side} closed @ ${price:.2f}  '
        f'entry=${pos.entry_price:.2f}  pnl=${pnl:+.2f}'
    )
    return pnl, summary


def mark_to_market(state: EngineState, ticker: str, price: float) -> None:
    """
    Update the unrealized P&L of an open position at the current price.

    Args:
        state:  Shared EngineState (modified in place).
        ticker: Ticker symbol.
        price:  Current mid price.
    """
    pos = state.positions.get(ticker)
    if pos is None:
        return
    sign              = 1 if pos.side == 'LONG' else -1
    pos.current_price = price
    pos.unrealized_pnl = sign * pos.shares * (price - pos.entry_price)
