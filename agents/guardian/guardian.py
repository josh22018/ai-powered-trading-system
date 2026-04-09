"""
Guardian agent — async coroutine that monitors risk rules and updates
EngineState.risk for every ticker on each tick.

If a risk breach is detected the Guardian:
  1. Sets RiskStatus.halted = True with a descriptive reason.
  2. Emits a log entry — the Strategist picks this up and liquidates.

The Guardian does NOT directly close positions; it only signals intent.
This preserves clean separation of concerns between agents.
"""

from __future__ import annotations

import asyncio
import logging

from agents.guardian.risk import evaluate_risk
from shared.state import EngineState

log = logging.getLogger(__name__)


class GuardianAgent:
    """
    Evaluates all risk rules for every ticker and publishes RiskStatus
    objects to EngineState.risk.
    """

    def __init__(
        self,
        state: EngineState,
        poll_interval: float = 0.8,
    ) -> None:
        """
        Initialise the Guardian agent.

        Args:
            state:         Shared EngineState.
            poll_interval: Seconds between risk evaluations.
        """
        self._state         = state
        self._poll_interval = poll_interval

    async def run(self) -> None:
        """Main async loop — runs until cancelled."""
        log.info('Guardian agent started.')
        self._state.emit('guardian', 'Agent started.')

        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                log.info('Guardian agent cancelled.')
                self._state.emit('guardian', 'Agent stopped.')
                return
            except Exception as exc:
                log.warning('Guardian tick error: %s', exc)
            await asyncio.sleep(self._poll_interval)

    async def _tick(self) -> None:
        """Evaluate risk for all tickers and update state."""
        async with self._state.lock_indicators:
            indicators = dict(self._state.indicators)

        if not indicators:
            return

        async with self._state.lock_risk:
            for ticker in self._state.tickers:
                ind       = indicators.get(ticker)
                sprd_pct  = ind.spread_pct if ind else None

                new_risk = evaluate_risk(ticker, self._state, sprd_pct)

                prev_risk = self._state.risk.get(ticker)
                if new_risk.halted and (prev_risk is None or not prev_risk.halted):
                    self._state.emit(
                        'guardian',
                        f'HALT {ticker}: {new_risk.halt_reason}',
                    )
                elif not new_risk.halted and prev_risk and prev_risk.halted:
                    self._state.emit(
                        'guardian',
                        f'RESUME {ticker}: risk cleared.',
                    )

                self._state.risk[ticker] = new_risk

        self._state.agent_ticks['guardian'] += 1
