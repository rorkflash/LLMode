"""Management API (``/api/*``): the control plane the CLI and UI consume.

Covers hardware/backends introspection, the model catalog (search/download/
delete), the lifecycle (load/unload/logs), metrics, events, and config. Every
route depends on :func:`require_auth` so the optional token gates the whole API.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from llmode.backends import all_adapters
from llmode.daemon.context import AppContext
from llmode.daemon.deps import get_context, require_auth
from llmode.hardware import detect_hardware
from llmode.schemas import BackendInfo, ModelManifest, ModelRun, RuntimeConfig

# All management routes live under /api and require auth (when enabled).
router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


# --- request/response bodies ----------------------------------------------
class SearchRequest(BaseModel):
    """Body for catalog search."""

    query: str = Field(description="Free-text query passed to the Hub search.")
    limit: int = Field(default=20, description="Max results to return.")


class DownloadRequest(BaseModel):
    """Body for starting a model download."""

    repo_id: str = Field(description="Hugging Face repo id, e.g. 'org/model'.")
    filename: str | None = Field(
        default=None, description="Specific file to fetch (e.g. a GGUF); None = whole repo."
    )


class LoadRequest(BaseModel):
    """Body for loading a model."""

    backend: str | None = Field(default=None, description="Force a backend; None = auto-select.")
    config: RuntimeConfig | None = Field(default=None, description="Override launch params.")


class SystemResponse(BaseModel):
    """Combined hardware + backend availability report."""

    hardware: dict = Field(description="Detected host hardware.")
    backends: list[BackendInfo] = Field(description="Per-backend availability.")


class ModelView(ModelManifest):
    """A catalog manifest enriched with its current runtime state (if loaded)."""

    run: ModelRun | None = Field(default=None, description="Live run, or None if not loaded.")


# --- system / backends -----------------------------------------------------
@router.get("/system", response_model=SystemResponse)
def get_system(ctx: AppContext = Depends(get_context)) -> SystemResponse:
    """Report host hardware and which backend runners are installed."""
    return SystemResponse(
        hardware=detect_hardware().model_dump(),
        backends=[a.probe() for a in all_adapters()],
    )


# --- catalog ---------------------------------------------------------------
@router.get("/models", response_model=list[ModelView])
def list_models(ctx: AppContext = Depends(get_context)) -> list[ModelView]:
    """List every known model, merged with its live run state.

    Combines the persisted catalog (downloaded + previously searched) with the
    lifecycle manager's in-memory runs so the UI gets one unified list.
    """
    views: list[ModelView] = []
    for manifest in ctx.db.list_models():
        run = ctx.lifecycle.get_run(manifest.id)
        views.append(ModelView(**manifest.model_dump(), run=run))
    return views


@router.post("/models/search", response_model=list[ModelManifest])
async def search_models(
    body: SearchRequest, ctx: AppContext = Depends(get_context)
) -> list[ModelManifest]:
    """Search the remote catalog (Hugging Face Hub).

    The Hub client is blocking, so we run it in a thread to keep the event loop
    responsive.
    """
    return await asyncio.to_thread(ctx.catalog.search, body.query, body.limit)


@router.post("/models/download", response_model=ModelManifest)
async def download_model(
    body: DownloadRequest, ctx: AppContext = Depends(get_context)
) -> ModelManifest:
    """Download a model into the local store and register its manifest.

    Synchronous (awaited) in v1 for simplicity; progress streaming is a planned
    enhancement. The blocking download runs in a worker thread.
    """
    try:
        return await asyncio.to_thread(ctx.catalog.download, body.repo_id, body.filename)
    except Exception as exc:  # noqa: BLE001 — surface download failures to the client
        raise HTTPException(status_code=502, detail=f"Download failed: {exc}") from exc


@router.delete("/models/{model_id:path}")
async def delete_model(model_id: str, ctx: AppContext = Depends(get_context)) -> dict:
    """Remove a model from the catalog (and unload it if currently running).

    Note: the on-disk weight files are intentionally left in place in v1; only
    the catalog entry is removed. (File deletion is a follow-up.)
    """
    await ctx.lifecycle.unload(model_id, reason="model deleted")
    ctx.db.delete_model(model_id)
    return {"deleted": model_id}


# --- lifecycle -------------------------------------------------------------
@router.post("/models/{model_id:path}/load", response_model=ModelRun)
async def load_model(
    model_id: str, body: LoadRequest, ctx: AppContext = Depends(get_context)
) -> ModelRun:
    """Load a model onto a backend and wait for it to become ready."""
    try:
        return await ctx.lifecycle.load(model_id, body.backend, body.config)
    except ValueError as exc:
        # Unknown model / no compatible backend -> 400.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        # Memory budget exhausted -> 507 Insufficient Storage (memory).
        raise HTTPException(status_code=507, detail=str(exc)) from exc


@router.post("/models/{model_id:path}/unload")
async def unload_model(model_id: str, ctx: AppContext = Depends(get_context)) -> dict:
    """Stop a running model and free its memory."""
    await ctx.lifecycle.unload(model_id)
    return {"unloaded": model_id}


@router.get("/models/{model_id:path}/logs")
def model_logs(model_id: str, ctx: AppContext = Depends(get_context)) -> dict:
    """Return the buffered backend log lines for a running model."""
    return {"model_id": model_id, "logs": ctx.lifecycle.get_logs(model_id)}


# --- metrics / events / config --------------------------------------------
@router.get("/metrics")
def get_metrics(ctx: AppContext = Depends(get_context)) -> dict:
    """Return the latest metrics snapshot (one-shot poll alternative to the WS)."""
    return ctx.metrics.latest() or {"system": None, "models": []}


@router.get("/events")
def get_events(limit: int = 100, ctx: AppContext = Depends(get_context)) -> dict:
    """Return recent structured events (loads, unloads, evictions, errors...)."""
    return {"events": ctx.db.recent_events(limit)}


@router.get("/config")
def get_config(ctx: AppContext = Depends(get_context)) -> dict:
    """Return the effective configuration (secrets like the token are omitted)."""
    data = ctx.settings.model_dump(mode="json")
    data.pop("auth_token", None)  # never echo the secret back
    return data
