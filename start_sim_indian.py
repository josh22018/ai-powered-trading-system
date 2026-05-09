"""
Kairos X — Aggressive Indian Market Simulator.
Forces high volatility and momentum to trigger Oracle BUY/SELL signals.
"""

import asyncio
import logging
import os
import signal
import sys
import time
import random
from pathlib import Path

# ---- Ensure project root is importable ----
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ---- Config ----
TICKERS = [t.strip() for t in os.environ.get('TICKERS', 'RELIANCE,HDFCBANK,TCS,INFY').split(',') if t.strip()]
DASHBOARD_PORT = int(os.environ.get('DASHBOARD_PORT', '5001'))
DASHBOARD_HOST = os.environ.get('DASHBOARD_HOST', '127.0.0.1')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(name)s  %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('kairos.orchestrator')

from agents.analyst.analyst        import AnalystAgent
from agents.guardian.guardian      import GuardianAgent
from agents.oracle.oracle          import OracleAgent
from agents.strategist.strategist  import StrategistAgent
from dashboard.backend.app         import create_app
from shared.state                  import EngineState

# Adjust thresholds for more trades in SIM mode
import agents.oracle.signals as sig_mod
import agents.guardian.risk as risk_mod
sig_mod.SIGNAL_THRESHOLD = 0.05  # Very low threshold to trigger signals
risk_mod.MIN_CONFIDENCE = 0.1   # Very low confidence to execute trades

async def run_dashboard(state: EngineState) -> None:
    import uvicorn
    app = create_app(state)
    config = uvicorn.Config(app, host=DASHBOARD_HOST, port=DASHBOARD_PORT, log_level="error")
    server = uvicorn.Server(config)
    await server.serve()

async def aggressive_feed_pump(state: EngineState) -> None:
    """Pump highly volatile mock data to ensure trades happen."""
    log.info(f"Aggressive Mock Feed started for {TICKERS}")
    
    prices = {
        "RELIANCE": 2900.0,
        "HDFCBANK": 1500.0,
        "TCS": 3800.0,
        "INFY": 1400.0
    }
    trends = {t: 0.0 for t in TICKERS}

    while True:
        latest = {}
        for ticker in TICKERS:
            # Add some momentum/trendiness
            if random.random() < 0.05:
                trends[ticker] = random.uniform(-1.0, 1.0)
            
            # Larger swings to trigger analyst momentum
            change = trends[ticker] + random.uniform(-1.5, 1.5)
            prices[ticker] += change
            mid = prices[ticker]
            
            # Artificial imbalance to trigger signals
            # 70% chance of a slight imbalance towards the current trend
            imb = trends[ticker] * 0.5 + random.uniform(-0.5, 0.5)
            imb = max(-1.0, min(1.0, imb))
            
            spread = random.uniform(0.1, 0.3)
            bids = []
            asks = []
            
            for i in range(5):
                # Apply imbalance to volumes
                b_qty = random.randint(100, 1000) * (1.0 + max(0, imb))
                a_qty = random.randint(100, 1000) * (1.0 + max(0, -imb))
                
                bids.append([round(mid - (spread/2) - (i * 0.1), 2), int(b_qty)])
                asks.append([round(mid + (spread/2) + (i * 0.1), 2), int(a_qty)])
            
            latest[ticker] = {
                'ticker': ticker,
                'timestamp_ns': time.time_ns(),
                'mid_price': float(mid),
                'spread': float(spread),
                'bids': bids,
                'asks': asks,
                'total_bid_volume': sum(b[1] for b in bids),
                'total_ask_volume': sum(a[1] for a in asks)
            }
        
        async with state.lock_snapshots:
            state.snapshots.update(latest)
            
        await asyncio.sleep(0.2)

async def main() -> None:
    print('=' * 62)
    print('  Kairos X  —  AGGRESSIVE SIMULATOR')
    print('=' * 62)
    print('  Status: Forcing volatility to trigger trades.')
    print()

    state = EngineState(TICKERS)
    
    analyst    = AnalystAgent(state)
    oracle     = OracleAgent(state)
    strategist = StrategistAgent(state)
    guardian   = GuardianAgent(state)

    tasks = [
        asyncio.create_task(aggressive_feed_pump(state), name='feed'),
        asyncio.create_task(analyst.run(),               name='analyst'),
        asyncio.create_task(oracle.run(),                name='oracle'),
        asyncio.create_task(strategist.run(),            name='strategist'),
        asyncio.create_task(guardian.run(),              name='guardian'),
        asyncio.create_task(run_dashboard(state),        name='dashboard'),
    ]

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        pass
    finally:
        for task in tasks:
            task.cancel()

if __name__ == '__main__':
    asyncio.run(main())
