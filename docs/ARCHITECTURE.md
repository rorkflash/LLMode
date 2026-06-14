# LLMode — Architecture

Companion to [REQUIREMENTS.md](REQUIREMENTS.md). Describes the v1 single-host design.

## 1. Decisions (locked)

| Decision            | Choice                                              |
|---------------------|-----------------------------------------------------|
| Inference strategy  | **Wrap existing runners** as subprocesses           |
| Deployment scope    | **Single host** (fleet-ready data model, not built) |
| Language / runtime  | **Python 3.12+**                                    |
| Audience            | **Personal / homelab**                              |
| API style           | **OpenAI-compatible** `/v1` + management API         |
| UI topology         | **Separate React service** (run on demand; daemon runs headless) |

### 1a. UI topology — two independent services

The Web UI is a **standalone React (Vite) app**, not bundled into the daemon. The
daemon (`llmoded`) runs **headless** as the source of truth; the UI is a pure client
launched only when wanted. Consequences (handled by design):

- **CORS:** daemon exposes a configurable `allowed_origins` (default
  `http://localhost:5173`).
- **Configurable API base URL:** the UI reads `VITE_LLMODE_API` to locate the daemon
  (they are not same-origin).
- **Auth across origins:** when the bearer token is enabled (OQ-4), the UI stores and
  sends it; localhost-trusted stays the default.
- **Optional one-process mode (future):** the daemon may *also* serve a prebuilt
  static bundle for a "just give me everything" install — secondary, not primary.

## 2. High-level diagram

```
        ┌──────────────────────┐     ┌──────────────┐
        │  llmode-ui (React)   │     │     CLI      │
        │  Vite • :5173        │     │   (Typer)    │
        │  separate service    │     └──────┬───────┘
        └──────────┬───────────┘            │
                   │ HTTP / WS (CORS)        │ HTTP
                   └───────────┬─────────────┘
                                   ▼
        ┌──────────────────────────────────────────────────────┐
        │                  LLMode Daemon (FastAPI)               │
        │                                                        │
        │  Mgmt API   OpenAI Proxy   WebSocket events            │
        │  ┌────────┐ ┌───────────┐ ┌──────────────┐            │
        │  │Catalog │ │  Router   │ │   Metrics    │            │
        │  │/Download│ │ (model→  │ │  collector   │            │
        │  └────────┘ │  process)│ └──────────────┘            │
        │  ┌─────────────────────┐  ┌──────────────┐            │
        │  │  Lifecycle manager  │  │ Hardware probe│            │
        │  │ (load/unload/evict) │  └──────────────┘            │
        │  └─────────┬───────────┘                              │
        │            │ Backend Adapter interface                │
        └────────────┼──────────────────────────────────────────┘
                     ▼
   ┌───────────┬───────────┬───────────┬───────────┐
   │ llama.cpp │  mlx-lm   │   vLLM    │  ollama    │  ← managed subprocesses
   │  server   │ (macOS)   │ (NV GPU)  │ (optional) │     each on a local port
   └───────────┴───────────┴───────────┴───────────┘
                     │
              ┌──────────────┐   ┌──────────────┐
              │ Model store  │   │   SQLite     │
              │  (on disk)   │   │ (state/hist) │
              └──────────────┘   └──────────────┘
```

## 3. Components

- **Daemon (FastAPI + uvicorn):** async HTTP server hosting the management API,
  the OpenAI-compatible proxy, and a WebSocket events channel. Single process;
  the source of truth for all state.
- **Hardware probe:** detects OS/arch/accelerators and capacities; runs at startup
  and on demand. Backends for probing: `psutil` (CPU/RAM/disk), `nvidia-smi`/NVML
  (CUDA), `powermetrics`/`ioreg`/`Metal` heuristics (macOS), `/sys` and vendor tools
  (SoC temp/power).
- **Catalog & downloader:** searches Hugging Face Hub (`huggingface_hub`), filters by
  backend-compatible formats, downloads with progress/resume/checksum, writes a
  per-model manifest into the model store.
- **Lifecycle manager:** owns the state machine
  (`available→loading→ready→idle→unloading→error`), enforces the memory budget,
  performs LRU eviction and idle-TTL unload, and supervises backend processes
  (start, health-check, reap, crash detection).
- **Backend adapters:** one per runner, behind a common interface (§4). Translate a
  model + runtime config into a launch command and know each runner's health probe
  and API quirks.
- **Router / proxy:** maps an inbound `/v1` request to the backend process for the
  requested model (triggering lazy-load), then streams the response back. Normalizes
  request/response to the OpenAI schema.
- **Metrics collector:** samples system + per-model metrics on a timer, pushes live
  updates over WebSocket, and persists rolling history to SQLite.
- **CLI (Typer):** thin client over the HTTP API; can also bootstrap/stop the daemon
  and run `doctor`.
- **Web UI:** static SPA served by the daemon; consumes the same API + WebSocket.

## 4. Backend adapter interface

```python
class BackendAdapter(Protocol):
    name: str                       # "llama.cpp", "mlx", "vllm", "ollama"

    def is_available(self) -> BackendInfo:        # installed? version? path?
        ...
    def supports(self, model: ModelManifest) -> bool:  # format/arch/accel match
        ...
    def launch_command(self, model: ModelManifest,
                       cfg: RuntimeConfig, port: int) -> list[str]:
        ...
    async def health(self, base_url: str) -> Health:   # readiness probe
        ...
    def estimate_memory(self, model: ModelManifest,
                       cfg: RuntimeConfig) -> MemoryEstimate:
        ...
    # API mapping: most runners already expose OpenAI-compatible endpoints;
    # adapter declares base path + any translation hooks.
    api: OpenAICompat | TranslatedAPI
```

