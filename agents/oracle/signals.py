"""
Signal scoring model for the Oracle agent.

Combines order-book indicators into a single directional score and
classifies it as BUY / SELL / HOLD with a confidence value.

Scoring weights (tunable):
    imbalance weight  : 0.55  — dominant driver of short-term flow
    momentum weight   : 0.30  — trend confirmation
    spread penalty    : 0.15  — wide spread reduces conviction

Thresholds:
    |score| > 0.20  → directional signal (BUY or SELL)
    |score| ≤ 0.20  → HOLD
"""

from __future__ import annotations

from typing import Tuple

from shared.state import IndicatorSnapshot, Signal
import time

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

W_IMBALANCE = 0.55
W_MOMENTUM  = 0.30
W_SPREAD    = 0.15
W_SENTIMENT = 0.25  # Weight for AI Sentiment Analyst

SIGNAL_THRESHOLD = 0.20       # minimum |score| for a directional signal
MAX_SPREAD_PCT   = 2.0        # spread > this % → reduce confidence heavily
MAX_MOMENTUM_REF = 0.50       # $0.50 normalisation reference for momentum


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _normalise_momentum(momentum: float, mid_price: float) -> float:
    """
    Normalise raw momentum to [-1, +1].

    Uses a percentage-of-price normalisation so the scale is
    ticker-independent.
    """
    if mid_price == 0:
        return 0.0
    pct = momentum / mid_price        # fraction of price
    # Sigmoid-like clamp via tanh (avoids hard clips)
    import math
    return math.tanh(pct * 50)       # 50× amplification → ≈saturates at ±2%


def _spread_confidence_penalty(spread_pct: float) -> float:
    """
    Return a multiplier in (0, 1] that reduces confidence when spread is wide.

    spread_pct 0 → multiplier 1.0  (no penalty)
    spread_pct ≥ MAX_SPREAD_PCT → multiplier ≈ 0.1  (heavy penalty)
    """
    if spread_pct <= 0:
        return 1.0
    penalty = 1.0 - min(spread_pct / MAX_SPREAD_PCT, 1.0) * 0.9
    return max(penalty, 0.1)


def score_indicators(ind: IndicatorSnapshot, sentiment: float = 0.0) -> Tuple[float, str]:
    """
    Compute a composite signal score from an IndicatorSnapshot and AI Sentiment.

    Returns:
        (score, reason_string)
        score in [-1.0, +1.0]; positive → bullish, negative → bearish.
    """
    imb  = ind.order_imbalance                       # already in [-1, 1]
    mom  = _normalise_momentum(ind.momentum, ind.mid_price)
    sprd = ind.spread_pct or 0.0

    # Combine Order Book + Momentum + Sentiment
    raw_score = (W_IMBALANCE * imb) + (W_MOMENTUM * mom) + (W_SENTIMENT * sentiment)

    # Apply spread penalty
    penalty   = _spread_confidence_penalty(sprd)
    score     = raw_score * penalty

    reason = (
        f'imb={imb:+.2f} mom={mom:+.2f} sent={sentiment:+.2f} '
        f'spread={sprd:.2f}% penalty={penalty:.2f}'
    )
    return score, reason


def classify_signal(
    ticker: str,
    ind: IndicatorSnapshot,
    sentiment: float = 0.0
) -> Signal:
    """
    Produce a Signal from an IndicatorSnapshot.

    Args:
        ticker: Ticker symbol.
        ind:    Latest IndicatorSnapshot for the ticker.

    Returns:
        Signal with direction ∈ {'BUY', 'SELL', 'HOLD'} and confidence.
    """
    score, reason = score_indicators(ind, sentiment)
    abs_score     = abs(score)

    if abs_score > SIGNAL_THRESHOLD:
        direction  = 'BUY' if score > 0 else 'SELL'
        confidence = min(abs_score, 1.0)
    else:
        direction  = 'HOLD'
        confidence = 1.0 - (abs_score / SIGNAL_THRESHOLD)   # certainty of HOLD

    return Signal(
        ticker=ticker,
        timestamp=time.time(),
        direction=direction,
        confidence=round(confidence, 4),
        score=round(score, 4),
        reason=reason,
    )
