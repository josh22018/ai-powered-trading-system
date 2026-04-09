"""
Guardian Agent — Autoencoder-based anomaly detector.

Trains on normal order-book data and emits HALT signals when the
reconstruction error exceeds a learned threshold.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import torch
import torch.nn as nn
import torch.optim as optim

MODEL_PATH     = Path(__file__).parent / 'guardian_model.pt'
THRESHOLD_PATH = Path(__file__).parent / 'threshold.json'
INPUT_SIZE     = 20   # top5 bid prices + top5 bid vols + top5 ask prices + top5 ask vols


def _snap_to_features(snap: dict) -> List[float]:
    """Flatten top-5 bid/ask prices and volumes into a 20-element vector."""
    bids = snap.get('bids', [])
    asks = snap.get('asks', [])

    bid_prices  = [bids[i][0] if i < len(bids) else 0.0 for i in range(5)]
    bid_volumes = [float(bids[i][1]) if i < len(bids) else 0.0 for i in range(5)]
    ask_prices  = [asks[i][0] if i < len(asks) else 0.0 for i in range(5)]
    ask_volumes = [float(asks[i][1]) if i < len(asks) else 0.0 for i in range(5)]

    return bid_prices + bid_volumes + ask_prices + ask_volumes


def _normalise(vectors: List[List[float]]) -> tuple:
    """Min-max normalise feature matrix; return (normalised, min, max)."""
    t = torch.tensor(vectors, dtype=torch.float32)
    mn = t.min(dim=0).values
    mx = t.max(dim=0).values
    rng = mx - mn
    rng[rng == 0] = 1.0   # avoid division by zero for constant features
    return (t - mn) / rng, mn, mx


class OrderBookAutoencoder(nn.Module):
    """
    Symmetric autoencoder: 20 → 64 → 32 → 16 → 8 → 16 → 32 → 64 → 20.
    """

    def __init__(self, input_size: int = INPUT_SIZE) -> None:
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(input_size, 64), nn.ReLU(),
            nn.Linear(64, 32),         nn.ReLU(),
            nn.Linear(32, 16),         nn.ReLU(),
            nn.Linear(16, 8),          nn.ReLU(),
        )
        self.decoder = nn.Sequential(
            nn.Linear(8, 16),          nn.ReLU(),
            nn.Linear(16, 32),         nn.ReLU(),
            nn.Linear(32, 64),         nn.ReLU(),
            nn.Linear(64, input_size),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.decoder(self.encoder(x))


class GuardianAgent:
    """
    Anomaly detector using reconstruction error from an autoencoder.

    After training on normal data, the dynamic threshold is set to
    mean_error + 2×std_error on the training set.
    """

    def __init__(self) -> None:
        self.model: OrderBookAutoencoder = OrderBookAutoencoder()
        self.model.eval()
        self.threshold: float = 0.05
        self.trained_on_normal: bool = False
        self._feat_min: Optional[torch.Tensor] = None
        self._feat_max: Optional[torch.Tensor] = None

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, normal_snapshots: List[dict], epochs: int = 100) -> None:
        """
        Train autoencoder on normal_snapshots (first 80% recommended).

        Learns the reconstruction threshold from training-set errors.
        Saves model and threshold to disk.
        """
        vectors = [_snap_to_features(s) for s in normal_snapshots]
        if len(vectors) < 10:
            print('[GUARDIAN] Too few snapshots — skipping training.')
            return

        X_norm, mn, mx = _normalise(vectors)
        self._feat_min = mn
        self._feat_max = mx

        self.model.train()
        optimizer = optim.Adam(self.model.parameters(), lr=1e-3)
        criterion = nn.MSELoss()

        for epoch in range(1, epochs + 1):
            optimizer.zero_grad()
            recon = self.model(X_norm)
            loss  = criterion(recon, X_norm)
            loss.backward()
            optimizer.step()
            if epoch % 20 == 0:
                print(f'  [GUARDIAN] Epoch {epoch:3d}/{epochs}  loss={loss.item():.6f}')

        # Compute dynamic threshold
        self.model.eval()
        with torch.no_grad():
            recon  = self.model(X_norm)
            errors = ((recon - X_norm) ** 2).mean(dim=1)
            mean_e = errors.mean().item()
            std_e  = errors.std().item()
            self.threshold = mean_e + 2.0 * std_e

        self.trained_on_normal = True
        print(f'  [GUARDIAN] Threshold set to {self.threshold:.6f}')

        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        torch.save({
            'model_state': self.model.state_dict(),
            'feat_min':    self._feat_min,
            'feat_max':    self._feat_max,
        }, MODEL_PATH)
        with open(THRESHOLD_PATH, 'w') as f:
            json.dump({'threshold': self.threshold}, f)
        print(f'  [GUARDIAN] Model saved → {MODEL_PATH}')

    def load(self) -> None:
        """Load model and threshold from disk."""
        data = torch.load(MODEL_PATH, map_location='cpu')
        self.model.load_state_dict(data['model_state'])
        self._feat_min = data.get('feat_min')
        self._feat_max = data.get('feat_max')
        self.model.eval()
        if THRESHOLD_PATH.exists():
            with open(THRESHOLD_PATH) as f:
                self.threshold = json.load(f)['threshold']
        self.trained_on_normal = True

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def _to_tensor(self, snap: dict) -> torch.Tensor:
        feats = torch.tensor([_snap_to_features(snap)], dtype=torch.float32)
        if self._feat_min is not None and self._feat_max is not None:
            rng = self._feat_max - self._feat_min
            rng[rng == 0] = 1.0
            feats = (feats - self._feat_min) / rng
        return feats

    def score(self, snapshot: dict) -> float:
        """Return reconstruction error for snapshot (higher = more anomalous)."""
        x = self._to_tensor(snapshot)
        with torch.no_grad():
            recon = self.model(x)
            return float(((recon - x) ** 2).mean().item())

    def predict(self, snapshot: dict) -> dict:
        """
        Return anomaly assessment for a snapshot.

        Returns halt_signal=True only when score exceeds 2× threshold.
        """
        ts    = snapshot.get('timestamp_ns', 0)
        err   = self.score(snapshot)
        is_anomaly = err > self.threshold
        is_critical = err > 2.0 * self.threshold

        if is_critical:
            level = 'critical'
        elif is_anomaly:
            level = 'warning'
        else:
            level = 'normal'

        return {
            'anomaly_score': round(err, 6),
            'is_anomaly':    is_anomaly,
            'halt_signal':   is_critical,
            'alert_level':   level,
            'timestamp_ns':  ts,
        }
