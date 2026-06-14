"""Host + accelerator detection.

We deliberately keep probing best-effort and dependency-free beyond ``psutil``:
GPU details come from shelling out to vendor tools (``nvidia-smi``) or inferring
from the platform (Apple Metal). Anything we cannot determine is reported as
zero/unknown rather than raising — detection must never crash the daemon.
"""

from __future__ import annotations

import platform
import shutil
import subprocess

import psutil

from llmode.schemas import AcceleratorInfo, HardwareInfo, SystemMetrics


def _detect_cuda() -> list[AcceleratorInfo]:
    """Return NVIDIA GPUs via ``nvidia-smi``, or [] if the tool is absent."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return []
    try:
        # Query name + total/used memory (MiB) as CSV without headers/units.
        out = subprocess.run(
            [smi, "--query-gpu=name,memory.total,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        # Tool present but failed (driver issue) — treat as no CUDA devices.
        return []

    gpus: list[AcceleratorInfo] = []
    for line in out.splitlines():
        name, total_mib, used_mib = (p.strip() for p in line.split(","))
        gpus.append(
            AcceleratorInfo(
                kind="cuda",
                name=name,
                vram_total_bytes=int(float(total_mib)) * 1024 * 1024,
                vram_used_bytes=int(float(used_mib)) * 1024 * 1024,
            )
        )
    return gpus


def _detect_metal() -> list[AcceleratorInfo]:
    """Report the Apple Silicon GPU on macOS/arm64.

    Apple Silicon uses *unified memory*, so VRAM is shared with system RAM; we
    report 0 VRAM here and let the budget logic treat it as RAM-bound instead.
    """
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return []
    return [AcceleratorInfo(kind="metal", name="Apple Silicon GPU", vram_total_bytes=0)]


def _detect_accelerators() -> list[AcceleratorInfo]:
    """Combine all accelerator probes; empty list means CPU-only."""
    return _detect_cuda() + _detect_metal()


def detect_hardware() -> HardwareInfo:
    """Build a :class:`HardwareInfo` describing this host's compute resources.

    Called once at startup and on demand (e.g. ``llmode doctor``). Values like
    OS/arch/CPU count are static; accelerator memory is a point-in-time read.
    """
    return HardwareInfo(
        os=platform.system().lower(),       # 'darwin' | 'linux'
        arch=platform.machine().lower(),     # 'arm64' | 'x86_64' | 'aarch64'
        cpu_count=psutil.cpu_count(logical=True) or 1,
        ram_total_bytes=psutil.virtual_memory().total,
        accelerators=_detect_accelerators(),
    )


def sample_system() -> SystemMetrics:
    """Take one live snapshot of host resource utilization.

    ``cpu_percent(interval=None)`` returns usage since the previous call, so the
    metrics collector's steady polling yields meaningful values without blocking.
    """
    vm = psutil.virtual_memory()
    return SystemMetrics(
        cpu_percent=psutil.cpu_percent(interval=None),
        ram_used_bytes=vm.used,
        ram_total_bytes=vm.total,
        accelerators=_detect_accelerators(),
    )
