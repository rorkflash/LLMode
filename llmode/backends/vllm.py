"""vLLM backend adapter — high-throughput inference on NVIDIA GPUs.

vLLM provides ``vllm serve`` (an OpenAI-compatible server) optimized for batched
GPU inference. It is GPU-only and heavyweight, so in v1 we treat it as
*best-effort / experimental* (see REQUIREMENTS OQ-5): available when the package
and a CUDA device are present, otherwise reported unavailable.
"""

from __future__ import annotations

import shutil
import subprocess

from llmode.backends.base import BackendAdapter
from llmode.hardware import detect_hardware
from llmode.schemas import (
    BackendInfo,
    MemoryEstimate,
    ModelFormat,
    ModelManifest,
    RuntimeConfig,
)


class VllmAdapter(BackendAdapter):
    """Adapter that drives ``vllm serve``."""

    name = "vllm"

    @staticmethod
    def _has_cuda() -> bool:
        """True when at least one CUDA accelerator was detected on the host."""
        return any(a.kind == "cuda" for a in detect_hardware().accelerators)

    def _find_binary(self) -> str | None:
        """Locate the ``vllm`` CLI on PATH."""
        return shutil.which("vllm")

    def probe(self) -> BackendInfo:
        """Available only with both the ``vllm`` CLI and a CUDA GPU present."""
        path = self._find_binary()
        if not path:
            return BackendInfo(
                name=self.name,
                available=False,
                detail="vllm not found. Install with `pip install vllm` (Linux + NVIDIA GPU).",
            )
        if not self._has_cuda():
            return BackendInfo(
                name=self.name,
                available=False,
                path=path,
                detail="vLLM requires an NVIDIA CUDA GPU; none detected.",
            )
        version = None
        try:
            out = subprocess.run(
                [path, "--version"], capture_output=True, text=True, timeout=5
            )
            version = (out.stdout or out.stderr).strip() or None
        except (subprocess.SubprocessError, OSError):
            version = None
        return BackendInfo(name=self.name, available=True, version=version, path=path)

    def supports(self, model: ModelManifest) -> bool:
        """vLLM serves HF safetensors checkpoints on CUDA hardware."""
        return self._has_cuda() and model.format == ModelFormat.SAFETENSORS

    def estimate_memory(
        self, model: ModelManifest, cfg: RuntimeConfig
    ) -> MemoryEstimate:
        """vLLM loads weights into VRAM; charge the footprint to GPU memory."""
        return MemoryEstimate(ram_bytes=0, vram_bytes=int(model.size_bytes * 1.3))

    def launch_command(
        self, model: ModelManifest, cfg: RuntimeConfig, port: int
    ) -> list[str]:
        """Build the ``vllm serve`` argv for this model + config."""
        binary = self._find_binary() or "vllm"
        cmd = [
            binary, "serve", model.path or model.id,
            "--host", "127.0.0.1",
            "--port", str(port),
        ]
        if cfg.context_length is not None:
            cmd += ["--max-model-len", str(cfg.context_length)]
        cmd += cfg.extra_args
        return cmd
