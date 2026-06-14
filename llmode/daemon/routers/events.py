"""WebSocket route (``/api/events``) for live metrics + lifecycle updates.

Each connected client subscribes to the metrics collector and receives a JSON
snapshot every sampling tick. This powers the UI's live dashboard charts without
polling.
"""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from llmode.daemon.context import AppContext

router = APIRouter()


@router.websocket("/api/events")
async def events_ws(websocket: WebSocket) -> None:
    """Stream metric snapshots to a connected client until it disconnects.

    Auth note: browser WebSocket clients cannot set Authorization headers
    easily, so token enforcement for the WS is handled via a query param in a
    fuller build. In localhost-trusted mode (default) no auth is needed.
    """
    await websocket.accept()
    ctx: AppContext = websocket.app.state.ctx
    queue = ctx.metrics.subscribe()
    try:
        # Send the latest cached snapshot immediately so the UI isn't blank.
        if (latest := ctx.metrics.latest()) is not None:
            await websocket.send_json(latest)
        # Then forward every new snapshot as it is produced.
        while True:
            snapshot = await queue.get()
            await websocket.send_json(snapshot)
    except WebSocketDisconnect:
        # Normal client disconnect — nothing to do but clean up below.
        pass
    finally:
        # Always remove our subscriber queue to avoid leaks.
        ctx.metrics.unsubscribe(queue)
        with contextlib.suppress(RuntimeError):
            await websocket.close()
