"""
Analyst Agent — Markov-chain mock sentiment agent.

Simulates LLM news sentiment analysis with realistic state persistence.
In production this would call a local Llama 3.2 model.
"""

from __future__ import annotations

import random
from typing import Dict

# Markov transition matrix: current_state → {next_state: probability}
TRANSITIONS = {
    'bullish': {'bullish': 0.60, 'neutral': 0.30, 'bearish': 0.10},
    'neutral': {'bullish': 0.25, 'neutral': 0.50, 'bearish': 0.25},
    'bearish': {'bullish': 0.10, 'neutral': 0.30, 'bearish': 0.60},
}

HEADLINES = {
    'bullish': [
        'Strong earnings beat expectations',
        'Analyst upgrades to Buy',
        'Record revenue reported',
        'New product launch drives optimism',
    ],
    'bearish': [
        'Missed earnings estimates',
        'Regulatory concerns weigh on stock',
        'Supply chain disruptions reported',
        'Analyst downgrades to Sell',
    ],
    'neutral': [
        'Earnings in line with estimates',
        'Market awaits Fed decision',
        'Mixed signals from management',
        'Volume below average',
    ],
}


def _markov_step(state: str) -> str:
    """Advance sentiment state by one Markov step."""
    weights = TRANSITIONS[state]
    states  = list(weights.keys())
    probs   = list(weights.values())
    return random.choices(states, weights=probs, k=1)[0]


class AnalystAgent:
    """
    Simulated sentiment analyst using a Markov chain per ticker.

    Each call to predict() advances the Markov chain one step and
    returns a sentiment dict with a fake matching headline.
    """

    def __init__(self) -> None:
        # Start all tickers in neutral state
        self._state:      Dict[str, str]   = {}
        self._confidence: Dict[str, float] = {}

    def _init_ticker(self, ticker: str) -> None:
        if ticker not in self._state:
            self._state[ticker]      = random.choice(['bullish', 'neutral', 'neutral'])
            self._confidence[ticker] = random.uniform(0.55, 0.75)

    def predict(self, ticker: str, timestamp_ns: int) -> dict:
        """
        Return a sentiment prediction for ticker at the given timestamp.

        Advances the Markov chain one step, adds confidence noise,
        and picks a matching fake headline.

        Args:
            ticker:       Ticker symbol (e.g. 'AAPL').
            timestamp_ns: Nanosecond timestamp from the snapshot.

        Returns:
            dict with keys: ticker, sentiment, confidence, headline, timestamp_ns.
        """
        self._init_ticker(ticker)

        # Advance Markov chain
        self._state[ticker] = _markov_step(self._state[ticker])

        # Add noise to confidence, clamp to [0.50, 0.95]
        noise = random.gauss(0, 0.04)
        conf  = self._confidence[ticker] + noise
        conf  = max(0.50, min(0.95, conf))
        self._confidence[ticker] = conf

        sentiment = self._state[ticker]
        headline  = random.choice(HEADLINES[sentiment])

        return {
            'ticker':       ticker,
            'sentiment':    sentiment,
            'confidence':   round(conf, 4),
            'headline':     headline,
            'timestamp_ns': timestamp_ns,
        }
