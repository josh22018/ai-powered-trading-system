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

from shared.state import EngineState

log = logging.getLogger(__name__)


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

    @app.get('/api/state')
    async def get_state() -> JSONResponse:
        """Return a full JSON snapshot of the current engine state."""
        state: EngineState = app.state.engine
        return JSONResponse(state.to_dict())

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
                await asyncio.sleep(1.0)
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
