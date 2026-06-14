"""Periodic metrics sampling + live fan-out.

The collector runs a single background loop that, every ``metrics_interval``:
  1. Samples system utilization (CPU/RAM/accelerators).
  2. Builds per-model metrics from the lifecycle manager's live runs.
  3. Persists the system snapshot to SQLite (pruned to a rolling window).
  4. Broadcasts the combined snapshot to all WebSocket subscribers.

Subscribers are asyncio Queues; the daemon's WebSocket handler drains one queue
per connected client. This decouples sampling speed from client speed.
"""

from __future__ import annotations

import asyncio
import contextlib

import psutil

from llmode.config import Settings
from llmode.hardware import sample_system
from llmode.lifecycle import LifecycleManager
from llmode.schemas import ModelMetrics
from llmode.store import Database

# Keep ~1 hour of history at the default 2s cadence; bounds DB growth on SoCs.
_METRICS_RETENTION_SECONDS = 3600


class MetricsCollector:
    """Samples metrics on a timer and publishes them to subscribers."""

    def __init__(self, db: Database, lifecycle: LifecycleManager, settings: Settings) -> None:
        """Wire up dependencies; no sampling starts until :meth:`start`."""
        self._db = db
        self._lifecycle = lifecycle
        self._settings = settings
        # Set of subscriber queues; each connected WS client owns one.
        self._subscribers: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None
        # Cache of the most recent snapshot for HTTP polling clients.
        self._latest: dict | None = None

    # --- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        """Launch the background sampling loop."""
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Cancel the sampling loop on shutdown."""
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    # --- subscription (used by the WebSocket route) ------------------------
    def subscribe(self) -> asyncio.Queue:
        """Register a new subscriber and return its dedicated queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=10)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove a subscriber queue (on client disconnect)."""
        self._subscribers.discard(q)

    def latest(self) -> dict | None:
        """Return the most recent snapshot for one-shot HTTP polling."""
        return self._latest

    # --- internals ---------------------------------------------------------
    def _per_model_metrics(self) -> list[ModelMetrics]:
        """Build per-model metric records from current lifecycle runs.

        Throughput/TTFT would be fed by the proxy's request instrumentation in a
        fuller build; here we report state and resident memory of each runner.
        """
        out: list[ModelMetrics] = []
        for run in self._lifecycle.list_runs():
            resident = 0
            if run.pid and psutil.pid_exists(run.pid):
                with contextlib.suppress(psutil.Error):
                    resident = psutil.Process(run.pid).memory_info().rss
            out.append(
                ModelMetrics(model_id=run.model_id, state=run.state, resident_bytes=resident)
            )
        return out

    def _build_snapshot(self) -> dict:
        """Assemble the combined system + per-model snapshot as a plain dict."""
        system = sample_system()
        models = self._per_model_metrics()
        return {
            "system": system.model_dump(),
            "models": [m.model_dump() for m in models],
        }

    async def _broadcast(self, snapshot: dict) -> None:
        """Push a snapshot to every subscriber, dropping it for slow clients.

        We never block sampling on a slow consumer: if a queue is full we skip
        that client for this tick rather than awaiting space.
        """
        for q in list(self._subscribers):
            try:
                q.put_nowait(snapshot)
            except asyncio.QueueFull:
                # Client is behind; drop this frame for them and continue.
                pass

    async def _loop(self) -> None:
        """The sampling loop: sample, persist, broadcast, prune, repeat."""
        while True:
            snapshot = self._build_snapshot()
            self._latest = snapshot
            # Persist only the system part as the long-term time series.
            self._db.add_metrics(_dump_json(snapshot["system"]))
            await self._broadcast(snapshot)
            # Occasionally prune old rows so the DB stays small.
            self._db.prune_metrics(_METRICS_RETENTION_SECONDS)
            await asyncio.sleep(self._settings.metrics_interval_seconds)


def _dump_json(obj: dict) -> str:
    """Serialize a dict to compact JSON (small helper to avoid import noise)."""
    import json

    return json.dumps(obj, separators=(",", ":"))
