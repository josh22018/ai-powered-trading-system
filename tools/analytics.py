"""
Post-run Analytics script for Kairos X.

Calculates key performance metrics (Sharpe ratio, max drawdown, win rate)
from the EngineState's portfolio and positions.

Usage:
  python tools/analytics.py
"""

import sys
import math
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import requests
from pathlib import Path

def compute_metrics():
    print("\n" + "="*50)
    print(" KAIROS X : POST-RUN ANALYTICS ")
    print("="*50)
    
    try:
        response = requests.get('http://127.0.0.1:5001/api/analytics')
        if response.status_code != 200:
            print(f"Error fetching analytics: {response.text}")
            return
            
        metrics = response.json()
        
        initial_cap = metrics.get('initial_capital', 0)
        current_equity = metrics.get('current_equity', 0)
        total_return = metrics.get('total_return', 0)
        total_return_pct = metrics.get('total_return_pct', 0)
        
        print(f"\n[Portfolio Summary]")
        print(f"  Initial Capital:  ${initial_cap:,.2f}")
        print(f"  Current Equity:   ${current_equity:,.2f}")
        print(f"  Total Return:     ${total_return:,.2f} ({total_return_pct:+.2f}%)")
        
        print(f"\n[Risk Metrics]")
        print(f"  Max Drawdown:     {metrics.get('max_drawdown_pct', 0):.2f}%")
        
        print(f"\n[Trade Statistics]")
        total_trades = metrics.get('total_trades', 0)
        win_rate = metrics.get('win_rate_pct', 0)
        
        if total_trades > 0:
            print(f"  Total Trades:     {total_trades}")
            print(f"  Win Rate (est):   {win_rate:.1f}%")
        else:
            print("  Total Trades:     0")
            print("  Win Rate:         N/A")
            
        print("\n" + "="*50 + "\n")
        
    except requests.exceptions.ConnectionError:
        print("Error: Could not connect to the engine. Make sure run_all.py is running on port 5001.")

if __name__ == '__main__':
    compute_metrics()
