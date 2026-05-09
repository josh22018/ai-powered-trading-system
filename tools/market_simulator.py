import time
import random
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure project root is importable
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.ring_buffer import RingBuffer

def run_simulator():
    load_dotenv()
    tickers = os.getenv("TICKERS", "RELIANCE,HDFCBANK,TCS,INFY").split(",")
    print(f"Starting Indian Market Simulator for: {tickers}")
    
    # Connect to ring buffer
    rb = RingBuffer(name='kairos_ring', create=False)
    
    # Initial prices (rough estimates for simulation)
    prices = {
        "RELIANCE": 2900.0,
        "HDFCBANK": 1500.0,
        "TCS": 3800.0,
        "INFY": 1400.0
    }
    # Fallback for other tickers
    for t in tickers:
        if t not in prices:
            prices[t] = random.uniform(100.0, 5000.0)

    print("Simulator running. Pushing data to dashboard...")
    
    try:
        while True:
            for ticker in tickers:
                # Random walk
                prices[ticker] += random.uniform(-1.5, 1.5)
                mid = prices[ticker]
                
                # Mock order book
                spread = random.uniform(0.1, 0.5)
                bids = []
                asks = []
                total_bid_vol = 0
                total_ask_vol = 0
                
                for i in range(5):
                    # Bids
                    b_price = mid - (spread/2) - (i * 0.2)
                    b_qty = random.randint(100, 2000)
                    bids.append([round(b_price, 2), b_qty])
                    total_bid_vol += b_qty
                    
                    # Asks
                    a_price = mid + (spread/2) + (i * 0.2)
                    a_qty = random.randint(100, 2000)
                    asks.append([round(a_price, 2), a_qty])
                    total_ask_vol += a_qty
                
                snapshot = {
                    'ticker': ticker,
                    'timestamp_ns': time.time_ns(),
                    'mid_price': float(mid),
                    'spread': float(spread),
                    'bids': bids,
                    'asks': asks,
                    'total_bid_volume': total_bid_vol,
                    'total_ask_volume': total_ask_vol
                }
                
                rb.write(snapshot)
            
            time.sleep(0.1) # 10 updates per second
            
    except KeyboardInterrupt:
        print("\nSimulator stopped.")

if __name__ == "__main__":
    run_simulator()
