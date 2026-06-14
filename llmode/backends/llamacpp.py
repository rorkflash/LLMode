"""llama.cpp backend adapter — the universal GGUF fallback.

llama.cpp ships ``llama-server``, an OpenAI-compatible HTTP server. It runs on
virtually every platform (CPU, CUDA, Metal, ROCm) which is why we treat it as
the default everywhere a GGUF model is available.
"""

from __future__ import annotations

import shutil
import subprocess

from llmode.backends.base import BackendAdapter
from llmode.schemas import BackendInfo, ModelFormat, ModelManifest, RuntimeConfig


class LlamaCppAdapter(BackendAdapter):
    """Adapter that drives ``llama-server`` from llama.cpp."""

    name = "llama.cpp"

    #: Candidate binary names across distributions/build flavours.
    _BINARIES = ("llama-server", "server")

    def _find_binary(self) -> str | None:
        """Return the first llama.cpp server binary found on PATH, else None."""
        for candidate in self._BINARIES:
            path = shutil.which(candidate)
            if path:
                return path
        return None

    def probe(self) -> BackendInfo:
        """Locate ``llama-server`` and read its ``--version`` banner."""
        path = self._find_binary()
        if not path:
            return BackendInfo(
                name=self.name,
                available=False,
                detail="llama-server not found. Install llama.cpp (e.g. `brew install llama.cpp`).",
            )
        version = None
        try:
            # llama-server prints version info and exits with --version.
            out = subprocess.run(
                [path, "--version"], capture_output=True, text=True, timeout=5
            )
            version = (out.stdout or out.stderr).strip().splitlines()[0] if out else None
        except (subprocess.SubprocessError, OSError, IndexError):
            version = None
        return BackendInfo(name=self.name, available=True, version=version, path=path)

    def supports(self, model: ModelManifest) -> bool:
        """llama.cpp runs GGUF weights only."""
        return model.format == ModelFormat.GGUF

    def launch_command(
        self, model: ModelManifest, cfg: RuntimeConfig, port: int
    ) -> list[str]:
        """Construct the ``llama-server`` argv for this model + config.

        We bind to localhost; the supervisor allocated ``port``. Optional tuning
        flags are appended only when the corresponding config field is set.
        """
        binary = self._find_binary() or "llama-server"
        cmd = [
            binary,
            "--model", model.path or "",   # path validated before launch by the supervisor
            "--host", "127.0.0.1",
            "--port", str(port),
        ]
        # Map RuntimeConfig fields onto llama-server flags when provided.
        if cfg.context_length is not None:
            cmd += ["--ctx-size", str(cfg.context_length)]
        if cfg.n_gpu_layers is not None:
            cmd += ["--n-gpu-layers", str(cfg.n_gpu_layers)]
        if cfg.threads is not None:
            cmd += ["--threads", str(cfg.threads)]
        # Pass through any raw user-supplied flags last so they can override.
        cmd += cfg.extra_args
        return cmd
