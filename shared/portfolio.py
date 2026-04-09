"""
Portfolio tracker — virtual capital allocation and P&L tracking.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


class Portfolio:
    """
    Tracks virtual positions, cash, and trade history.

    Args:
        initial_capital: Starting cash in USD.
    """

    def __init__(self, initial_capital: float = 10_000.0) -> None:
        self.initial_capital  = initial_capital
        self.cash             = initial_capital
        self.positions: Dict[str, dict] = {}
        self.trade_history:  List[dict] = []
        self._realized_pnl   = 0.0
        self.created_at       = datetime.utcnow().isoformat()
        self._valuation_history: List[dict] = []

    # ------------------------------------------------------------------
    # Trading
    # ------------------------------------------------------------------

    def buy(self, ticker: str, shares: int, price: float) -> dict:
        """Buy shares of ticker at given price."""
        cost = shares * price
        if cost > self.cash:
            return {
                'success': False,
                'message': f'Insufficient cash: need ${cost:.2f}, have ${self.cash:.2f}',
                'cost':    cost,
            }

        self.cash -= cost

        if ticker in self.positions:
            pos = self.positions[ticker]
            total_shares   = pos['shares'] + shares
            total_invested = pos['total_invested'] + cost
            pos['avg_buy_price']  = total_invested / total_shares
            pos['shares']         = total_shares
            pos['total_invested'] = total_invested
        else:
            self.positions[ticker] = {
                'shares':         shares,
                'avg_buy_price':  price,
                'total_invested': cost,
            }

        self.trade_history.append({
            'action':    'BUY',
            'ticker':    ticker,
            'shares':    shares,
            'price':     price,
            'cost':      cost,
            'timestamp': datetime.utcnow().isoformat(),
        })
        return {'success': True, 'message': f'Bought {shares} {ticker} @ ${price:.2f}', 'cost': cost}

    def sell(self, ticker: str, shares: int, price: float) -> dict:
        """Sell shares of ticker at given price."""
        pos = self.positions.get(ticker)
        if pos is None or pos['shares'] < shares:
            held = pos['shares'] if pos else 0
            return {
                'success':  False,
                'message':  f'Insufficient shares: need {shares}, have {held}',
                'proceeds': 0.0,
                'pnl':      0.0,
            }

        proceeds = shares * price
        cost_basis = pos['avg_buy_price'] * shares
        pnl = proceeds - cost_basis

        self.cash += proceeds
        self._realized_pnl += pnl

        pos['shares']         -= shares
        pos['total_invested'] -= cost_basis
        if pos['shares'] == 0:
            del self.positions[ticker]

        self.trade_history.append({
            'action':    'SELL',
            'ticker':    ticker,
            'shares':    shares,
            'price':     price,
            'proceeds':  proceeds,
            'pnl':       pnl,
            'timestamp': datetime.utcnow().isoformat(),
        })
        return {
            'success':  True,
            'message':  f'Sold {shares} {ticker} @ ${price:.2f}  PnL=${pnl:+.2f}',
            'proceeds': proceeds,
            'pnl':      pnl,
        }

    # ------------------------------------------------------------------
    # Valuation
    # ------------------------------------------------------------------

    def current_valuation(self, current_prices: Dict[str, float]) -> dict:
        """Compute full portfolio valuation given a dict of current prices."""
        pos_detail: Dict[str, dict] = {}
        total_pos_value = 0.0
        best_ticker: Optional[str] = None
        worst_ticker: Optional[str] = None
        best_pct:  float = float('-inf')
        worst_pct: float = float('inf')

        for ticker, pos in self.positions.items():
            price   = current_prices.get(ticker, pos['avg_buy_price'])
            value   = pos['shares'] * price
            cost    = pos['total_invested']
            upnl    = value - cost
            upnl_pct = (upnl / cost * 100.0) if cost else 0.0
            total_pos_value += value

            pos_detail[ticker] = {
                'shares':              pos['shares'],
                'avg_buy_price':       pos['avg_buy_price'],
                'current_price':       price,
                'current_value':       value,
                'unrealized_pnl':      upnl,
                'unrealized_pnl_pct':  upnl_pct,
                'total_invested':      cost,
            }
            if upnl_pct > best_pct:
                best_pct    = upnl_pct
                best_ticker = ticker
            if upnl_pct < worst_pct:
                worst_pct    = upnl_pct
                worst_ticker = ticker

        total_value = self.cash + total_pos_value
        total_pnl   = total_value - self.initial_capital
        total_pnl_pct = (total_pnl / self.initial_capital * 100.0)

        valuation = {
            'initial_capital':      self.initial_capital,
            'cash':                 self.cash,
            'positions':            pos_detail,
            'total_position_value': total_pos_value,
            'total_portfolio_value': total_value,
            'total_pnl':            total_pnl,
            'total_pnl_pct':        total_pnl_pct,
            'realized_pnl':         self._realized_pnl,
            'best_performer':       best_ticker,
            'worst_performer':      worst_ticker,
        }
        self._valuation_history.append({**valuation, 'timestamp': datetime.utcnow().isoformat()})
        return valuation

    def portfolio_history(self) -> List[dict]:
        """Return list of all valuation snapshots computed so far."""
        return list(self._valuation_history)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            'initial_capital':   self.initial_capital,
            'cash':              self.cash,
            'positions':         self.positions,
            'trade_history':     self.trade_history,
            'realized_pnl':      self._realized_pnl,
            'created_at':        self.created_at,
            'valuation_history': self._valuation_history,
        }

    def save(self, path: str) -> None:
        """Save portfolio state to a JSON file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str) -> 'Portfolio':
        """Load portfolio state from a JSON file."""
        with open(path) as f:
            data = json.load(f)
        p = cls(initial_capital=data['initial_capital'])
        p.cash              = data['cash']
        p.positions         = data['positions']
        p.trade_history     = data['trade_history']
        p._realized_pnl     = data.get('realized_pnl', 0.0)
        p.created_at        = data.get('created_at', '')
        p._valuation_history = data.get('valuation_history', [])
        return p
