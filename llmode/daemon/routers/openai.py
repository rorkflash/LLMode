"""OpenAI-compatible inference proxy (``/v1/*``).

Inbound requests name a model in their JSON body (or path); we lazy-load that
model via the lifecycle manager and forward the request to the corresponding
backend process, streaming the response back unchanged. This lets any existing
OpenAI client talk to LLMode by just pointing ``base_url`` at the daemon.
"""

from __future__ import annotations

import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from llmode.daemon.context import AppContext
from llmode.daemon.deps import get_context, require_auth

# Mounted at /v1, gated by the same optional auth as the management API.
router = APIRouter(prefix="/v1", dependencies=[Depends(require_auth)])


@router.get("/models")
def list_v1_models(ctx: AppContext = Depends(get_context)) -> dict:
    """List models in OpenAI's ``/v1/models`` shape.

    We advertise everything in the local catalog so clients can discover what is
    runnable; loading happens on first completion request.
    """
    data = [
        {"id": m.id, "object": "model", "owned_by": m.source}
        for m in ctx.db.list_models()
    ]
    return {"object": "list", "data": data}


async def _proxy(ctx: AppContext, request: Request, path: str) -> Request:
    """Shared forwarding logic for completion-style endpoints.

    Steps: parse body -> find model -> ensure it's loaded -> forward to backend,
    honouring streaming (SSE) when the client requested ``stream: true``.
    """
    # Parse the JSON body to discover which model is being requested.
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body.") from exc

    model_id = body.get("model")
    if not model_id:
        raise HTTPException(status_code=400, detail="Request must include a 'model' field.")

    # Lazy-load (or refresh) the target model; 400/507 surface as HTTP errors.
    try:
        run = await ctx.lifecycle.ensure_loaded(model_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from exc

    if not run.base_url:
        raise HTTPException(status_code=503, detail="Backend has no address yet.")

    upstream_url = f"{run.base_url}/v1/{path}"
    streaming = bool(body.get("stream"))

    if streaming:
        # Stream Server-Sent Events straight through to the client.
        async def event_stream():
            """Yield upstream SSE chunks verbatim as they arrive."""
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", upstream_url, json=body) as resp:
                    async for chunk in resp.aiter_raw():
                        yield chunk

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    # Non-streaming: await the full response and relay status + JSON.
    async with httpx.AsyncClient(timeout=None) as client:
        resp = await client.post(upstream_url, json=body)
    return JSONResponse(status_code=resp.status_code, content=resp.json())


@router.post("/chat/completions")
async def chat_completions(request: Request, ctx: AppContext = Depends(get_context)):
    """Proxy chat completions to the requested model's backend."""
    return await _proxy(ctx, request, "chat/completions")


@router.post("/completions")
async def completions(request: Request, ctx: AppContext = Depends(get_context)):
    """Proxy legacy text completions to the requested model's backend."""
    return await _proxy(ctx, request, "completions")


@router.post("/embeddings")
async def embeddings(request: Request, ctx: AppContext = Depends(get_context)):
    """Proxy embedding requests to the requested model's backend."""
    return await _proxy(ctx, request, "embeddings")
