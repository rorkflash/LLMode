"""Hardware detection package.

Exposes two functions used by the rest of the app:
    detect_hardware() -> static-ish description of the host (HardwareInfo).
    sample_system()   -> a live SystemMetrics snapshot.
"""

from llmode.hardware.probe import detect_hardware, sample_system

__all__ = ["detect_hardware", "sample_system"]
