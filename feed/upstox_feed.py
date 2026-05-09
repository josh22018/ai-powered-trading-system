import asyncio
import logging
import os
import time
from typing import List, Dict, Optional
import urllib.request
import gzip
import csv
import io
from dotenv import load_dotenv

import upstox_client
from upstox_client.feeder.market_data_streamer_v3 import MarketDataStreamerV3
from shared.ring_buffer import RingBuffer

logger = logging.getLogger(__name__)

def get_nse_instruments() -> Dict[str, str]:
    """Downloads the Upstox NSE instrument list and maps TradingSymbol to InstrumentKey."""
    print("Downloading Upstox NSE instrument list...")
    url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz"
    
    mapping = {}
    try:
        response = urllib.request.urlopen(url)
        compressed_file = io.BytesIO(response.read())
        decompressed_file = gzip.GzipFile(fileobj=compressed_file)
        
        # Parse CSV
        content = decompressed_file.read().decode('utf-8')
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            symbol = row.get('tradingsymbol')
            key = row.get('instrument_key')
            if symbol and key:
                mapping[symbol] = key
                
        print(f"Loaded {len(mapping)} NSE instruments.")
    except Exception as e:
        print(f"Error downloading instruments: {e}")
        
    return mapping

class UpstoxFeed:
    def __init__(self, tickers: List[str]):
        load_dotenv()
        self.sandbox_mode = os.getenv('UPSTOX_SANDBOX_MODE', 'false').lower() == 'true'
        
        token_key = 'UPSTOX_SANDBOX_TOKEN' if self.sandbox_mode else 'UPSTOX_ACCESS_TOKEN'
        self.access_token = os.getenv(token_key) or os.getenv('UPSTOX_ACCESS_TOKEN')
        if not self.access_token:
            raise ValueError(f"{token_key} not found in .env. Please configure your tokens.")
            
        # Connect to existing ring buffer
        self.ring_buffer = RingBuffer(name='kairos_ring', create=False)
        self.tickers = tickers
        
        # Resolve symbols to instrument keys
        self.symbol_map = get_nse_instruments()
        self.instrument_keys = []
        self.key_to_symbol = {}
        
        for t in tickers:
            if t in self.symbol_map:
                key = self.symbol_map[t]
                self.instrument_keys.append(key)
                self.key_to_symbol[key] = t
                print(f"Mapped {t} -> {key}")
            else:
                print(f"WARNING: Symbol {t} not found in NSE equity list.")

        # Initialize Streamer
        configuration = upstox_client.Configuration(sandbox=self.sandbox_mode)
        configuration.access_token = self.access_token
        upstox_client.Configuration.set_default(configuration)
        
        self.streamer = MarketDataStreamerV3(
            instrument_keys=self.instrument_keys,
            mode="full" # Full mode gives order book depth
        )
        
        self.streamer.on("open", self.on_open)
        self.streamer.on("message", self.on_message)
        self.streamer.on("error", self.on_error)
        self.streamer.on("close", self.on_close)

    def on_open(self):
        print("Connected to Upstox Market Data WebSocket!")

    def on_message(self, message):
        """Parse incoming protobuf dict and format to OrderBook snapshot"""
        # The structure is specific to upstox v3 feed.
        # It contains a 'feeds' dict keyed by instrument_key.
        feeds = message.get("feeds", {})
        
        for key, data in feeds.items():
            if 'ff' not in data: # full feed
                continue
                
            ff = data['ff']
            market_ff = ff.get('marketFF', {})
            ltp = market_ff.get('ltpc', {}).get('ltp')
            
            if ltp is None:
                continue
                
            symbol = self.key_to_symbol.get(key, key)
            
            # Extract order book (depth)
            bids = []
            asks = []
            total_bid_vol = 0
            total_ask_vol = 0
            
            # Upstox gives up to 5 levels of market depth
            market_level = market_ff.get('marketLevel', {})
            for bid in market_level.get('bidAskQuote', []):
                # Price is often scaled or direct. Let's assume direct for now.
                bq_price = bid.get('bp', 0)
                bq_qty = bid.get('bq', 0)
                aq_price = bid.get('ap', 0)
                aq_qty = bid.get('aq', 0)
                
                if bq_qty > 0:
                    bids.append([bq_price, bq_qty])
                    total_bid_vol += bq_qty
                if aq_qty > 0:
                    asks.append([aq_price, aq_qty])
                    total_ask_vol += aq_qty
                    
            # Sort bids desc, asks asc
            bids.sort(key=lambda x: x[0], reverse=True)
            asks.sort(key=lambda x: x[0])
            
            # Calculate mid price and spread
            mid_price = ltp
            spread = 0.0
            if bids and asks:
                mid_price = (bids[0][0] + asks[0][0]) / 2.0
                spread = asks[0][0] - bids[0][0]

            snapshot = {
                'ticker': symbol,
                'timestamp_ns': time.time_ns(),
                'mid_price': float(mid_price),
                'spread': float(spread),
                'bids': bids,
                'asks': asks,
                'total_bid_volume': total_bid_vol,
                'total_ask_volume': total_ask_vol
            }
            
            # Push to RingBuffer
            self.ring_buffer.write(snapshot)

    def on_error(self, error):
        print(f"WebSocket Error: {error}")

    def on_close(self, code, reason):
        print(f"WebSocket Closed: {code} - {reason}")

    def start(self):
        print("Connecting Upstox Streamer...")
        self.streamer.connect()
        # connect() is blocking, but we can run it in a thread if needed
        # Since this is a feed script, blocking is fine.

if __name__ == "__main__":
    # Default to tracking RELIANCE and HDFCBANK
    tickers = os.getenv("TICKERS", "RELIANCE,HDFCBANK,TCS,INFY").split(",")
    feed = UpstoxFeed(tickers=tickers)
    feed.start()
