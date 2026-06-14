"""The backend adapter abstraction.

An *adapter* knows how to turn a model + runtime config into a launchable
subprocess command, how to check that runner's health, and how to estimate its
memory cost. It does NOT manage processes itself — the lifecycle supervisor owns
process spawning so adapters stay small and testable.

Most modern runners already expose an OpenAI-compatible HTTP server, so the
default ``api_base_path`` is ``/v1`` and the proxy can forward requests
unchanged. Adapters that differ override the relevant hooks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from llmode.schemas import (
    BackendInfo,
    Health,
    MemoryEstimate,
    ModelManifest,
    RuntimeConfig,
)


class BackendAdapter(ABC):
    """Common contract every concrete backend must implement."""

    #: Stable adapter name used in the registry and persisted in runs.
    name: str = "base"
    #: HTTP path the runner mounts its OpenAI-compatible API under.
    api_base_path: str = "/v1"

    @abstractmethod
    def probe(self) -> BackendInfo:
        """Report whether this runner is installed and usable on the host.

        Implementations should locate the binary, read its version, and return
        an install hint in ``detail`` when unavailable. Must never raise.
        """

    @abstractmethod
    def supports(self, model: ModelManifest) -> bool:
        """Return True if this backend can run the given model.

        Decision is based on weight format and (implicitly) host hardware —
        e.g. the MLX adapter only supports ``mlx`` models on Apple Silicon.
        """

    @abstractmethod
    def launch_command(
        self, model: ModelManifest, cfg: RuntimeConfig, port: int
    ) -> list[str]:
        """Build the argv list to start the runner serving ``model`` on ``port``.

        The supervisor executes this verbatim. ``cfg`` fields that are ``None``
        are omitted so the runner applies its own defaults.
        """

    def estimate_memory(
        self, model: ModelManifest, cfg: RuntimeConfig
    ) -> MemoryEstimate:
        """Estimate the memory needed to load ``model``.

        Default heuristic: assume the resident footprint is roughly the on-disk
        size plus ~20% overhead for KV-cache/buffers, charged to RAM. Backends
        that offload to GPU override this to split RAM/VRAM appropriately.
        """
        overhead = int(model.size_bytes * 1.2)
        return MemoryEstimate(ram_bytes=overhead, vram_bytes=0)

    async def health(self, base_url: str) -> Health:
        """Probe readiness by hitting the runner's models endpoint.

        Works for any OpenAI-compatible server: a 200 from ``/v1/models`` means
        it is up and serving. Overridable for runners with bespoke health paths.
        """
        url = f"{base_url}{self.api_base_path}/models"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(url)
            return Health(ready=resp.status_code == 200, detail=f"HTTP {resp.status_code}")
        except httpx.HTTPError as exc:
            # Connection refused while warming up is expected — report not-ready.
            return Health(ready=False, detail=str(exc))
