"""
Strategist Agent — PPO reinforcement learning trading agent.

Uses a custom Gymnasium environment that incorporates signals from
Oracle and Analyst agents as part of the observation space.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import gymnasium as gym
from gymnasium import spaces
from stable_baselines3 import PPO
from stable_baselines3.common.env_util import make_vec_env

MODEL_PATH = Path(__file__).parent / 'strategist_model.zip'

INITIAL_CASH   = 10_000.0
SHARES_PER_BUY = 10
BANKRUPT_FLOOR = 100.0
MAX_EPISODE_STEPS = 500

SENTIMENT_MAP   = {'bullish': 0, 'neutral': 1, 'bearish': 2}
DIRECTION_MAP   = {'up': 0, 'flat': 2, 'down': 1}


def _encode_oracle(signal: dict) -> Tuple[int, float]:
    direction = signal.get('direction', 'flat') if signal else 'flat'
    conf      = signal.get('confidence', 0.33) if signal else 0.33
    return DIRECTION_MAP.get(direction, 2), float(conf)


def _encode_analyst(signal: dict) -> Tuple[int, float]:
    sentiment = signal.get('sentiment', 'neutral') if signal else 'neutral'
    conf      = signal.get('confidence', 0.5) if signal else 0.5
    return SENTIMENT_MAP.get(sentiment, 1), float(conf)


class TradingEnv(gym.Env):
    """
    Single-ticker trading environment for PPO training.

    Observation (12 features):
        mid_price, spread, bid_volume, ask_volume,
        oracle_direction(0-2), oracle_confidence,
        analyst_sentiment(0-2), analyst_confidence,
        position(shares), avg_buy_price, unrealized_pnl,
        cash_balance_normalized

    Actions: 0=Hold, 1=Buy, 2=Sell
    """

    metadata = {'render_modes': []}

    def __init__(self, snapshots: List[dict],
                 oracle_signals: Optional[List[dict]] = None,
                 analyst_signals: Optional[List[dict]] = None) -> None:
        super().__init__()
        self.snapshots       = snapshots
        self.oracle_signals  = oracle_signals  or [{}] * len(snapshots)
        self.analyst_signals = analyst_signals or [{}] * len(snapshots)

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(12,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(3)

        self._step_idx  = 0
        self._cash      = INITIAL_CASH
        self._position  = 0
        self._avg_price = 0.0
        self._realized_pnl = 0.0

    def _mid(self) -> float:
        snap = self.snapshots[self._step_idx]
        return float(snap.get('mid_price') or 1.0)

    def _obs(self) -> np.ndarray:
        snap     = self.snapshots[self._step_idx]
        oracle   = self.oracle_signals[self._step_idx]
        analyst  = self.analyst_signals[self._step_idx]
        mid      = float(snap.get('mid_price') or 0.0)
        spread   = float(snap.get('spread') or 0.0)
        bid_vol  = float(snap.get('total_bid_volume') or 0)
        ask_vol  = float(snap.get('total_ask_volume') or 0)
        o_dir, o_conf = _encode_oracle(oracle)
        a_sent, a_conf = _encode_analyst(analyst)
        pos_val   = self._position * mid
        unreal    = pos_val - self._position * self._avg_price
        cash_norm = self._cash / INITIAL_CASH
        return np.array([
            mid, spread, bid_vol, ask_vol,
            o_dir, o_conf, a_sent, a_conf,
            float(self._position), self._avg_price, unreal, cash_norm,
        ], dtype=np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._step_idx     = 0
        self._cash         = INITIAL_CASH
        self._position     = 0
        self._avg_price    = 0.0
        self._realized_pnl = 0.0
        return self._obs(), {}

    def step(self, action: int):
        mid     = self._mid()
        reward  = -0.001   # time penalty

        cost = mid * SHARES_PER_BUY

        if action == 1:   # Buy
            if self._cash >= cost:
                total_shares = self._position + SHARES_PER_BUY
                self._avg_price = (
                    (self._avg_price * self._position + cost) / total_shares
                ) if total_shares else mid
                self._cash     -= cost
                self._position += SHARES_PER_BUY
                reward += 0.01
            else:
                reward -= 0.05   # invalid action penalty

        elif action == 2:   # Sell
            if self._position >= SHARES_PER_BUY:
                proceeds = mid * SHARES_PER_BUY
                pnl      = proceeds - self._avg_price * SHARES_PER_BUY
                self._cash      += proceeds
                self._position  -= SHARES_PER_BUY
                self._realized_pnl += pnl
                reward += pnl * 0.001 + 0.01
                if self._position == 0:
                    self._avg_price = 0.0
            else:
                reward -= 0.05

        self._step_idx += 1
        done = (
            self._step_idx >= min(MAX_EPISODE_STEPS, len(self.snapshots) - 1)
            or (self._cash + self._position * mid) < BANKRUPT_FLOOR
        )
        truncated = False
        return self._obs(), reward, done, truncated, {}

    def render(self): pass


class StrategistAgent:
    """PPO-based trading decision agent."""

    def __init__(self) -> None:
        self._model: Optional[PPO] = None

    def train(self, snapshots: List[dict],
              oracle_signals: Optional[List[dict]] = None,
              analyst_signals: Optional[List[dict]] = None,
              total_timesteps: int = 50_000) -> None:
        """Train PPO on TradingEnv built from provided snapshots."""
        env = TradingEnv(snapshots, oracle_signals, analyst_signals)
        self._model = PPO(
            'MlpPolicy', env,
            learning_rate=3e-4,
            n_steps=512,
            batch_size=64,
            n_epochs=10,
            gamma=0.99,
            verbose=1,
            device='cpu',
        )
        self._model.learn(total_timesteps=total_timesteps)
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._model.save(str(MODEL_PATH.with_suffix('')))
        print(f'  [STRATEGIST] Model saved → {MODEL_PATH}')

    def load(self, path: Optional[str] = None) -> None:
        """Load a saved PPO model."""
        p = str(Path(path).with_suffix('')) if path else str(MODEL_PATH.with_suffix(''))
        self._model = PPO.load(p, device='cpu')

    def predict(self, observation: Dict[str, Any]) -> dict:
        """
        Return a trading action given a structured observation dict.

        The observation dict should have the same keys as TradingEnv._obs().
        """
        if self._model is None:
            return {'action': 'Hold', 'confidence': 0.5,
                    'timestamp_ns': observation.get('timestamp_ns', 0)}

        snap     = observation.get('snapshot', {})
        oracle   = observation.get('oracle', {})
        analyst  = observation.get('analyst', {})
        position = observation.get('position', 0)
        avg_buy  = observation.get('avg_buy_price', 0.0)
        cash     = observation.get('cash', INITIAL_CASH)

        mid      = float(snap.get('mid_price') or 0.0)
        spread   = float(snap.get('spread') or 0.0)
        bid_vol  = float(snap.get('total_bid_volume') or 0)
        ask_vol  = float(snap.get('total_ask_volume') or 0)
        o_dir, o_conf  = _encode_oracle(oracle)
        a_sent, a_conf = _encode_analyst(analyst)
        pos_val  = position * mid
        unreal   = pos_val - position * avg_buy
        cash_norm = cash / INITIAL_CASH

        obs_arr = np.array([
            mid, spread, bid_vol, ask_vol,
            o_dir, o_conf, a_sent, a_conf,
            float(position), float(avg_buy), unreal, cash_norm,
        ], dtype=np.float32)

        action, _states = self._model.predict(obs_arr, deterministic=True)
        action_int = int(action)
        action_name = {0: 'Hold', 1: 'Buy', 2: 'Sell'}.get(action_int, 'Hold')

        # Rough confidence proxy from action probability
        dist = self._model.policy.get_distribution(
            self._model.policy.obs_to_tensor(obs_arr)[0]
        )
        probs = dist.distribution.probs.detach().numpy()[0]
        confidence = float(probs[action_int])

        return {
            'action':       action_name,
            'confidence':   round(confidence, 4),
            'timestamp_ns': snap.get('timestamp_ns', 0),
        }
