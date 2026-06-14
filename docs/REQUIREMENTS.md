# LLMode — Requirements

> A single-host control plane to discover, configure, run, and monitor local LLMs
> across heterogeneous hardware (macOS/Apple Silicon, Linux x86+GPU, Linux ARM SoCs)
> by orchestrating existing inference runners as subprocesses.

## 1. Vision & scope

LLMode is a **personal / homelab** tool. It runs as one daemon on a single machine
and exposes both a **management interface** (CLI + Web UI) and an
**OpenAI-compatible inference API**. It does not run inference itself — it
**orchestrates existing runners** (`llama.cpp-server`, `mlx-lm`, `vLLM`, optionally
`Ollama`) and presents a unified surface over them.

**In scope (v1):**
- Single host, single user (optional simple token auth).
- Wrap external inference backends as managed subprocesses.
- Model discovery, download, lifecycle (load / unload), and monitoring.
- CLI control + lightweight Web UI, both driven by the same HTTP API.

**Out of scope (v1), explicitly deferred:**
- Multi-node / fleet orchestration (kept architecturally possible — see ARCHITECTURE §10).
- Fine-tuning / training.
- Multi-tenant auth, quotas, billing.
- Embedding inference libraries in-process (we wrap runners instead).

## 2. Personas & primary use cases

- **Tinkerer (primary):** "Find a model, download it, run it, and hit it from my
  apps with an OpenAI-compatible endpoint — without babysitting RAM."
- **Homelab operator:** "Keep a few models available; auto-unload idle ones so I
  don't OOM; show me what's eating memory and how fast tokens come out."

## 3. Functional requirements

### FR-1 Hardware & platform detection
- FR-1.1 Detect OS/arch: `darwin/arm64`, `linux/x86_64`, `linux/aarch64`.
- FR-1.2 Detect accelerators: Apple Metal, NVIDIA CUDA (`nvidia-smi`), ROCm,
  generic CPU/NEON; report total/available RAM and VRAM.
- FR-1.3 Recommend a **default backend** per detected hardware (see ARCHITECTURE §4).
- FR-1.4 Detect which backend binaries are installed and their versions; surface
  install hints for missing ones.

### FR-2 Backend management
- FR-2.1 Pluggable **backend adapter** interface (start/stop/health/launch-args/capabilities).
- FR-2.2 Ship adapters for: `llama.cpp-server`, `mlx-lm`, `vLLM`, `ollama`.
- FR-2.3 Each loaded model maps to one managed subprocess on a local port; the
  daemon proxies to it.
- FR-2.4 Health-check probing with readiness detection; restart-on-crash policy
  (configurable, default: no auto-restart, mark `error`).
- FR-2.5 Capture and expose backend stdout/stderr logs.

### FR-3 Model catalog & download
- FR-3.1 Browse/search remote catalog (Hugging Face Hub primary; Ollama registry
  optional). Filter by format compatible with available backends (GGUF, MLX, safetensors).
- FR-3.2 Download with progress, resume, integrity check, and pre-flight disk-space check.
- FR-3.3 Local **model store** with a manifest per model (source, format, size,
  quantization, backend compatibility, default launch params).
- FR-3.4 List local models; show on-disk size; delete a model (reclaim disk).
- FR-3.5 Import an already-present local model file/dir.

### FR-4 Model lifecycle (load / unload)
- FR-4.1 Explicit load (`load <model> [--backend] [--params]`) and unload.
- FR-4.2 **Lazy load on first inference request** for a known model (optional, default on).
- FR-4.3 **Idle TTL auto-unload** (configurable per model and global default).
- FR-4.4 **Memory budget guard**: refuse/evict to stay within a configurable
  RAM/VRAM ceiling; LRU eviction of idle models when loading a new one.
- FR-4.5 Clear lifecycle states: `available → loading → ready → idle → unloading → error`.
- FR-4.6 Per-model runtime config (context length, n_gpu_layers, threads, quant,
  sampling defaults) stored and reusable.

### FR-5 Inference API
- FR-5.1 Expose **OpenAI-compatible** `/v1/chat/completions`, `/v1/completions`,
  `/v1/embeddings`, `/v1/models` — streaming (SSE) supported.
