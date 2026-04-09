"""
Oracle agent — async coroutine that consumes IndicatorSnapshots from
EngineState and produces directional trading signals.

Runs on a configurable poll interval (default 0.5 s).
Signals are written to EngineState.signals and appended to
EngineState.signal_history for trend analysis.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict

from agents.oracle.signals import classify_signal
from shared.state import EngineState, Signal

log = logging.getLogger(__name__)

# Minimum consecutive ticks with same direction before emitting a signal
MIN_CONFIRM_TICKS = 2


class OracleAgent:
    """
    Reads IndicatorSnapshots and classifies them into BUY/SELL/HOLD signals.

    Uses a simple confirmation filter: a directional signal must appear
    in at least MIN_CONFIRM_TICKS consecutive evaluations before it is
    promoted to the state.  HOLD signals are always written immediately.
    """

    def __init__(
        self,
        state: EngineState,
        poll_interval: float = 0.6,
    ) -> None:
        """
        Initialise the Oracle agent.

        Args:
            state:         Shared EngineState.
            poll_interval: Seconds between signal evaluations.
        """
        self._state         = state
        self._poll_interval = poll_interval

        # Per-ticker pending confirmation: {ticker: (direction, tick_count)}
        self._pending: Dict[str, tuple] = {}

    async def run(self) -> None:
        """Main async loop — runs until cancelled."""
        log.info('Oracle agent started.')
        self._state.emit('oracle', 'Agent started.')

        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                log.info('Oracle agent cancelled.')
                self._state.emit('oracle', 'Agent stopped.')
                return
            except Exception as exc:
                log.warning('Oracle tick error: %s', exc)
            await asyncio.sleep(self._poll_interval)

    async def _tick(self) -> None:
        """Evaluate indicators for all tickers and update signals."""
        async with self._state.lock_indicators:
            indicators = dict(self._state.indicators)

        if not indicators:
            return

        new_signals: Dict[str, Signal] = {}

        for ticker, ind in indicators.items():
            candidate = classify_signal(ticker, ind)

            if candidate.direction == 'HOLD':
                # Always accept HOLD immediately — clears pending
                self._pending.pop(ticker, None)
                new_signals[ticker] = candidate
            else:
                # Confirmation filter
                prev_dir, count = self._pending.get(ticker, ('', 0))
                if prev_dir == candidate.direction:
                    count += 1
                else:
                    count = 1
                self._pending[ticker] = (candidate.direction, count)

                if count >= MIN_CONFIRM_TICKS:
                    new_signals[ticker] = candidate
                    self._state.emit(
                        'oracle',
                        f'{ticker}: {candidate.direction} '
                        f'conf={candidate.confidence:.2f}  {candidate.reason}',
                    )

        async with self._state.lock_signals:
            self._state.signals.update(new_signals)
            for ticker, sig in new_signals.items():
                self._state.signal_history[ticker].append(sig)

        self._state.agent_ticks['oracle'] += 1
