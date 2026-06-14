"""Metrics package.

Exposes :class:`~llmode.metrics.collector.MetricsCollector`, which periodically
samples host + per-model metrics, persists a rolling history, and fans live
snapshots out to WebSocket subscribers.
"""

from llmode.metrics.collector import MetricsCollector

__all__ = ["MetricsCollector"]
