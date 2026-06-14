"""Shared domain models for LLMode.

Every layer (store, backends, lifecycle, daemon API, CLI) speaks in terms of
these Pydantic types so we have one consistent vocabulary. Keeping them in a
single module avoids circular imports between the feature packages.
"""

from __future__ import annotations

import time
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class ModelFormat(str, Enum):
    """On-disk weight format — determines which backends can run a model."""

    GGUF = "gguf"            # llama.cpp's quantized format (universal fallback).
    MLX = "mlx"              # Apple MLX format (macOS / Apple Silicon).
    SAFETENSORS = "safetensors"  # HF native weights (vLLM, transformers).
    UNKNOWN = "unknown"      # Format could not be determined.


class ModelState(str, Enum):
    """Lifecycle state of a model, mirrored in the UI.

    Transitions (see ARCHITECTURE §5):
        AVAILABLE -> LOADING -> READY -> IDLE -> UNLOADING -> AVAILABLE
        any active state -> ERROR on failure.
    """

    AVAILABLE = "available"    # On disk, not running.
    LOADING = "loading"        # Subprocess starting / warming up.
    READY = "ready"            # Healthy and serving requests.
    IDLE = "idle"              # Ready but unused; eligible for auto-unload.
    UNLOADING = "unloading"    # Being stopped.
    ERROR = "error"            # Crashed or failed to start.


# ---------------------------------------------------------------------------
# Model configuration + manifest
# ---------------------------------------------------------------------------
class RuntimeConfig(BaseModel):
    """Tunable launch parameters applied when a model is loaded.

    These map onto backend-specific CLI flags inside each adapter. Unset
    (``None``) fields fall back to the backend's own defaults.
    """

    context_length: int | None = Field(
        default=None, description="Max context window (tokens) to allocate."
    )
    n_gpu_layers: int | None = Field(
        default=None, description="Layers offloaded to GPU (llama.cpp). None = backend default."
    )
    threads: int | None = Field(
        default=None, description="CPU threads for inference."
    )
    temperature: float | None = Field(
        default=None, description="Default sampling temperature."
    )
    extra_args: list[str] = Field(
        default_factory=list, description="Raw extra flags passed verbatim to the runner."
    )


class ModelManifest(BaseModel):
    """Everything LLMode knows about a single model.

    A manifest is created when a model is downloaded/imported and persisted in
    SQLite. ``path`` is populated only once the weights are present locally.
    """

    id: str = Field(description="Stable unique id, e.g. 'TheBloke/Llama-2-7B-GGUF:Q4_K_M'.")
    name: str = Field(description="Human-friendly display name.")
    source: str = Field(default="huggingface", description="Origin registry/source.")
    format: ModelFormat = Field(default=ModelFormat.UNKNOWN, description="Weight format.")
    quantization: str | None = Field(default=None, description="Quant label, e.g. 'Q4_K_M'.")
    size_bytes: int = Field(default=0, description="On-disk size in bytes (0 if unknown).")
    path: str | None = Field(default=None, description="Local filesystem path once downloaded.")
    backends: list[str] = Field(
        default_factory=list, description="Names of backends able to run this model."
    )
    default_config: RuntimeConfig = Field(
        default_factory=RuntimeConfig, description="Saved default launch params."
    )

    @property
    def is_local(self) -> bool:
        """True when the weights have been downloaded to disk."""
        return self.path is not None


# ---------------------------------------------------------------------------
# Backend + capability descriptors
# ---------------------------------------------------------------------------
class BackendInfo(BaseModel):
    """Result of probing whether a backend runner is installed and usable."""

    name: str = Field(description="Adapter name: llama.cpp | mlx | vllm | ollama.")
    available: bool = Field(description="Whether the runner binary was found.")
    version: str | None = Field(default=None, description="Detected runner version.")
    path: str | None = Field(default=None, description="Resolved binary path.")
    detail: str | None = Field(default=None, description="Install hint or error if unavailable.")


class Health(BaseModel):
    """Readiness result from probing a running backend process."""

    ready: bool = Field(description="True when the backend can serve requests.")
    detail: str | None = Field(default=None, description="Diagnostic message.")


class MemoryEstimate(BaseModel):
    """Predicted memory footprint of loading a model (used by the budget guard)."""

    ram_bytes: int = Field(default=0, description="Estimated system RAM required.")
    vram_bytes: int = Field(default=0, description="Estimated GPU VRAM required.")


# ---------------------------------------------------------------------------
# Runtime / lifecycle records
# ---------------------------------------------------------------------------
class ModelRun(BaseModel):
    """A live (or recently finished) load of a model on a backend process."""

    model_id: str = Field(description="Manifest id of the loaded model.")
    backend: str = Field(description="Backend adapter running it.")
    state: ModelState = Field(default=ModelState.LOADING, description="Current state.")
    pid: int | None = Field(default=None, description="OS process id of the runner.")
    port: int | None = Field(default=None, description="Local port the runner listens on.")
    base_url: str | None = Field(default=None, description="http://127.0.0.1:<port> base URL.")
    started_at: float = Field(default_factory=time.time, description="Unix start time.")
    last_used_at: float = Field(default_factory=time.time, description="Last request time (for TTL/LRU).")
    error: str | None = Field(default=None, description="Error message if state == ERROR.")


# ---------------------------------------------------------------------------
# Hardware / metrics
# ---------------------------------------------------------------------------
class AcceleratorInfo(BaseModel):
    """A single GPU/NPU accelerator discovered on the host."""

    kind: str = Field(description="Accelerator kind: metal | cuda | rocm | none.")
    name: str = Field(description="Device name.")
    vram_total_bytes: int = Field(default=0, description="Total VRAM.")
    vram_used_bytes: int = Field(default=0, description="VRAM currently in use.")


class HardwareInfo(BaseModel):
    """Static-ish description of the host's compute resources."""

    os: str = Field(description="Operating system, e.g. 'darwin' or 'linux'.")
    arch: str = Field(description="CPU architecture, e.g. 'arm64' or 'x86_64'.")
    cpu_count: int = Field(description="Logical CPU count.")
    ram_total_bytes: int = Field(description="Total system RAM.")
    accelerators: list[AcceleratorInfo] = Field(
        default_factory=list, description="Detected GPUs/NPUs."
    )


class SystemMetrics(BaseModel):
    """A single time-point sample of host resource usage."""

    timestamp: float = Field(default_factory=time.time, description="Unix sample time.")
    cpu_percent: float = Field(default=0.0, description="Overall CPU utilization %.")
    ram_used_bytes: int = Field(default=0, description="System RAM in use.")
    ram_total_bytes: int = Field(default=0, description="Total system RAM.")
    accelerators: list[AcceleratorInfo] = Field(
        default_factory=list, description="Per-accelerator utilization snapshot."
    )


class ModelMetrics(BaseModel):
    """Per-model performance counters surfaced in the dashboard."""

    model_id: str = Field(description="Manifest id.")
    state: ModelState = Field(description="Current lifecycle state.")
    requests: int = Field(default=0, description="Total requests served this run.")
    tokens_per_second: float = Field(default=0.0, description="Recent generation throughput.")
    ttft_ms: float = Field(default=0.0, description="Recent time-to-first-token (ms).")
    resident_bytes: int = Field(default=0, description="Resident memory of the runner process.")
