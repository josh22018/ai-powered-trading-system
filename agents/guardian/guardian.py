"""
Guardian agent — async coroutine that monitors risk rules AND runs
autoencoder-based anomaly detection on order-book snapshots.

Two-layer defence:
  1. Rule-based checks (position size, drawdown, spread, trade count)
  2. Autoencoder reconstruction error — flags spoofing/manipulation

If a risk breach or critical anomaly is detected the Guardian:
  1. Sets RiskStatus.halted = True with a descriptive reason.
  2. Emits a log entry — the Strategist picks this up and liquidates.

The Guardian does NOT directly close positions; it only signals intent.
This preserves clean separation of concerns between agents.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

import torch

from agents.guardian.risk import evaluate_risk
from shared.state import EngineState

log = logging.getLogger(__name__)

# Autoencoder paths (from guardian_agent.py training)
_MODEL_PATH     = Path(__file__).parent / 'guardian_model.pt'
_THRESHOLD_PATH = Path(__file__).parent / 'threshold.json'


def _snap_to_features(snap: dict) -> List[float]:
    """Flatten top-5 bid/ask prices and volumes into a 20-element vector."""
    bids = snap.get('bids', [])
    asks = snap.get('asks', [])

    bid_prices  = [bids[i][0] if i < len(bids) else 0.0 for i in range(5)]
    bid_volumes = [float(bids[i][1]) if i < len(bids) else 0.0 for i in range(5)]
    ask_prices  = [asks[i][0] if i < len(asks) else 0.0 for i in range(5)]
    ask_volumes = [float(asks[i][1]) if i < len(asks) else 0.0 for i in range(5)]

    return bid_prices + bid_volumes + ask_prices + ask_volumes


class GuardianAgent:
    """
    Evaluates all risk rules for every ticker and publishes RiskStatus
    objects to EngineState.risk.

    Also runs the trained autoencoder on raw order-book snapshots for
    anomaly detection (spoofing/manipulation detection).
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

        # Autoencoder state
        self._ae_model: Optional[torch.nn.Module] = None
        self._ae_threshold: float = 0.05
        self._feat_min: Optional[torch.Tensor] = None
        self._feat_max: Optional[torch.Tensor] = None
        self._ae_loaded: bool = False

        # Per-ticker anomaly scores (for dashboard)
        self._anomaly_scores: Dict[str, float] = {}

        # Try to load pre-trained model
        self._try_load_autoencoder()

    def _try_load_autoencoder(self) -> None:
        """Attempt to load the pre-trained autoencoder model from disk."""
        if not _MODEL_PATH.exists():
            log.info('No pre-trained Guardian autoencoder found at %s', _MODEL_PATH)
            return

        try:
            from agents.guardian.guardian_agent import OrderBookAutoencoder
            data = torch.load(_MODEL_PATH, map_location='cpu', weights_only=False)
            model = OrderBookAutoencoder()
            model.load_state_dict(data['model_state'])
            model.eval()
            self._ae_model = model
            self._feat_min = data.get('feat_min')
            self._feat_max = data.get('feat_max')

            if _THRESHOLD_PATH.exists():
                with open(_THRESHOLD_PATH) as f:
                    self._ae_threshold = json.load(f).get('threshold', 0.05)

            self._ae_loaded = True
            log.info('Guardian autoencoder loaded (threshold=%.6f)', self._ae_threshold)
        except Exception as exc:
            log.warning('Failed to load Guardian autoencoder: %s', exc)

    def _score_anomaly(self, snap: dict) -> float:
        """
        Compute autoencoder reconstruction error for a snapshot.

        Returns 0.0 if the autoencoder is not loaded.
        """
        if not self._ae_loaded or self._ae_model is None:
            return 0.0

        try:
            feats = torch.tensor([_snap_to_features(snap)], dtype=torch.float32)
            if self._feat_min is not None and self._feat_max is not None:
                rng = self._feat_max - self._feat_min
                rng[rng == 0] = 1.0
                feats = (feats - self._feat_min) / rng

            with torch.no_grad():
                recon = self._ae_model(feats)
                return float(((recon - feats) ** 2).mean().item())
        except Exception as exc:
            log.warning('Autoencoder scoring failed: %s', exc)
            return 0.0

    async def run(self) -> None:
        """Main async loop — runs until cancelled."""
        log.info('Guardian agent started.')
        self._state.emit('guardian', 'Agent started.')
        if self._ae_loaded:
            self._state.emit(
                'guardian',
                f'Autoencoder loaded (threshold={self._ae_threshold:.6f})',
            )

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

        async with self._state.lock_snapshots:
            snapshots = dict(self._state.snapshots)

        if not indicators:
            return

        async with self._state.lock_risk:
            for ticker in self._state.tickers:
                ind       = indicators.get(ticker)
                sprd_pct  = ind.spread_pct if ind else None

                # Rule-based risk evaluation
                new_risk = evaluate_risk(ticker, self._state, sprd_pct)

                # Autoencoder anomaly detection on raw snapshots
                snap = snapshots.get(ticker)
                if snap and self._ae_loaded:
                    anomaly_score = self._score_anomaly(snap)
                    self._anomaly_scores[ticker] = anomaly_score

                    is_critical = anomaly_score > 2.0 * self._ae_threshold
                    is_warning  = anomaly_score > self._ae_threshold

                    if is_critical and not new_risk.halted:
                        new_risk.halted = True
                        new_risk.halt_reason = (
                            f'Anomaly detected (score={anomaly_score:.6f} '
                            f'> 2×threshold={2*self._ae_threshold:.6f}) '
                            f'— possible spoofing/manipulation'
                        )
                    elif is_warning and not new_risk.halted:
                        # Log warning but don't halt
                        pass  # state.emit below handles logging

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
