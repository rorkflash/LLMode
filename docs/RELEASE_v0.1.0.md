# v0.1.0 — Initial Release

LLMode is a single-host control plane for running local LLMs. It orchestrates
existing inference runners as subprocesses and exposes a unified
OpenAI-compatible API, a CLI, and a React web dashboard.

---

## What's included

### Daemon (`llmoded`)

- FastAPI-based headless service exposing:
  - `/api/*` — management API (hardware, catalog, lifecycle, metrics, events)
  - `/v1/*` — OpenAI-compatible inference proxy (chat, completions, embeddings)
  - `/api/events` — live WebSocket metrics stream
- Hardware detection: OS/arch, CPU, RAM, Apple Metal, NVIDIA CUDA
- Automatic backend selection per platform — MLX on Apple Silicon, vLLM on
  Linux+NVIDIA, llama.cpp as the universal GGUF fallback, optional Ollama
  pass-through
- Model lifecycle with states:
  `available → loading → ready → idle → unloading → error`
- Memory budget guard with LRU eviction of idle models before loading new ones
- Idle TTL auto-unload (configurable, default 10 min)
- Lazy-load on first `/v1` inference request
- Model catalog: search Hugging Face Hub, download with integrity check, local
  manifest store (SQLite)
- Live metrics sampling — CPU, RAM, VRAM, per-model resident memory and state
- Orphan process reaping on restart after a crash
- Layered configuration: `.env` file → YAML config → environment variables → defaults

### CLI (`llmode`)

| Command | Description |
|---|---|
| `llmode serve` | Start the daemon (foreground) |
| `llmode doctor` | Diagnose hardware + backends (no daemon required) |
| `llmode status` | Show hardware + backend availability |
| `llmode models` | List models (`--local`, `--running`, `--state`, `--format`) |
| `llmode search <query>` | Search Hugging Face Hub |
| `llmode download <repo>` | Download a model into the local store |
| `llmode load <model>` | Load a model and wait for ready |
| `llmode unload <model>` | Unload a running model |
| `llmode logs <model>` | Print buffered backend logs |
| `llmode metrics` | Print the latest metrics snapshot |
| `llmode ui` | Start the React UI (`--preview`, `--build`) |

### Web UI (`ui/`)

- Standalone React + Vite app — runs independently on demand, connects to the
  daemon via configurable `VITE_LLMODE_API`
- **Dashboard** — live CPU/RAM sparkline charts, backend status, running models
- **Catalog** — search Hugging Face Hub and trigger downloads
- **Models** — load/unload controls, lifecycle state badges, inline log viewer

---

## Hardware support

| Platform | Default backend |
|---|---|
| macOS / Apple Silicon | MLX (`mlx-lm`) |
| Linux x86\_64 + NVIDIA GPU | vLLM or llama.cpp+CUDA |
| Linux x86\_64 (CPU only) | llama.cpp |
| Linux aarch64 (ARM SoC) | llama.cpp (NEON) |

---

## Getting started

```bash
# Install
pip install -e .

# Check hardware and which backends are installed
llmode doctor

# Start the daemon
llmoded

# In a second terminal — start the web UI
llmode ui

# Or use the CLI directly
llmode search "llama gguf"
llmode download mlx-community/Qwen2.5-0.5B-Instruct-4bit
llmode load mlx-community/Qwen2.5-0.5B-Instruct-4bit
llmode models --running

# Point any OpenAI-compatible client at the daemon
curl http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"mlx-community/Qwen2.5-0.5B-Instruct-4bit",
       "messages":[{"role":"user","content":"Hello!"}]}'
```

---

## Known limitations (planned for v0.2)

- Download progress is synchronous — no live progress bar yet
- `tokens/sec` and TTFT metrics are not yet computed from proxy traffic
- Ollama adapter is a pass-through stub; full integration is pending
- WebSocket auth relies on localhost-trusted mode; token enforcement via query
  param is not yet implemented
