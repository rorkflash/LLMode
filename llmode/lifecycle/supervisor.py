"""The lifecycle manager / process supervisor.

Responsibilities (ARCHITECTURE §5 & §8):
  * Track every loaded model as a :class:`ModelRun` in memory (source of truth).
  * Spawn backend runners as subprocesses, allocate ports, capture logs.
  * Wait for readiness via the adapter's health probe.
  * Enforce a RAM/VRAM budget before loading; evict idle models (LRU) to fit.
  * Auto-unload models idle longer than the configured TTL.
  * Reap orphaned processes left by a previous daemon crash.

Everything here is async so it cooperates with the FastAPI event loop. Process
state mutations are guarded by a single lock to avoid races between concurrent
load requests and the idle-sweep task.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import time
from collections import deque

import psutil

from llmode.backends import get_adapter, select_backend
from llmode.config import Settings
from llmode.hardware import detect_hardware, sample_system
from llmode.schemas import ModelRun, ModelState, RuntimeConfig
from llmode.store import Database

# How many log lines to retain per running model (ring buffer for the UI).
_LOG_BUFFER_LINES = 500


class _ManagedProcess:
    """Internal bookkeeping for one running backend subprocess."""

    def __init__(self, run: ModelRun, proc: asyncio.subprocess.Process, run_id: int) -> None:
        #: The public run record (state, pid, port, timestamps).
        self.run = run
        #: The asyncio subprocess handle used to signal/terminate it.
        self.proc = proc
        #: DB row id so we can mark the run stopped on shutdown.
        self.run_id = run_id
        #: Rolling log buffer fed by the stdout/stderr reader tasks.
        self.logs: deque[str] = deque(maxlen=_LOG_BUFFER_LINES)


def _free_port() -> int:
    """Ask the OS for an unused localhost TCP port and return it.

    We bind to port 0, read the assigned port, then close — a small race window
    exists but is acceptable for a single-host homelab tool.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LifecycleManager:
    """Owns all running models and their backend processes."""

    def __init__(self, db: Database, settings: Settings) -> None:
        """Store dependencies and prepare in-memory state (nothing spawned yet)."""
        self._db = db
        self._settings = settings
        # model_id -> managed process. Presence here means "loaded or loading".
        self._procs: dict[str, _ManagedProcess] = {}
        # Serializes load/unload/evict so budget math stays consistent.
        self._lock = asyncio.Lock()
        # Handle to the background idle-sweep task (started in ``start``).
        self._idle_task: asyncio.Task | None = None

    # --- startup / shutdown ------------------------------------------------
    async def start(self) -> None:
        """Reap orphans from a prior crash and launch the idle-sweep loop."""
        self._reap_orphans()
        self._idle_task = asyncio.create_task(self._idle_sweep_loop())

    async def stop(self) -> None:
        """Cancel background tasks and stop every running model gracefully."""
        if self._idle_task:
            self._idle_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._idle_task
        # Unload everything so no subprocess is left running after we exit.
        for model_id in list(self._procs):
            await self.unload(model_id, reason="daemon shutdown")

    def _reap_orphans(self) -> None:
        """Kill subprocesses recorded as running but never marked stopped.

        After a daemon crash the runner children may survive; we match recorded
        pids and terminate any that are still alive, then close the DB run rows.
        """
        for row in self._db.list_orphan_runs():
            pid = row["pid"]
            if pid and psutil.pid_exists(pid):
                with contextlib.suppress(psutil.Error):
                    psutil.Process(pid).terminate()
            self._db.record_run_stop(row["id"], reason="reaped orphan on startup")

    # --- introspection -----------------------------------------------------
    def list_runs(self) -> list[ModelRun]:
        """Return the current run record for every loaded/loading model."""
        return [mp.run for mp in self._procs.values()]

    def get_run(self, model_id: str) -> ModelRun | None:
        """Return the run record for ``model_id`` if it is loaded, else None."""
        mp = self._procs.get(model_id)
        return mp.run if mp else None

    def get_logs(self, model_id: str) -> list[str]:
        """Return the buffered log lines for a running model (empty if none)."""
        mp = self._procs.get(model_id)
        return list(mp.logs) if mp else []

    # --- public lifecycle operations --------------------------------------
    async def ensure_loaded(self, model_id: str) -> ModelRun:
        """Return a ready run for ``model_id``, lazy-loading it if necessary.

        Called by the inference proxy. If the model is already READY/IDLE we just
        refresh its last-used timestamp; otherwise we trigger a full load.
        """
        mp = self._procs.get(model_id)
        if mp and mp.run.state in (ModelState.READY, ModelState.IDLE):
            mp.run.last_used_at = time.time()
            mp.run.state = ModelState.READY  # a request brings an idle model back
            return mp.run
        return await self.load(model_id)

    async def load(
        self,
        model_id: str,
        backend_name: str | None = None,
        config: RuntimeConfig | None = None,
    ) -> ModelRun:
        """Load a model: pick a backend, free memory if needed, spawn, await ready.

        Raises ``ValueError`` for unknown models / no compatible backend, and
        ``RuntimeError`` when the memory budget cannot be satisfied even after
        evicting idle models.
        """
        async with self._lock:
            # Idempotency: if already loaded, return the existing run.
            existing = self._procs.get(model_id)
            if existing and existing.run.state in (ModelState.READY, ModelState.IDLE):
                return existing.run

            manifest = self._db.get_model(model_id)
            if manifest is None or not manifest.is_local:
                raise ValueError(f"Model '{model_id}' is not available locally.")

            # Resolve the backend: explicit choice or auto-selection.
            adapter = get_adapter(backend_name) if backend_name else select_backend(manifest)
            if adapter is None or not adapter.supports(manifest):
                raise ValueError(f"No usable backend for model '{model_id}'.")

            cfg = config or manifest.default_config

            # Budget guard: estimate cost and evict idle models (LRU) to fit.
            estimate = adapter.estimate_memory(manifest, cfg)
            self._ensure_capacity(estimate.ram_bytes, estimate.vram_bytes)

            # Spawn the runner subprocess on a fresh port.
            port = _free_port()
            run = ModelRun(
                model_id=model_id,
                backend=adapter.name,
                state=ModelState.LOADING,
                port=port,
                base_url=f"http://127.0.0.1:{port}",
            )
            cmd = adapter.launch_command(manifest, cfg, port)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,  # merge streams into one buffer
            )
            run.pid = proc.pid
            run_id = self._db.record_run_start(model_id, adapter.name, proc.pid, port)
            mp = _ManagedProcess(run, proc, run_id)
            self._procs[model_id] = mp

            # Stream the runner's output into the ring buffer in the background.
            asyncio.create_task(self._pump_logs(mp))
            self._db.add_event("load", f"Loading {model_id} on {adapter.name}", model_id)

        # Wait for readiness OUTSIDE the lock so other reads aren't blocked.
        await self._await_ready(model_id, adapter)
        return self._procs[model_id].run

    async def unload(self, model_id: str, reason: str = "manual") -> None:
        """Stop a model's backend process and forget its run."""
        mp = self._procs.get(model_id)
        if not mp:
            return
        mp.run.state = ModelState.UNLOADING
        # Graceful terminate, then hard kill if it ignores SIGTERM.
        with contextlib.suppress(ProcessLookupError):
            mp.proc.terminate()
            try:
                await asyncio.wait_for(mp.proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                mp.proc.kill()
        self._db.record_run_stop(mp.run_id, reason)
        self._db.add_event("unload", f"Unloaded {model_id} ({reason})", model_id)
        self._procs.pop(model_id, None)

    # --- readiness + log pumping ------------------------------------------
    async def _await_ready(self, model_id: str, adapter, timeout: float = 120.0) -> None:
        """Poll the backend health endpoint until ready or timeout/crash.

        Marks the run READY on success, ERROR on failure (process exit or
        timeout). Runs after the subprocess is spawned.
        """
        mp = self._procs.get(model_id)
        if not mp:
            return
        deadline = time.time() + timeout
        while time.time() < deadline:
            # If the process already exited, it failed to start.
            if mp.proc.returncode is not None:
                mp.run.state = ModelState.ERROR
                mp.run.error = f"Backend exited early (code {mp.proc.returncode})."
                self._db.add_event("crash", mp.run.error, model_id)
                return
            health = await adapter.health(mp.run.base_url)
            if health.ready:
                mp.run.state = ModelState.READY
                mp.run.last_used_at = time.time()
                self._db.add_event("load", f"{model_id} ready", model_id)
                return
            await asyncio.sleep(1.0)
        # Timed out waiting for readiness.
        mp.run.state = ModelState.ERROR
        mp.run.error = "Timed out waiting for backend readiness."
        self._db.add_event("error", mp.run.error, model_id)

    async def _pump_logs(self, mp: _ManagedProcess) -> None:
        """Continuously read the subprocess output into its log ring buffer."""
        assert mp.proc.stdout is not None
        while True:
            line = await mp.proc.stdout.readline()
            if not line:  # EOF — the process has closed its output stream.
                break
            mp.logs.append(line.decode(errors="replace").rstrip())

    # --- memory budget + eviction -----------------------------------------
    def _ensure_capacity(self, need_ram: int, need_vram: int) -> None:
        """Free enough memory for a pending load by evicting idle models (LRU).

        Raises ``RuntimeError`` if the requirement cannot be met even after
        evicting every idle model (we never evict a model that is actively READY
        and recently used — only IDLE ones).
        """
        if self._fits(need_ram, need_vram):
            return
        # Candidate idle models, least-recently-used first.
        idle = sorted(
            (mp for mp in self._procs.values() if mp.run.state == ModelState.IDLE),
            key=lambda mp: mp.run.last_used_at,
        )
        for mp in idle:
            self._db.add_event(
                "evict", f"Evicting idle {mp.run.model_id} to free memory", mp.run.model_id
            )
            # Synchronous best-effort terminate; the async unload path also exists
            # but capacity checks run inside the load lock.
            with contextlib.suppress(ProcessLookupError):
                mp.proc.terminate()
            self._db.record_run_stop(mp.run_id, reason="evicted (budget)")
            self._procs.pop(mp.run.model_id, None)
            if self._fits(need_ram, need_vram):
                return
        if not self._fits(need_ram, need_vram):
            raise RuntimeError(
                "Insufficient memory to load model even after evicting idle models."
            )

    def _fits(self, need_ram: int, need_vram: int) -> bool:
        """Check a prospective load against the configured RAM/VRAM budgets."""
        hw = detect_hardware()
        sys_metrics = sample_system()

        # RAM budget: ceiling = fraction of total; available headroom = ceiling
        # minus what's already used system-wide.
        ram_ceiling = hw.ram_total_bytes * self._settings.ram_budget_fraction
        ram_headroom = ram_ceiling - sys_metrics.ram_used_bytes
        if need_ram > ram_headroom:
            return False

        # VRAM budget: only enforced when we have discrete-memory accelerators.
        if need_vram > 0:
            total_vram = sum(a.vram_total_bytes for a in hw.accelerators)
            used_vram = sum(a.vram_used_bytes for a in hw.accelerators)
            vram_ceiling = total_vram * self._settings.vram_budget_fraction
            if need_vram > (vram_ceiling - used_vram):
                return False
        return True

    # --- idle auto-unload --------------------------------------------------
    async def _idle_sweep_loop(self) -> None:
        """Background task: periodically demote/unload idle models per TTL.

        A READY model with no requests for ``idle_ttl_seconds`` is first marked
        IDLE (so the UI can show it), then unloaded on the following sweep if it
        is still unused.
        """
        ttl = self._settings.idle_ttl_seconds
        while True:
            await asyncio.sleep(max(5.0, self._settings.metrics_interval_seconds))
            now = time.time()
            for model_id, mp in list(self._procs.items()):
                idle_for = now - mp.run.last_used_at
                if mp.run.state == ModelState.READY and idle_for > ttl:
                    # First crossing of the TTL: mark idle, keep it loaded briefly.
                    mp.run.state = ModelState.IDLE
                elif mp.run.state == ModelState.IDLE and idle_for > ttl * 2:
                    # Still unused after a grace period: free the memory.
                    await self.unload(model_id, reason="idle TTL")
