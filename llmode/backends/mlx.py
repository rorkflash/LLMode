"""MLX backend adapter — fastest path on Apple Silicon.

Apple's MLX framework ships ``mlx_lm.server`` (from the ``mlx-lm`` package),
an OpenAI-compatible server optimized for Metal + unified memory. This adapter
is only usable on macOS/arm64.
"""

from __future__ import annotations

import platform
import shutil
import subprocess

import httpx

from llmode.backends.base import BackendAdapter
from llmode.schemas import (
    BackendInfo,
    Health,
    MemoryEstimate,
    ModelFormat,
    ModelManifest,
    RuntimeConfig,
)


class MlxAdapter(BackendAdapter):
    """Adapter that drives ``mlx_lm.server`` on Apple Silicon."""

    name = "mlx"

    @staticmethod
    def _is_apple_silicon() -> bool:
        """True only on macOS running on an arm64 (Apple Silicon) CPU."""
        return platform.system() == "Darwin" and platform.machine() == "arm64"

    def _find_binary(self) -> str | None:
        """Locate the ``mlx_lm.server`` entry point on PATH."""
        return shutil.which("mlx_lm.server")

    def probe(self) -> BackendInfo:
        """Report availability — requires both Apple Silicon and the mlx-lm pkg."""
        if not self._is_apple_silicon():
            return BackendInfo(
                name=self.name,
                available=False,
                detail="MLX requires macOS on Apple Silicon.",
            )
        path = self._find_binary()
        if not path:
            return BackendInfo(
                name=self.name,
                available=False,
                detail="mlx_lm.server not found. Install with `pip install mlx-lm`.",
            )
        version = None
        try:
            # mlx-lm exposes its version via the python package metadata.
            out = subprocess.run(
                ["python", "-c", "import mlx_lm,importlib.metadata as m;"
                 "print(m.version('mlx-lm'))"],
                capture_output=True, text=True, timeout=5,
            )
            version = out.stdout.strip() or None
        except (subprocess.SubprocessError, OSError):
            version = None
        return BackendInfo(name=self.name, available=True, version=version, path=path)

    def supports(self, model: ModelManifest) -> bool:
        """MLX runs MLX-format models, and only on Apple Silicon."""
        return self._is_apple_silicon() and model.format == ModelFormat.MLX

    def estimate_memory(
        self, model: ModelManifest, cfg: RuntimeConfig
    ) -> MemoryEstimate:
        """On unified-memory Macs all of it counts as RAM (no separate VRAM)."""
        return MemoryEstimate(ram_bytes=int(model.size_bytes * 1.2), vram_bytes=0)

    def launch_command(
        self, model: ModelManifest, cfg: RuntimeConfig, port: int
    ) -> list[str]:
        """Build the ``mlx_lm.server`` argv.

        MLX takes a model *path or HF repo id* via ``--model`` and serves an
        OpenAI-compatible API. Fewer knobs than llama.cpp; we map what exists.
        """
        binary = self._find_binary() or "mlx_lm.server"
        cmd = [
            binary,
            "--model", model.path or model.id,
            "--host", "127.0.0.1",
            "--port", str(port),
        ]
        cmd += cfg.extra_args
        return cmd

    async def health(self, base_url: str) -> Health:
        """Readiness probe tolerant of mlx_lm.server's endpoint differences.

        Some mlx-lm versions do not implement ``/v1/models``; a 404 still means
        the HTTP server is up and able to accept completion requests. So we treat
        any response below 500 (i.e. the server answered) as ready.
        """
        url = f"{base_url}{self.api_base_path}/models"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(url)
            return Health(ready=resp.status_code < 500, detail=f"HTTP {resp.status_code}")
        except httpx.HTTPError as exc:
            # Connection refused while the server is still starting up.
            return Health(ready=False, detail=str(exc))
