"""Application context — the daemon's dependency container.

Bundles the long-lived singletons (settings, DB, catalog, lifecycle, metrics)
so routers can pull them off ``request.app.state.ctx`` instead of constructing
globals. Created once during the app's lifespan startup and torn down on exit.
"""

from __future__ import annotations

from dataclasses import dataclass

from llmode.catalog import CatalogService
from llmode.config import Settings
from llmode.lifecycle import LifecycleManager
from llmode.metrics import MetricsCollector
from llmode.store import Database


@dataclass
class AppContext:
    """Holds every shared service the request handlers need."""

    settings: Settings           # Effective configuration.
    db: Database                 # SQLite persistence layer.
    catalog: CatalogService      # Remote search + downloads.
    lifecycle: LifecycleManager  # Load/unload + process supervision.
    metrics: MetricsCollector    # Sampling + live fan-out.

    @classmethod
    def build(cls, settings: Settings) -> "AppContext":
        """Construct the full object graph from settings.

        Order matters: the DB underpins everything; lifecycle needs the DB;
        metrics needs both the DB and lifecycle.
        """
        db = Database(settings.db_path)
        lifecycle = LifecycleManager(db, settings)
        return cls(
            settings=settings,
            db=db,
            catalog=CatalogService(db, settings.models_dir),
            lifecycle=lifecycle,
            metrics=MetricsCollector(db, lifecycle, settings),
        )

    async def startup(self) -> None:
        """Start background tasks (process reaping, idle sweep, metrics loop)."""
        await self.lifecycle.start()
        await self.metrics.start()

    async def shutdown(self) -> None:
        """Stop background tasks and release resources cleanly."""
        await self.metrics.stop()
        await self.lifecycle.stop()
        self.db.close()