- FR-5.2 Route a request to the right backend process by model name; lazy-load if needed.
- FR-5.3 Normalize differences across backends behind the OpenAI schema.
- FR-5.4 Queue / concurrency limits per model; backpressure with clear errors.

### FR-6 Monitoring & observability
- FR-6.1 System metrics: CPU%, RAM used/free, GPU%, VRAM, temperature/power where
  available (SoC), disk usage of model store.
- FR-6.2 Per-model metrics: state, resident memory, requests, tokens/sec, TTFT,
  p50/p95 latency, context utilization, errors.
- FR-6.3 Live stream to UI (WebSocket) + short-term history persisted for charts.
- FR-6.4 Structured event log (loads, unloads, evictions, crashes, downloads).

### FR-7 Control interfaces
- FR-7.1 **CLI** (`llmode ...`) covering every API capability; talks to the daemon
  over HTTP; can also start/stop the daemon.
- FR-7.2 **Web UI**: dashboard (system + model status), catalog/download, model
  detail with live metrics + logs, settings.
- FR-7.3 Single source of truth: UI and CLI are both clients of the same HTTP API.

### FR-8 Configuration & persistence
- FR-8.1 Single YAML config file + env overrides; sane defaults; `llmode config` to view/edit.
- FR-8.2 Persist catalog, model manifests, runtime configs, metrics history, and
  events in local **SQLite**.
- FR-8.3 Configurable paths for model store and data dir; respect XDG / platform conventions.

## 4. Non-functional requirements

- **NFR-1 Cross-platform:** first-class macOS/arm64 and Linux (x86_64 + aarch64).
  No backend assumed present; degrade gracefully.
- **NFR-2 Lightweight:** daemon idle footprint small; monitoring overhead negligible
  on SoCs. Avoid heavy ML deps in the core (they live in the backends).
- **NFR-3 Robustness:** a crashing backend never takes down the daemon; orphaned
  subprocesses are reaped on restart.
- **NFR-4 Responsiveness:** management API p95 < 200 ms (excluding inference/downloads);
  live metrics at ~1 Hz.
- **NFR-5 Simple install:** `uv`/`pipx` install; single command to run the daemon.
  No root required for core operation.
- **NFR-6 Security (homelab baseline):** bind to localhost by default; optional
  bearer token for non-local binds; never expose the management API publicly by default.
- **NFR-7 Observability of itself:** structured logs, `--verbose`, a `doctor`
  command that diagnoses environment/backends.
- **NFR-8 Extensibility:** adding a backend adapter or catalog source requires no
  core changes beyond registering the adapter.

## 5. Acceptance criteria (v1 "done")

1. Fresh install on a Mac (Apple Silicon) and a Linux box detects hardware, finds at
   least one usable backend, and reports status via `llmode status`.
2. From the catalog, user downloads a model with visible progress and a disk check.
3. `llmode run <model>` (or first `/v1/chat/completions` call) lazy-loads the model;
   a streamed completion returns; tokens/sec and TTFT show in the UI.
4. Loading a second model that would exceed the memory budget triggers LRU eviction
   of an idle model (with an event logged), or a clear refusal if none can be evicted.
5. After the configured idle TTL, an unused model auto-unloads and frees memory.
6. Killing a backend process externally is detected; the model shows `error` and the
   daemon stays healthy.
7. The same operations are achievable via CLI and Web UI.

## 6. Open questions

- **OQ-1 Web UI stack:** _Resolved_ → **standalone React + Vite app**, run as a
  separate service on demand; the daemon runs headless and is the source of truth.
  Requires CORS + configurable API base URL (see ARCHITECTURE §1a). Remaining
  sub-choice: React state/query lib (e.g. TanStack Query) and charting lib.
- **OQ-2 Catalog sources:** HF Hub only for v1, or include Ollama registry import?
- **OQ-3 Default memory budget:** percentage of total RAM/VRAM vs. absolute, and
  per-accelerator handling.
- **OQ-4 Auth default:** ship a token even for localhost, or localhost = trusted?
- **OQ-5 vLLM scope:** full support in v1 or "best-effort/experimental" given its
  heavier footprint and GPU-only nature?
