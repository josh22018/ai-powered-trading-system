"""
Strategist agent — async coroutine that converts Oracle signals into
virtual position actions (open / close / hold).

Entry rules:
  - BUY  signal, confidence ≥ MIN_CONFIDENCE → open LONG  (if no position)
  - SELL signal, confidence ≥ MIN_CONFIDENCE → open SHORT (if no position)

Exit rules:
  - Existing LONG  + SELL signal              → close LONG
  - Existing SHORT + BUY  signal              → close SHORT
  - Guardian marks ticker halted              → close position immediately
  - Position unrealized loss > MAX_LOSS_PER_TRADE → stop-loss close
"""

from __future__ import annotations

import asyncio
import logging

from agents.strategist.position import (
    close_position,
    mark_to_market,
    open_position,
)
from agents.guardian.risk import MIN_CONFIDENCE
from agents.execution.upstox_executor import UpstoxExecutor
from shared.state import EngineState

log = logging.getLogger(__name__)

# Stop-loss: close if unrealized loss exceeds this amount
MAX_LOSS_PER_TRADE = -300.0   # -$300 per position


class StrategistAgent:
    """
    Reads signals from EngineState and manages a virtual portfolio by
    opening and closing positions via the position module helpers.
    """

    def __init__(
        self,
        state: EngineState,
        poll_interval: float = 0.7,
    ) -> None:
        """
        Initialise the Strategist agent.

        Args:
            state:         Shared EngineState.
            poll_interval: Seconds between strategy evaluations.
        """
        self._state         = state
        self._poll_interval = poll_interval
        
        # Live Execution hook
        self.live_executor = UpstoxExecutor()

    async def run(self) -> None:
        """Main async loop — runs until cancelled."""
        log.info('Strategist agent started.')
        self._state.emit('strategist', 'Agent started.')

        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                log.info('Strategist agent cancelled.')
                self._state.emit('strategist', 'Agent stopped.')
                return
            except Exception as exc:
                log.warning('Strategist tick error: %s', exc)
            await asyncio.sleep(self._poll_interval)

    async def _tick(self) -> None:
        """Evaluate all tickers and execute position logic."""
        async with self._state.lock_signals:
            signals = dict(self._state.signals)

        async with self._state.lock_indicators:
            indicators = dict(self._state.indicators)

        if not signals:
            return

        async with self._state.lock_positions:
            for ticker, sig in signals.items():
                ind = indicators.get(ticker)
                if ind is None:
                    continue

                mid   = ind.mid_price
                pos   = self._state.positions.get(ticker)
                risk  = self._state.risk.get(ticker)
                halted = risk.halted if risk else False

                # Mark-to-market all open positions
                mark_to_market(self._state, ticker, mid)
                pos = self._state.positions.get(ticker)   # re-read after mtm

                # Stop-loss check
                if pos and pos.unrealized_pnl < MAX_LOSS_PER_TRADE:
                    side_closed = pos.side
                    pnl, summary = close_position(self._state, ticker, mid)
                    self._state.emit('strategist', f'STOP-LOSS {summary}')
                    # Execute live opposite trade to close
                    exec_side = "SELL" if side_closed == "LONG" else "BUY"
                    self.live_executor.place_order(ticker, exec_side, quantity=1, price=mid)
                    continue

                # Guardian halt — liquidate immediately
                if halted and pos is not None:
                    side_closed = pos.side
                    pnl, summary = close_position(self._state, ticker, mid)
                    self._state.emit('strategist', f'HALT-CLOSE {summary}')
                    # Execute live opposite trade to close
                    exec_side = "SELL" if side_closed == "LONG" else "BUY"
                    self.live_executor.place_order(ticker, exec_side, quantity=1, price=mid)
                    continue

                if halted:
                    continue

                direction  = sig.direction
                confidence = sig.confidence

                if confidence < MIN_CONFIDENCE and direction != 'HOLD':
                    continue   # signal not confident enough

                # ---- Exit logic ----
                if pos is not None:
                    should_exit = (
                        (pos.side == 'LONG'  and direction == 'SELL') or
                        (pos.side == 'SHORT' and direction == 'BUY')
                    )
                    if should_exit:
                        side_closed = pos.side
                        pnl, summary = close_position(self._state, ticker, mid)
                        self._state.emit('strategist', f'EXIT {summary}')
                        # Execute live opposite trade to close
                        exec_side = "SELL" if side_closed == "LONG" else "BUY"
                        self.live_executor.place_order(ticker, exec_side, quantity=1, price=mid)
                    continue

                # ---- Entry logic ----
                if direction == 'BUY':
                    new_pos = open_position(self._state, ticker, 'LONG', mid)
                    if new_pos:
                        self._state.emit(
                            'strategist',
                            f'ENTER LONG  {ticker} @ ${mid:.2f}  '
                            f'conf={confidence:.2f}',
                        )
                        self.live_executor.place_order(ticker, "BUY", quantity=1, price=mid)
                elif direction == 'SELL':
                    new_pos = open_position(self._state, ticker, 'SHORT', mid)
                    if new_pos:
                        self._state.emit(
                            'strategist',
                            f'ENTER SHORT {ticker} @ ${mid:.2f}  '
                            f'conf={confidence:.2f}',
                        )
                        self.live_executor.place_order(ticker, "SELL", quantity=1, price=mid)

        self._state.agent_ticks['strategist'] += 1
