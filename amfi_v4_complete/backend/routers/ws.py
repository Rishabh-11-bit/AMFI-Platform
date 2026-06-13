"""AMFI v4 — WebSocket hub for real-time incident push.

Clients connect to  ws://<host>/ws?token=<jwt>  (token required when AUTH_ENABLED=true)
The server broadcasts JSON messages when incidents are created or updated.

Message shape:
  { "type": "incident_created" | "incident_updated" | "approval_required" | "ping",
    "data": { ... } }

Usage from other modules:
  from backend.routers.ws import manager
  await manager.broadcast({"type": "incident_created", "data": {...}})
"""
import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from backend.config import get_settings

logger   = logging.getLogger("amfi.ws")
router   = APIRouter(tags=["websocket"])
settings = get_settings()


class ConnectionManager:
    """Manages all active WebSocket connections."""

    def __init__(self):
        self._active: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._active.append(ws)
        logger.debug("WS connect  — %d active", len(self._active))

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            try:
                self._active.remove(ws)
            except ValueError:
                pass
        logger.debug("WS disconnect — %d active", len(self._active))

    async def broadcast(self, payload: dict):
        """Fan-out a JSON message to all connected clients."""
        if not self._active:
            return
        text = json.dumps(payload, default=str)
        dead: list[WebSocket] = []
        async with self._lock:
            targets = list(self._active)
        for ws in targets:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        # Remove any dead connections
        if dead:
            async with self._lock:
                for ws in dead:
                    try:
                        self._active.remove(ws)
                    except ValueError:
                        pass

    @property
    def connection_count(self) -> int:
        return len(self._active)


# Singleton — import this from other modules
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(
    ws:    WebSocket,
    token: Optional[str] = Query(None, description="JWT access token (required when AUTH_ENABLED=true)"),
):
    """WebSocket endpoint.  When AUTH_ENABLED=true, a valid JWT *token* query
    parameter is required.  Unauthenticated connections are closed with 4001."""

    if settings.auth_enabled:
        if not token:
            await ws.close(code=4001, reason="Authentication required")
            return
        try:
            from jose import jwt as _jwt, JWTError
            _jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        except Exception:
            await ws.close(code=4001, reason="Invalid or expired token")
            return

    await manager.connect(ws)
    try:
        while True:
            # Keep connection alive — client can send "ping", we reply "pong"
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=30)
                if data == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
            except asyncio.TimeoutError:
                # Send server-initiated keepalive
                await ws.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("WS error: %s", e)
    finally:
        await manager.disconnect(ws)
