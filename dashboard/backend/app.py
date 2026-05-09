"""
Kairos X dashboard backend — FastAPI application.

Endpoints:
  GET  /api/state          → full JSON snapshot of EngineState
  GET  /api/health         → liveness probe
  WS   /ws                 → WebSocket; pushes state JSON every ~1 s

The EngineState instance is injected at startup via app.state.engine.
Call `create_app(engine_state)` to get a configured FastAPI instance.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time as _time
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from shared.state import EngineState

log = logging.getLogger(__name__)

class LoginRequest(BaseModel):
    username: str
    password: str


def create_app(engine_state: EngineState) -> FastAPI:
    """
    Construct and configure the FastAPI application.

    Args:
        engine_state: The shared EngineState instance used by all agents.

    Returns:
        Configured FastAPI app ready for uvicorn.
    """
    app = FastAPI(title='Kairos X Dashboard', version='1.0.0')

    # Attach engine state so routes can access it
    app.state.engine = engine_state

    # Allow any origin in development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=['*'],
        allow_methods=['*'],
        allow_headers=['*'],
    )

    # -----------------------------------------------------------------
    # REST endpoints
    # -----------------------------------------------------------------

    @app.get('/api/health')
    async def health() -> JSONResponse:
        """Liveness probe — returns 200 OK when server is up."""
        return JSONResponse({'status': 'ok'})


    @app.post('/api/auth/login')
    async def login(req: LoginRequest) -> JSONResponse:
        # Mock auth: Any username works
        return JSONResponse({"status": "success", "user": req.username})

    @app.get('/api/market/overview')
    async def market_overview() -> JSONResponse:
        # Mock data for the Groww-style homepage
        return JSONResponse({
            "indices": [
                {"name": "NIFTY 50", "value": 22453.30, "change": 124.50, "pct": 0.56},
                {"name": "SENSEX", "value": 73876.80, "change": 382.10, "pct": 0.52},
                {"name": "BANK NIFTY", "value": 48115.50, "change": -84.20, "pct": -0.17}
            ],
            "gainers": [
                {"ticker": "RELIANCE", "price": 2945.30, "change": 2.45, "sentiment": 0.85, "vol": "1.2M"},
                {"ticker": "TCS", "price": 3812.10, "change": 1.85, "sentiment": 0.72, "vol": "840K"},
                {"ticker": "INFY", "price": 1425.60, "change": 1.20, "sentiment": 0.65, "vol": "2.1M"},
                {"ticker": "SBIN", "price": 820.45, "change": 3.10, "sentiment": 0.91, "vol": "4.5M"},
                {"ticker": "BHARTIARTL", "price": 1280.30, "change": 2.15, "sentiment": 0.78, "vol": "1.1M"},
                {"ticker": "ICICIBANK", "price": 1150.20, "change": 1.95, "sentiment": 0.82, "vol": "3.2M"}
            ],
            "losers": [
                {"ticker": "HDFCBANK", "price": 1510.40, "change": -0.85, "sentiment": 0.42, "vol": "2.8M"},
                {"ticker": "AXISBANK", "price": 1120.15, "change": -1.10, "sentiment": 0.35, "vol": "1.5M"},
                {"ticker": "WIPRO", "price": 450.30, "change": -2.40, "sentiment": 0.28, "vol": "6.2M"},
                {"ticker": "LT", "price": 3450.10, "change": -1.25, "sentiment": 0.48, "vol": "520K"}
            ]
        })

    @app.get('/api/profile')
    async def get_profile() -> JSONResponse:
        return JSONResponse({
            "username": "Karthik",
            "email": "karthik@kairos.ai",
            "plan": "Pro Alpha",
            "joined": "2026-01-15",
            "balance": 1000000.0,
            "margin_used": 0.0
        })
        return JSONResponse({'status': 'ok'})

    @app.get('/api/state')
    async def get_state() -> JSONResponse:
        """Return a full JSON snapshot of the current engine state."""
        state: EngineState = app.state.engine
        return JSONResponse(state.to_dict())

    @app.get('/api/book/{ticker}')
    async def get_book(ticker: str) -> JSONResponse:
        """Return the raw order book for a given ticker."""
        state: EngineState = app.state.engine
        async with state.lock_snapshots:
            snap = state.snapshots.get(ticker)
        if not snap:
            return JSONResponse({'error': 'Ticker not found'}, status_code=404)
        return JSONResponse(snap)

    @app.get('/api/analytics')
    async def get_analytics() -> JSONResponse:
        """Return post-run analytics metrics."""
        state: EngineState = app.state.engine
        
        # Calculate Win Rate
        total_trades = 0
        winning_trades = 0
        losing_trades = 0
        
        async with state.lock_positions:
            for ticker, pos in state.positions.items():
                if pos:
                    total_trades += pos.trade_count
                    if pos.realized_pnl > 0:
                        winning_trades += 1
                    elif pos.realized_pnl < 0:
                        losing_trades += 1
                        
        win_rate = 0.0
        if total_trades > 0:
            win_rate = (winning_trades / max(1, winning_trades + losing_trades)) * 100
            
        metrics = {
            'initial_capital': state.initial_capital,
            'current_equity': state.equity,
            'total_return': state.equity - state.initial_capital,
            'total_return_pct': ((state.equity - state.initial_capital) / state.initial_capital) * 100,
            'max_drawdown_pct': state.total_drawdown_pct,
            'total_trades': total_trades,
            'win_rate_pct': win_rate
        }
        return JSONResponse(metrics)

    @app.post('/api/invest')
    async def post_invest(request: Request) -> JSONResponse:
        """Create a simulated investment tracked against engine equity performance."""
        body = await request.json()
        amount = float(body.get('amount', 0))
        if amount <= 0:
            return JSONResponse({'error': 'Amount must be positive'}, status_code=400)
        state: EngineState = app.state.engine
        inv = {
            'id': str(int(_time.time() * 1000)),
            'amount': round(amount, 2),
            'invested_at': _time.time(),
            'engine_equity_at_invest': round(state.equity, 2),
        }
        async with state.lock_investments:
            state.user_investments.append(inv)
        return JSONResponse(inv)

    @app.post('/api/spoof')
    async def post_spoof(request: Request) -> JSONResponse:
        """Inject a heavily anomalous snapshot for the spoofing demo."""
        body = await request.json()
        ticker = body.get('ticker')
        state: EngineState = app.state.engine
        
        if not ticker or ticker not in state.tickers:
            return JSONResponse({'error': 'Invalid ticker'}, status_code=400)
            
        spoofed_snap = {
            'ticker': ticker,
            'timestamp_ns': int(_time.time() * 1e9),
            'mid_price': 150.0,
            'spread': 0.01,
            'bids': [[149.99, 1000000], [149.98, 500000], [149.97, 250000], [149.96, 100000], [149.95, 50000]],
            'asks': [[150.00, 100], [150.01, 100], [150.02, 100], [150.03, 100], [150.04, 100]],
            'total_bid_volume': 1900000,
            'total_ask_volume': 500,
            'message_count': 1000
        }
        
        async with state.lock_snapshots:
            state.snapshots[ticker] = spoofed_snap
            
        return JSONResponse({'status': 'Spoofed snapshot injected', 'ticker': ticker})

    @app.delete('/api/invest/{inv_id}')
    async def delete_invest(inv_id: str) -> JSONResponse:
        """Close/remove a simulated investment by ID."""
        state: EngineState = app.state.engine
        async with state.lock_investments:
            before = len(state.user_investments)
            state.user_investments = [i for i in state.user_investments if i['id'] != inv_id]
            removed = before - len(state.user_investments)
        if removed == 0:
            return JSONResponse({'error': 'Investment not found'}, status_code=404)
        return JSONResponse({'deleted': inv_id})

    # -----------------------------------------------------------------
    # WebSocket endpoint
    # -----------------------------------------------------------------

    @app.websocket('/ws')
    async def websocket_endpoint(ws: WebSocket) -> None:
        """
        Push EngineState JSON to connected clients every second.

        The client sends any message to keep the connection alive;
        the server ignores incoming frames and only pushes state.
        """
        await ws.accept()
        log.info('WebSocket client connected: %s', ws.client)
        state: EngineState = app.state.engine

        try:
            while True:
                payload = json.dumps(state.to_dict())
                await ws.send_text(payload)
                # 60fps equivalent sleep (~16ms) to power the 3D dashboard
                await asyncio.sleep(0.016)
        except WebSocketDisconnect:
            log.info('WebSocket client disconnected.')
        except Exception as exc:
            log.warning('WebSocket error: %s', exc)

    # -----------------------------------------------------------------
    # Serve frontend HTML
    # -----------------------------------------------------------------

    @app.get('/', response_class=HTMLResponse)
    async def serve_dashboard() -> HTMLResponse:
        """Serve the single-page dashboard HTML."""
        import pathlib
        html_path = (
            pathlib.Path(__file__).resolve().parent.parent / 'frontend' / 'index.html'
        )
        return HTMLResponse(html_path.read_text(encoding='utf-8'))

    return app