**Default backend selection (FR-1.3):**

| Platform               | Default        | Notes                                  |
|------------------------|----------------|----------------------------------------|
| macOS / Apple Silicon  | `mlx-lm`       | fastest on Metal; fallback llama.cpp+Metal |
| Linux x86_64 + NVIDIA  | `vLLM` or llama.cpp+CUDA | vLLM for throughput; llama.cpp for GGUF |
| Linux x86_64 (CPU)     | `llama.cpp`    | GGUF, AVX                              |
| Linux aarch64 (SoC)    | `llama.cpp`    | NEON/CPU; CUDA on Jetson if present    |

llama.cpp-server is the **universal fallback** — if it's installed and the model is
GGUF, it works everywhere.

## 5. Lifecycle state machine

```
 available ──load──▶ loading ──ready──▶ ready ──(serving)
     ▲                  │                  │  │
     │                  └──fail──▶ error   │  └──idle TTL──▶ idle
     │                                     │                  │
     └────────────── unloading ◀──unload/evict──────────────┘
```

- **Lazy load:** first `/v1` request for a known-but-unloaded model triggers `load`.
- **Memory budget:** before `loading`, `estimate_memory` is checked against the
  configured ceiling and live free memory. If insufficient → evict LRU `idle`
  model(s); if still insufficient → `error` with a clear message (no eviction of
  actively-serving models).
- **Idle TTL:** a `ready` model with no requests for `idle_ttl` → `idle`, then
  unloaded (TTL split lets the UI show "idle, will unload at T").
- **Crash:** health probe failure → `error`; process reaped; event logged; optional
  restart policy.

## 6. Data model (SQLite)

- `models` — catalog + local manifests (id, source, format, quant, size, sha,
  backend compatibility, default runtime config).
- `runtime_configs` — saved per-model launch params.
- `runs` — load sessions (model, backend, pid, port, started/stopped, exit reason).
- `metrics` — time-series samples (system + per-run), rolled up / TTL'd.
- `events` — structured audit log (load, unload, evict, download, crash, error).
- `settings` — effective config snapshot.

## 7. API surface (sketch)

**Management**
```
GET    /api/system            → hardware, accelerators, capacities, backends
GET    /api/models            → catalog (remote) + local + loaded, with state
POST   /api/models/search     → query remote catalog
POST   /api/models/{id}/download   (SSE progress)
DELETE /api/models/{id}            (remove local)
POST   /api/models/{id}/load   {backend?, config?}
POST   /api/models/{id}/unload
GET    /api/models/{id}/logs   (tail / stream)
GET    /api/metrics           → latest snapshot
WS     /api/events            → live metrics + lifecycle events
GET    /api/config / PUT /api/config
```

**Inference (OpenAI-compatible)**
```
GET    /v1/models
POST   /v1/chat/completions   (stream: SSE)
POST   /v1/completions
POST   /v1/embeddings
```

## 8. Process & port management

- Each loaded model = one child process bound to `127.0.0.1:<ephemeral>`.
- Daemon allocates ports, tracks `pid`/`port` in `runs`, and on startup reaps any
  orphaned children recorded from a previous run.
- Subprocess stdout/stderr streamed to ring buffers (for `logs`) and rotated files.
- Graceful stop (SIGTERM → timeout → SIGKILL) on unload/eviction/shutdown.

## 9. Proposed tech stack

| Concern        | Choice                                             |
|----------------|----------------------------------------------------|
| Daemon         | FastAPI + uvicorn (async)                          |
| CLI            | Typer + httpx                                      |
| Config/models  | Pydantic v2 / pydantic-settings, YAML             |
| Storage        | SQLite (stdlib `sqlite3` or SQLModel)              |
| System metrics | psutil + platform probes (nvidia-smi, powermetrics)|
| Catalog/download | huggingface_hub                                  |
| Web UI         | **React + Vite, separate service** (lives in `ui/` inside the repo, CORS) |
| Packaging      | `uv` / `pipx` for daemon+CLI; `npm` in `ui/`       |
| Process supervision | stdlib `asyncio` subprocess + psutil          |

## 10. Fleet-readiness (deferred, not built)

Kept cheap to add later: the management API is node-scoped, the data model can carry
a `node_id`, and the router abstracts "where a model runs." A future coordinator
could aggregate multiple daemons behind one UI and route inference across nodes —
**no v1 work, only avoid decisions that preclude it.**

## 11. Module layout

One repo — Python daemon+CLI and the React UI co-located. Runtime is still two
independent processes; co-location just keeps history and versioning together.

```
llmode/                 ← repo root
  llmode/               # Python package: daemon + CLI
    daemon/             # FastAPI app, routers (mgmt, openai, ws), CORS
    backends/           # adapters: base.py, llamacpp.py, mlx.py, vllm.py, ollama.py
    lifecycle/          # state machine, memory budget, supervisor
    catalog/            # hf source, search, download, manifest
    hardware/           # probes (cpu, mem, cuda, metal, soc)
    metrics/            # collector, store, ws publisher
    store/              # sqlite models + migrations, model store fs layout
    config/             # settings, paths
    cli/                # Typer app
  ui/                   # React + Vite: standalone client, run on demand
    src/
      api/              # typed client for /api + /v1 + WS (VITE_LLMODE_API)
    pages/              # dashboard, catalog, model-detail, settings
    components/         # charts, log viewer, status widgets
  package.json
```
