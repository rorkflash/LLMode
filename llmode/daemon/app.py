"""FastAPI application factory + ``llmoded`` entry point.

Wires the routers, CORS, and the lifespan that builds/tears down the
:class:`AppContext`. ``main`` launches uvicorn for the ``llmoded`` console script.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from llmode import __version__
from llmode.config import get_settings
from llmode.daemon.context import AppContext
from llmode.daemon.routers import events, management, openai


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Build shared services on startup; dispose of them on shutdown.

    The yielded block is when the app serves requests. Everything before
    ``yield`` runs once at boot; everything after runs once at exit.
    """
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    ctx = AppContext.build(settings)
    await ctx.startup()
    # Expose the context to routers via app state.
    app.state.ctx = ctx
    try:
        yield
    finally:
        await ctx.shutdown()


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application instance.

    Kept separate from ``main`` so tests can build the app without starting a
    server.
    """
    settings = get_settings()
    app = FastAPI(title="LLMode", version=__version__, lifespan=_lifespan)

    # CORS: the React UI runs on a different origin (its dev server), so we must
    # explicitly allow it. Origins come from settings (REQUIREMENTS NFR-6).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount the three routers: control plane, inference proxy, live events.
    app.include_router(management.router)
    app.include_router(openai.router)
    app.include_router(events.router)

    @app.get("/healthz")
    def healthz() -> dict:
        """Liveness probe: returns OK once the app is serving."""
        return {"status": "ok", "version": __version__}

    return app


# Module-level app so `uvicorn llmode.daemon.app:app` also works.
app = create_app()


def main() -> None:
    """Console entry point for ``llmoded`` — run the daemon with uvicorn."""
    settings = get_settings()
    uvicorn.run(
        "llmode.daemon.app:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
