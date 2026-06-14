"""Backend adapters package.

Each adapter wraps one external inference runner (llama.cpp, MLX, vLLM, Ollama)
behind the common :class:`~llmode.backends.base.BackendAdapter` interface. The
registry here lets the lifecycle manager pick an adapter by name or auto-select
the best one for the current hardware + model.
"""

from llmode.backends.base import BackendAdapter
from llmode.backends.registry import (
    all_adapters,
    get_adapter,
    select_backend,
)

__all__ = ["BackendAdapter", "all_adapters", "get_adapter", "select_backend"]
