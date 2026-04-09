"""
Oracle Agent — LSTM-based price direction predictor.

Trains on sequences of order-book snapshots and predicts whether the
next mid-price will go up, down, or stay flat.
"""

from __future__ import annotations

import os
from collections import deque
from pathlib import Path
from typing import Deque, Dict, List, Optional

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

SEQUENCE_LEN = 20
MODEL_PATH   = Path(__file__).parent / 'oracle_model.pt'

# Direction label encoding
DIRECTION_MAP = {0: 'up', 1: 'down', 2: 'flat'}
FLAT_THRESHOLD = 0.01   # ±$0.01 counts as flat


def _snap_to_features(snap: dict) -> List[float]:
    """Extract 8-feature vector from a snapshot dict."""
    bids = snap.get('bids', [])
    asks = snap.get('asks', [])
    best_bid = bids[0][0] if bids else 0.0
    best_ask = asks[0][0] if asks else 0.0
    return [
        float(snap.get('mid_price') or 0.0),
        float(snap.get('spread') or 0.0),
        float(best_bid),
        float(best_ask),
        float(snap.get('total_bid_volume') or 0),
        float(snap.get('total_ask_volume') or 0),
        float(len(bids)),
        float(len(asks)),
    ]


class LSTMOracle(nn.Module):
    """Small 2-layer LSTM for 3-class price direction prediction."""

    def __init__(self, input_size: int = 8, hidden_size: int = 64,
                 num_layers: int = 2, output_size: int = 3,
                 dropout: float = 0.2) -> None:
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.fc = nn.Linear(hidden_size, output_size)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_len, input_size)
        out, _ = self.lstm(x)
        return self.fc(out[:, -1, :])   # last timestep → (batch, 3)


class OracleAgent:
    """
    LSTM-based price direction predictor.

    Maintains a per-ticker history deque and predicts direction on each
    new snapshot. Shared model trained on all tickers simultaneously.
    """

    def __init__(self) -> None:
        self.model: LSTMOracle = LSTMOracle()
        self.model.eval()
        self._history: Dict[str, Deque[List[float]]] = {}

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, snapshots_by_ticker: Dict[str, List[dict]],
              epochs: int = 50) -> None:
        """
        Build sequence-label pairs from per-ticker snapshot histories
        and train the shared LSTM model.

        Args:
            snapshots_by_ticker: {ticker: [snapshot_dict, ...]}
            epochs:              Training epochs.
        """
        X_all, y_all = [], []

        for ticker, snaps in snapshots_by_ticker.items():
            features = [_snap_to_features(s) for s in snaps]
            for i in range(len(features) - SEQUENCE_LEN):
                seq = features[i: i + SEQUENCE_LEN]
                cur_mid  = features[i + SEQUENCE_LEN - 1][0]
                next_mid = features[i + SEQUENCE_LEN][0]
                delta = next_mid - cur_mid
                if delta > FLAT_THRESHOLD:
                    label = 0   # up
                elif delta < -FLAT_THRESHOLD:
                    label = 1   # down
                else:
                    label = 2   # flat
                X_all.append(seq)
                y_all.append(label)

        if not X_all:
            print('[ORACLE] No training data — skipping.')
            return

        X = torch.tensor(X_all, dtype=torch.float32)
        y = torch.tensor(y_all, dtype=torch.long)

        dataset    = TensorDataset(X, y)
        dataloader = DataLoader(dataset, batch_size=64, shuffle=True)

        self.model.train()
        optimizer = optim.Adam(self.model.parameters(), lr=1e-3)
        criterion = nn.CrossEntropyLoss()

        for epoch in range(1, epochs + 1):
            total_loss = 0.0
            for xb, yb in dataloader:
                optimizer.zero_grad()
                logits = self.model(xb)
                loss   = criterion(logits, yb)
                loss.backward()
                optimizer.step()
                total_loss += loss.item()
            if epoch % 10 == 0:
                avg = total_loss / len(dataloader)
                print(f'  [ORACLE] Epoch {epoch:3d}/{epochs}  loss={avg:.4f}')

        self.model.eval()
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        torch.save(self.model.state_dict(), MODEL_PATH)
        print(f'  [ORACLE] Model saved → {MODEL_PATH}')

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def load(self, path: Optional[str] = None) -> None:
        """Load model weights from disk."""
        p = Path(path) if path else MODEL_PATH
        self.model.load_state_dict(torch.load(p, map_location='cpu'))
        self.model.eval()

    def update(self, snapshot: dict) -> None:
        """Add a snapshot to the per-ticker history buffer."""
        ticker = snapshot.get('ticker', 'UNKNOWN')
        if ticker not in self._history:
            self._history[ticker] = deque(maxlen=SEQUENCE_LEN)
        self._history[ticker].append(_snap_to_features(snapshot))

    def predict(self, ticker: str, new_snapshot: dict) -> dict:
        """
        Predict price direction for ticker given a new snapshot.

        Updates history then runs the LSTM if enough history exists.
        Returns direction + confidence dict.
        """
        self.update(new_snapshot)
        ts = new_snapshot.get('timestamp_ns', 0)

        hist = self._history.get(ticker)
        if hist is None or len(hist) < SEQUENCE_LEN:
            return {
                'ticker': ticker,
                'direction': 'flat',
                'confidence': 0.33,
                'timestamp_ns': ts,
            }

        x = torch.tensor([list(hist)], dtype=torch.float32)
        with torch.no_grad():
            logits = self.model(x)
            probs  = torch.softmax(logits, dim=-1)[0]
            label  = int(torch.argmax(probs).item())
            conf   = float(probs[label].item())

        return {
            'ticker': ticker,
            'direction': DIRECTION_MAP[label],
            'confidence': round(conf, 4),
            'timestamp_ns': ts,
        }
