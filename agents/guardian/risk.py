"""
Risk rule definitions for the Guardian agent.

Rules are evaluated in order; the first breach halts trading for that ticker.
All thresholds are intentionally conservative for a prototype engine.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from shared.state import EngineState, Position, RiskStatus

# ---------------------------------------------------------------------------
# Risk limits (tunable constants)
# ---------------------------------------------------------------------------

MAX_POSITION_VALUE   = 50_000.0    # max market value of any single position ($)
MAX_TOTAL_DRAWDOWN   = -10.0       # max portfolio drawdown (%)
MAX_SPREAD_PCT_TRADE = 1.5         # don't enter when spread > 1.5% of mid
MIN_CONFIDENCE       = 0.45        # minimum oracle confidence to trade
MAX_TRADES_PER_TICKER = 20         # circuit breaker: max trades per ticker


# ---------------------------------------------------------------------------
# Individual rule functions
# ---------------------------------------------------------------------------

def check_position_size(
    pos: Optional[Position],
    mid_price: float,
) -> Tuple[bool, str]:
    """
    Return (breach, reason) if position market value exceeds MAX_POSITION_VALUE.
    """
    if pos is None:
        return False, ''
    value = pos.shares * mid_price
    if value > MAX_POSITION_VALUE:
        return True, f'Position value ${value:,.0f} > limit ${MAX_POSITION_VALUE:,.0f}'
    return False, ''


def check_portfolio_drawdown(state: EngineState) -> Tuple[bool, str]:
    """Return (breach, reason) if total portfolio drawdown exceeds limit."""
    dd = state.total_drawdown_pct
    if dd < MAX_TOTAL_DRAWDOWN:
        return True, f'Portfolio drawdown {dd:.1f}% < limit {MAX_TOTAL_DRAWDOWN:.1f}%'
    return False, ''


def check_spread(spread_pct: Optional[float]) -> Tuple[bool, str]:
    """Return (breach, reason) if bid-ask spread is too wide to trade safely."""
    if spread_pct is None:
        return False, ''
    if spread_pct > MAX_SPREAD_PCT_TRADE:
        return True, f'Spread {spread_pct:.2f}% > limit {MAX_SPREAD_PCT_TRADE:.2f}%'
    return False, ''


def check_trade_count(pos: Optional[Position]) -> Tuple[bool, str]:
    """Return (breach, reason) if trade count circuit breaker is triggered."""
    if pos is None:
        return False, ''
    if pos.trade_count >= MAX_TRADES_PER_TICKER:
        return True, f'Trade count {pos.trade_count} ≥ limit {MAX_TRADES_PER_TICKER}'
    return False, ''


# ---------------------------------------------------------------------------
# Aggregate evaluator
# ---------------------------------------------------------------------------

def evaluate_risk(
    ticker: str,
    state: EngineState,
    spread_pct: Optional[float],
) -> RiskStatus:
    """
    Run all risk rules for a single ticker and return an updated RiskStatus.

    Args:
        ticker:     Ticker symbol to evaluate.
        state:      Full engine state.
        spread_pct: Current bid-ask spread as % of mid price.

    Returns:
        RiskStatus with halted=True and halt_reason set if any rule fires.
    """
    rs     = RiskStatus(ticker=ticker)
    pos    = state.positions.get(ticker)
    ind    = state.indicators.get(ticker)
    mid    = ind.mid_price if ind else 0.0

    checks: List[Tuple[bool, str]] = [
        check_position_size(pos, mid),
        check_portfolio_drawdown(state),
        check_spread(spread_pct),
        check_trade_count(pos),
    ]

    for breached, reason in checks:
        if breached:
            rs.halted      = True
            rs.halt_reason = reason
            break

    rs.drawdown_pct = state.total_drawdown_pct
    if pos:
        rs.max_position_breach = (pos.shares * mid) > MAX_POSITION_VALUE

    return rs
