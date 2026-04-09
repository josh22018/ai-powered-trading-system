"""
Analyst agent — async coroutine that reads order-book snapshots and
computes technical indicators, writing results to the shared EngineState.

Runs on a configurable poll interval (default 0.5 s) and processes
the latest batch of snapshots from the RingBuffer.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from agents.analyst.indicators import (
    order_imbalance,
    spread_pct,
    update_ema,
    update_vwap,
)
from shared.state import EngineState, IndicatorSnapshot

log = logging.getLogger(__name__)


class AnalystAgent:
    """
    Reads raw order-book snapshots from EngineState.snapshots and
    derives IndicatorSnapshot objects stored in EngineState.indicators.

    Per-ticker EMA and VWAP state is maintained internally across ticks.
    """

    def __init__(
        self,
        state: EngineState,
        poll_interval: float = 0.5,
        ema_alpha: float = 0.12,
    ) -> None:
        """
        Initialise the Analyst agent.

        Args:
            state:         Shared EngineState.
            poll_interval: Seconds between indicator updates.
            ema_alpha:     EMA smoothing factor (0 < alpha < 1).
        """
        self._state         = state
        self._poll_interval = poll_interval
        self._ema_alpha     = ema_alpha

        # Per-ticker persistent state for stateful indicators
        self._ema_state:  Dict[str, Dict[str, float]] = {}
        self._vwap_state: Dict[str, Dict[str, float]] = {}

    async def run(self) -> None:
        """
        Main async loop — runs indefinitely until the task is cancelled.

        On each tick, processes all tickers that have a raw snapshot in
        EngineState.snapshots and writes IndicatorSnapshots to state.
        """
        log.info('Analyst agent started.')
        self._state.emit('analyst', 'Agent started.')

        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                log.info('Analyst agent cancelled.')
                self._state.emit('analyst', 'Agent stopped.')
                return
            except Exception as exc:
                log.warning('Analyst tick error: %s', exc)
            await asyncio.sleep(self._poll_interval)

    async def _tick(self) -> None:
        """Process one round of indicator updates for all available tickers."""
        async with self._state.lock_snapshots:
            snapshots = dict(self._state.snapshots)

        if not snapshots:
            return

        new_indicators: Dict[str, IndicatorSnapshot] = {}

        for ticker, snap in snapshots.items():
            mid = snap.get('mid_price')
            if mid is None:
                continue

            # Initialise per-ticker state dicts on first visit
            if ticker not in self._ema_state:
                self._ema_state[ticker]  = {}
                self._vwap_state[ticker] = {}

            ema, momentum = update_ema(
                mid, self._ema_state[ticker], alpha=self._ema_alpha
            )
            vwap = update_vwap(snap, self._vwap_state[ticker])
            imb  = order_imbalance(snap)
            sprd = spread_pct(snap)

            bids = snap.get('bids', [])
            asks = snap.get('asks', [])
            best_bid = bids[0][0] if bids else None
            best_ask = asks[0][0] if asks else None

            new_indicators[ticker] = IndicatorSnapshot(
                ticker=ticker,
                timestamp_ns=snap.get('timestamp_ns', 0),
                mid_price=mid,
                best_bid=best_bid,
                best_ask=best_ask,
                spread=snap.get('spread'),
                spread_pct=sprd,
                order_imbalance=imb,
                bid_volume=snap.get('total_bid_volume', 0),
                ask_volume=snap.get('total_ask_volume', 0),
                ema_price=ema,
                momentum=momentum,
                vwap=vwap,
            )

        async with self._state.lock_indicators:
            self._state.indicators.update(new_indicators)

        self._state.agent_ticks['analyst'] += 1
