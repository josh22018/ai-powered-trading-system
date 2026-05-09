"""
Strategist agent — async coroutine that converts Oracle signals and 
Reinforcement Learning (RL) inferences into position actions.

Neuro-Symbolic Architecture:
  1. Neuro Layer (PPO/ONNX): Decides optimal Buy/Sell/Hold based on LOB state.
  2. Symbolic Layer (Rules): Enforces stop-loss, emergency halts, and oracle exit confirmations.
"""

import asyncio
import logging
import os
import onnxruntime as ort
import numpy as np

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
MAX_LOSS_PER_TRADE = -300.0   # -₹300 per position

class StrategistAgent:
    def __init__(
        self,
        state: EngineState,
        poll_interval: float = 0.7,
    ) -> None:
        self._state         = state
        self._poll_interval = poll_interval
        
        # Live Execution hook
        self.live_executor = UpstoxExecutor()
        
        # RL Model Hook (Neuro Layer)
        onnx_path = "models/strategist.onnx"
        if os.path.exists(onnx_path):
            self._ort_session = ort.InferenceSession(onnx_path)
            log.info(f"Strategist loaded ONNX model from {onnx_path}")
        else:
            self._ort_session = None
            log.warning(f"No ONNX model found at {onnx_path}, falling back to rule-based.")

    async def run(self) -> None:
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
        """Evaluate all tickers using the Neuro-Symbolic blend."""
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
                pos = self._state.positions.get(ticker)

                # 1. Neuro Layer: RL Inference
                rl_action = 0 # Default HOLD
                if self._ort_session and ind:
                    sent = self._state.sentiment.get(ticker, 0.0)
                    mom_norm = (ind.momentum / mid) * 100 if mid > 0 else 0
                    obs = np.array([[ind.order_imbalance, mom_norm, sent, ind.spread_pct or 0]], dtype=np.float32)
                    
                    outputs = self._ort_session.run(None, {'input': obs})
                    rl_action = int(np.argmax(outputs[0])) # 0=HOLD, 1=BUY, 2=SELL

                # 2. Symbolic Layer: Safety & Execution Rules
                if halted and pos:
                    side_closed = pos.side
                    pnl, summary = close_position(self._state, ticker, mid)
                    self._state.emit('strategist', f'EMERGENCY HALT: {summary}')
                    exec_side = "SELL" if side_closed == "LONG" else "BUY"
                    self.live_executor.place_order(ticker, exec_side, quantity=1, price=mid)
                    continue

                if pos and pos.unrealized_pnl < MAX_LOSS_PER_TRADE:
                    side_closed = pos.side
                    pnl, summary = close_position(self._state, ticker, mid)
                    self._state.emit('strategist', f'STOP-LOSS HIT: {summary}')
                    exec_side = "SELL" if side_closed == "LONG" else "BUY"
                    self.live_executor.place_order(ticker, exec_side, quantity=1, price=mid)
                    continue

                if halted: continue

                # Entry logic (Neuro RL)
                if not pos:
                    if rl_action == 1: # RL says BUY
                        open_position(self._state, ticker, 'LONG', mid)
                        self._state.emit('strategist', f'RL-ENTER LONG {ticker} @ ₹{mid:.2f}')
                        self.live_executor.place_order(ticker, "BUY", quantity=1, price=mid)
                    elif rl_action == 2: # RL says SELL
                        open_position(self._state, ticker, 'SHORT', mid)
                        self._state.emit('strategist', f'RL-ENTER SHORT {ticker} @ ₹{mid:.2f}')
                        self.live_executor.place_order(ticker, "SELL", quantity=1, price=mid)
                
                # Exit logic (Neuro-Symbolic blend)
                else:
                    should_exit = (
                        (pos.side == 'LONG'  and (rl_action == 2 or sig.direction == 'SELL')) or
                        (pos.side == 'SHORT' and (rl_action == 1 or sig.direction == 'BUY'))
                    )
                    if should_exit:
                        side_closed = pos.side
                        pnl, summary = close_position(self._state, ticker, mid)
                        self._state.emit('strategist', f'RL/ORACLE EXIT: {summary}')
                        exec_side = "SELL" if side_closed == "LONG" else "BUY"
                        self.live_executor.place_order(ticker, exec_side, quantity=1, price=mid)

        self._state.agent_ticks['strategist'] += 1
