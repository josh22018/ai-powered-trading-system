"""
Sentiment Analyst Agent — async coroutine that monitors financial news
and social media to compute a sentiment score (-1 to 1) for each ticker.

Provides a hook for local Llama-3 (via Ollama) or falls back to TextBlob
for lightweight sentiment scoring.
"""

import asyncio
import logging
import random
import requests
from typing import Dict, List
from textblob import TextBlob
from shared.state import EngineState

log = logging.getLogger(__name__)

class SentimentAgent:
    def __init__(
        self,
        state: EngineState,
        poll_interval: float = 2.0,  # Sentiment updates slower than price
        use_llama: bool = False,
        llama_url: str = "http://localhost:11434/api/generate"
    ) -> None:
        self._state = state
        self._poll_interval = poll_interval
        self._use_llama = use_llama
        self._llama_url = llama_url
        
        # Mock news headlines database
        self._headlines = {
            "RELIANCE": [
                "Reliance Industries reports record quarterly profit.",
                "New green energy initiative announced by Ambani.",
                "Market analysts upgrade Reliance to Strong Buy.",
                "Reliance Jio subscriber growth slows down.",
                "Oil prices volatility impacts Reliance refinery margins."
            ],
            "HDFCBANK": [
                "HDFC Bank loan book expands by 15%.",
                "RBI imposes minor fine on HDFC Bank for compliance issues.",
                "HDFC Bank merger synergies starting to show results.",
                "Asset quality remains stable at HDFC Bank.",
                "Global brokerage cuts target price for HDFC Bank."
            ],
            "TCS": [
                "TCS wins $500 million cloud transformation deal.",
                "Attrition rates at TCS hit record lows.",
                "TCS dividend yield remains attractive for investors.",
                "Slowdown in US tech spending might affect TCS growth.",
                "TCS AI platform sees massive adoption in Europe."
            ],
            "INFY": [
                "Infosys raises full-year revenue guidance.",
                "Management shuffle at Infosys raises concerns.",
                "Infosys secures long-term deal with major UK retailer.",
                "Q3 results for Infosys beat street expectations.",
                "Infosys under investigation for tax discrepancies."
            ]
        }

    async def run(self) -> None:
        log.info('Sentiment Analyst agent started.')
        self._state.emit('sentiment', 'Agent started.')

        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                log.info('Sentiment Analyst agent cancelled.')
                self._state.emit('sentiment', 'Agent stopped.')
                return
            except Exception as exc:
                log.warning('Sentiment tick error: %s', exc)
            await asyncio.sleep(self._poll_interval)

    async def _tick(self) -> None:
        """Fetch latest 'news' and score sentiment for each ticker."""
        for ticker in self._state.tickers:
            # Pick a random headline to simulate news arrival
            headline = random.choice(self._headlines.get(ticker, ["Neutral market sentiment for " + ticker]))
            
            score = 0.0
            if self._use_llama:
                score = await self._score_with_llama(headline)
            else:
                score = self._score_with_textblob(headline)

            async with self._state.lock_sentiment:
                self._state.sentiment[ticker] = score
                self._state.sentiment_history[ticker].append(score)
                
            # Log the news for the dashboard
            if random.random() < 0.2: # Only log occasionally to avoid noise
                self._state.emit('sentiment', f"NEW HEADLINE [{ticker}]: {headline} (Score: {score:+.2f})")

        self._state.agent_ticks['sentiment'] += 1

    def _score_with_textblob(self, text: str) -> float:
        """Simple TextBlob sentiment scoring."""
        analysis = TextBlob(text)
        return analysis.sentiment.polarity # -1.0 to 1.0

    async def _score_with_llama(self, text: str) -> float:
        """Hook to score sentiment using a local Llama-3 model via Ollama."""
        prompt = f"Score the sentiment of this financial headline for the stock. Output ONLY a single number between -1.0 (very bearish) and 1.0 (very bullish). Headline: '{text}'"
        
        try:
            # Using asyncio to hit the local Llama API
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, lambda: requests.post(
                self._llama_url,
                json={"model": "llama3", "prompt": prompt, "stream": False},
                timeout=5
            ))
            
            if response.status_code == 200:
                result = response.json().get("response", "0.0").strip()
                return float(result)
        except Exception as e:
            log.debug(f"Llama scoring failed, falling back: {e}")
            
        return self._score_with_textblob(text)
