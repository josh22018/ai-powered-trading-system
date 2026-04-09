"""
SignalsStore — thread-safe in-memory store for latest agent signals.

Used by the Phase 3 backend API to serve current signals without
blocking the agent inference loop.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Dict, Optional


class SignalsStore:
    """
    Thread-safe, per-ticker store for the latest signal from each agent.

    Structure:
        {ticker: {agent_name: signal_dict, ...}, ...}
    """

    def __init__(self) -> None:
        self._lock  = threading.Lock()
        self._store: Dict[str, Dict[str, dict]] = {}
        self.last_updated: Optional[datetime] = None

    def _set(self, agent: str, ticker: str, signal: dict) -> None:
        with self._lock:
            if ticker not in self._store:
                self._store[ticker] = {}
            self._store[ticker][agent] = signal
            self.last_updated = datetime.utcnow()

    def update_oracle(self, ticker: str, signal_dict: dict) -> None:
        """Store the latest Oracle signal for ticker."""
        self._set('oracle', ticker, signal_dict)

    def update_analyst(self, ticker: str, signal_dict: dict) -> None:
        """Store the latest Analyst signal for ticker."""
        self._set('analyst', ticker, signal_dict)

    def update_strategist(self, ticker: str, signal_dict: dict) -> None:
        """Store the latest Strategist signal for ticker."""
        self._set('strategist', ticker, signal_dict)

    def update_guardian(self, ticker: str, signal_dict: dict) -> None:
        """Store the latest Guardian signal for ticker."""
        self._set('guardian', ticker, signal_dict)

    def get_all(self) -> dict:
        """Return a copy of the full signals store."""
        with self._lock:
            return {
                ticker: dict(agents)
                for ticker, agents in self._store.items()
            }

    def get_ticker(self, ticker: str) -> dict:
        """Return signals for a single ticker (empty dict if unknown)."""
        with self._lock:
            return dict(self._store.get(ticker, {}))
