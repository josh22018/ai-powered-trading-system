"""
Central in-memory state store for the Kairos X trading engine.

All agents (analyst, oracle, strategist, guardian) and the dashboard
backend read from and write to this module.  Every mutable collection
is protected by an asyncio.Lock so coroutines can await safe access.

State hierarchy:
    per-ticker   → market snapshots, indicators, signals, positions
    global       → portfolio summary, risk status, engine log
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional


# ---------------------------------------------------------------------------
# Dataclasses stored in state
# ---------------------------------------------------------------------------

@dataclass
class IndicatorSnapshot:
    """Output of the Analyst agent for one ticker at one point in time."""
    ticker: str
    timestamp_ns: int
    mid_price: float
    best_bid: Optional[float]
    best_ask: Optional[float]
    spread: Optional[float]
    spread_pct: Optional[float]
    order_imbalance: float      # -1.0 (full ask) … +1.0 (full bid)
    bid_volume: int
    ask_volume: int
    ema_price: float            # short-term EMA of mid price
    momentum: float             # mid_price - ema_price
    vwap: float                 # cumulative VWAP approximation


@dataclass
class Signal:
    """Trading signal produced by the Oracle agent."""
    ticker: str
    timestamp: float            # wall-clock time (time.time())
    direction: str              # 'BUY' | 'SELL' | 'HOLD'
    confidence: float           # 0.0 – 1.0
    score: float                # raw composite score
    reason: str                 # human-readable explanation


@dataclass
class Position:
    """Virtual position held by the Strategist."""
    ticker: str
    side: str                   # 'LONG' | 'SHORT'
    shares: int
    entry_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    open_time: float = field(default_factory=time.time)
    trade_count: int = 0


@dataclass
class RiskStatus:
    """Per-ticker risk state from the Guardian agent."""
    ticker: str
    halted: bool = False        # trading halted for this ticker
    halt_reason: str = ''
    max_position_breach: bool = False
    drawdown_pct: float = 0.0
    last_check: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Central state store
# ---------------------------------------------------------------------------

class EngineState:
    """
    Singleton-style shared state for the entire Kairos X engine.

    All reads and writes should go through the public async methods or
    use the provided asyncio.Lock objects when doing multi-step updates.
    """

    def __init__(self, tickers: List[str]) -> None:
        """Initialise empty state for the given list of tickers."""
        self.tickers: List[str] = tickers

        # Market data (from feed)
        self.snapshots: Dict[str, Dict[str, Any]] = {}      # raw OB snapshots

        # Agent outputs
        self.indicators: Dict[str, IndicatorSnapshot] = {}
        self.signals: Dict[str, Signal] = {}
        self.positions: Dict[str, Optional[Position]] = {t: None for t in tickers}
        self.risk: Dict[str, RiskStatus] = {
            t: RiskStatus(ticker=t) for t in tickers
        }

        # Portfolio
        self.initial_capital: float = 100_000.0
        self.cash: float = 100_000.0
        self.realized_pnl_total: float = 0.0

        # User investment simulations
        self.user_investments: List[Dict[str, Any]] = []

        # Signal history (rolling 200 entries per ticker)
        self.signal_history: Dict[str, Deque[Signal]] = {
            t: deque(maxlen=200) for t in tickers
        }

        # Engine log (rolling 500 lines)
        self.log: Deque[str] = deque(maxlen=500)

        # Agent liveness counters
        self.agent_ticks: Dict[str, int] = {
            'analyst': 0, 'oracle': 0, 'strategist': 0, 'guardian': 0,
        }

        # Asyncio locks
        self.lock_snapshots    = asyncio.Lock()
        self.lock_indicators   = asyncio.Lock()
        self.lock_signals      = asyncio.Lock()
        self.lock_positions    = asyncio.Lock()
        self.lock_risk         = asyncio.Lock()
        self.lock_portfolio    = asyncio.Lock()
        self.lock_investments  = asyncio.Lock()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def emit(self, agent: str, msg: str) -> None:
        """Append a timestamped log line from an agent."""
        ts = time.strftime('%H:%M:%S')
        self.log.append(f'[{ts}] [{agent}] {msg}')

    @property
    def total_unrealized_pnl(self) -> float:
        """Sum of unrealized P&L across all open positions."""
        return sum(
            p.unrealized_pnl for p in self.positions.values() if p is not None
        )

    @property
    def equity(self) -> float:
        """Current equity = cash + unrealized P&L."""
        return self.cash + self.total_unrealized_pnl

    @property
    def total_drawdown_pct(self) -> float:
        """Drawdown as % of initial capital (negative = loss)."""
        return (self.equity - self.initial_capital) / self.initial_capital * 100

    def to_dict(self) -> Dict[str, Any]:
        """Serialise full state to a JSON-friendly dict for the dashboard."""

        def _sig(s: Optional[Signal]) -> Optional[Dict]:
            if s is None:
                return None
            return {
                'ticker': s.ticker, 'direction': s.direction,
                'confidence': round(s.confidence, 4),
                'score': round(s.score, 4), 'reason': s.reason,
                'timestamp': s.timestamp,
            }

        def _ind(i: Optional[IndicatorSnapshot]) -> Optional[Dict]:
            if i is None:
                return None
            return {
                'ticker': i.ticker,
                'mid_price': round(i.mid_price, 4),
                'best_bid': round(i.best_bid, 4) if i.best_bid else None,
                'best_ask': round(i.best_ask, 4) if i.best_ask else None,
                'spread': round(i.spread, 4) if i.spread else None,
                'spread_pct': round(i.spread_pct, 4) if i.spread_pct else None,
                'order_imbalance': round(i.order_imbalance, 4),
                'bid_volume': i.bid_volume,
                'ask_volume': i.ask_volume,
                'ema_price': round(i.ema_price, 4),
                'momentum': round(i.momentum, 4),
                'vwap': round(i.vwap, 4),
                'timestamp_ns': i.timestamp_ns,
            }

        def _pos(p: Optional[Position]) -> Optional[Dict]:
            if p is None:
                return None
            return {
                'ticker': p.ticker, 'side': p.side, 'shares': p.shares,
                'entry_price': round(p.entry_price, 4),
                'current_price': round(p.current_price, 4),
                'unrealized_pnl': round(p.unrealized_pnl, 2),
                'realized_pnl': round(p.realized_pnl, 2),
                'trade_count': p.trade_count,
            }

        def _risk(r: RiskStatus) -> Dict:
            return {
                'ticker': r.ticker, 'halted': r.halted,
                'halt_reason': r.halt_reason,
                'max_position_breach': r.max_position_breach,
                'drawdown_pct': round(r.drawdown_pct, 2),
            }

        current_equity = self.equity

        def _inv(inv: Dict[str, Any]) -> Dict[str, Any]:
            eq_at = inv['engine_equity_at_invest']
            ratio = (current_equity / eq_at) if eq_at > 0 else 1.0
            current_val = round(inv['amount'] * ratio, 2)
            pnl = round(current_val - inv['amount'], 2)
            return {
                'id': inv['id'],
                'amount': inv['amount'],
                'invested_at': inv['invested_at'],
                'current_value': current_val,
                'pnl': pnl,
                'roi_pct': round((ratio - 1.0) * 100, 2),
            }

        return {
            'tickers': self.tickers,
            'snapshots': self.snapshots,
            'indicators': {t: _ind(self.indicators.get(t)) for t in self.tickers},
            'signals': {t: _sig(self.signals.get(t)) for t in self.tickers},
            'positions': {t: _pos(self.positions.get(t)) for t in self.tickers},
            'risk': {t: _risk(self.risk[t]) for t in self.tickers},
            'portfolio': {
                'cash': round(self.cash, 2),
                'equity': round(self.equity, 2),
                'unrealized_pnl': round(self.total_unrealized_pnl, 2),
                'realized_pnl': round(self.realized_pnl_total, 2),
                'drawdown_pct': round(self.total_drawdown_pct, 2),
                'initial_capital': self.initial_capital,
            },
            'investments': [_inv(i) for i in list(self.user_investments)],
            'agent_ticks': dict(self.agent_ticks),
            'log': list(self.log)[-50:],   # last 50 lines only
        }
