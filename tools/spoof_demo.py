"""
Spoofing Detection Demo

Injects heavily anomalous order-book snapshots into the live engine state
to trigger the Guardian agent's autoencoder-based anomaly detector.

Usage:
  python tools/spoof_demo.py
"""

import time
import sys
import requests
from pathlib import Path

def inject_spoof() -> None:
    print("\n--- Kairos X Spoofing Demo ---")
    
    ticker = "AAPL" # Default ticker
    print(f"[!] Target ticker selected: {ticker}")
    
    print("\n[!] Simulating normal market conditions (5s)...")
    time.sleep(5)
    
    print("\n[!!!] INJECTING SPOOFING ANOMALY [!!!]")
    print(f"      Injecting massive imbalanced volume on {ticker}...")
    
    try:
        response = requests.post(
            'http://127.0.0.1:5001/api/spoof',
            json={'ticker': ticker}
        )
        if response.status_code == 200:
            print("\n[!] Anomaly injected. Watch the dashboard for Guardian HALT signal.")
            print("    The Guardian's autoencoder should flag this as a critical anomaly.")
        else:
            print(f"\n[X] Failed to inject anomaly: {response.text}")
    except requests.exceptions.ConnectionError:
        print("\n[X] Error: Could not connect to the engine. Make sure run_all.py is running on port 5001.")
    
    print("\n[!] Demo complete.")

if __name__ == '__main__':
    try:
        inject_spoof()
    except KeyboardInterrupt:
        print("\nExiting.")
