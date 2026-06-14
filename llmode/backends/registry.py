"""Backend registry + automatic selection.

Holds the set of known adapters and implements the "pick the right backend"
policy from ARCHITECTURE §4: prefer the platform-optimal runner, fall back to
llama.cpp (the universal GGUF path) when nothing better matches.
"""

from __future__ import annotations

from llmode.backends.base import BackendAdapter
from llmode.backends.llamacpp import LlamaCppAdapter
from llmode.backends.mlx import MlxAdapter
from llmode.backends.ollama import OllamaAdapter
from llmode.backends.vllm import VllmAdapter
from llmode.schemas import ModelManifest

# Instantiate one adapter of each kind. Adapters are stateless, so module-level
# singletons are fine and cheap.
_ADAPTERS: dict[str, BackendAdapter] = {
    a.name: a
    for a in (LlamaCppAdapter(), MlxAdapter(), VllmAdapter(), OllamaAdapter())
}

# Preference order when auto-selecting. Earlier = higher priority. The platform
# guards inside each adapter's ``supports``/``probe`` ensure only valid ones win.
_PREFERENCE = ("mlx", "vllm", "llama.cpp", "ollama")


def all_adapters() -> list[BackendAdapter]:
    """Return every registered adapter (used for ``probe``/doctor output)."""
    return list(_ADAPTERS.values())


def get_adapter(name: str) -> BackendAdapter | None:
    """Look up an adapter by its name, or None if unregistered."""
    return _ADAPTERS.get(name)


def select_backend(model: ModelManifest) -> BackendAdapter | None:
    """Choose the best *available* backend that can run ``model``.

    A candidate qualifies only when it both ``supports`` the model's format and
    is actually installed (``probe().available``). We honour ``_PREFERENCE`` so
    the platform-optimal runner is chosen ahead of the universal fallback.
    Returns None when no installed backend can run the model.
    """
    for name in _PREFERENCE:
        adapter = _ADAPTERS.get(name)
        if adapter and adapter.supports(model) and adapter.probe().available:
            return adapter
    return None
