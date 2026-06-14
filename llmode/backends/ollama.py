"""Ollama backend adapter — optional convenience wrapper.

Unlike the other adapters, Ollama runs its own long-lived daemon and manages
models itself. We integrate it as a pass-through: if the user already runs
Ollama, LLMode can route OpenAI-compatible traffic to it (Ollama exposes
``/v1``) without LLMode supervising the process lifecycle the same way.

In v1 this adapter mainly advertises availability; deeper integration (listing
Ollama's own models, pulling via Ollama) is a future enhancement.
"""

from __future__ import annotations

import shutil
import subprocess

from llmode.backends.base import BackendAdapter
from llmode.schemas import BackendInfo, ModelFormat, ModelManifest, RuntimeConfig


class OllamaAdapter(BackendAdapter):
    """Adapter that defers model execution to a running Ollama daemon."""

    name = "ollama"

    def _find_binary(self) -> str | None:
        """Locate the ``ollama`` CLI on PATH."""
        return shutil.which("ollama")

    def probe(self) -> BackendInfo:
        """Report whether the ``ollama`` CLI is installed."""
        path = self._find_binary()
        if not path:
            return BackendInfo(
                name=self.name,
                available=False,
                detail="ollama not found. Install from https://ollama.com.",
            )
        version = None
        try:
            out = subprocess.run(
                [path, "--version"], capture_output=True, text=True, timeout=5
            )
            version = out.stdout.strip() or None
        except (subprocess.SubprocessError, OSError):
            version = None
        return BackendInfo(name=self.name, available=True, version=version, path=path)

    def supports(self, model: ModelManifest) -> bool:
        """Ollama internally uses GGUF; we mark GGUF models as supported.

        Note: actual serving is delegated to the Ollama daemon, so this is only
        meaningful when the user opts into the Ollama backend explicitly.
        """
        return model.format == ModelFormat.GGUF

    def launch_command(
        self, model: ModelManifest, cfg: RuntimeConfig, port: int
    ) -> list[str]:
        """Start an Ollama model server bound to ``port``.

        ``ollama serve`` honours OLLAMA_HOST; we set it via the command's env in
        the supervisor. Here we return the serve invocation; model loading in
        Ollama happens lazily on first request to its API.
        """
        binary = self._find_binary() or "ollama"
        # Ollama reads the bind address from the OLLAMA_HOST env var rather than
        # flags; the supervisor sets it. We still pass `serve` as the command.
        return [binary, "serve"]
