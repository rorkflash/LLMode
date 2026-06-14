"""Lifecycle package: model load/unload orchestration.

Exposes :class:`~llmode.lifecycle.supervisor.LifecycleManager`, which owns the
in-memory state of every running model, spawns/stops backend subprocesses,
enforces the memory budget (with LRU eviction), and auto-unloads idle models.
"""

from llmode.lifecycle.supervisor import LifecycleManager

__all__ = ["LifecycleManager"]
