# LLMode

A single-host control plane to **discover, configure, run, and monitor local LLMs**
across heterogeneous hardware (macOS/Apple Silicon, Linux x86+GPU, Linux ARM SoCs).
LLMode does not perform inference itself — it **orchestrates existing runners**
(llama.cpp, MLX, vLLM, Ollama) as subprocesses and presents one unified surface:
an OpenAI-compatible API, a CLI, and a Web UI.

See [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design.

## Topology — one repo, two services

```
llmode/          ← this repo
  llmode/        Python package (daemon + CLI)
  ui/            React app (run on demand)
```

At runtime they are still **two independent processes** — a single clone just
keeps daemon and UI versions in sync.

```
ui/ (React + Vite, :5173)  ──HTTP/WS──▶  llmoded (FastAPI, :8080)
  run on demand                            headless source of truth
                                           /api/*  /v1/*  /api/events
```

The daemon runs headless; the UI is a separate client you launch when you want a
dashboard. The CLI and any OpenAI-compatible client also talk to the daemon.

## Backend (Python daemon + CLI)

```bash
# Install (editable) into a virtualenv.
pip install -e ".[dev]"

# Diagnose hardware + which backend runners are installed (no daemon needed).
llmode doctor

# Run the daemon.
llmoded                      # serves http://127.0.0.1:8080

# In another shell — drive it via the CLI:
llmode status               # hardware + backends
llmode search "llama gguf"  # search Hugging Face
llmode download <repo_id>   # download into the local model store
llmode load <model_id>      # load + wait for ready
llmode models               # list models with live state
llmode unload <model_id>
```

Inference is OpenAI-compatible — point any client at the daemon:

```bash
curl http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"<model_id>","messages":[{"role":"user","content":"hi"}]}'
```

## Web UI (React)

```bash
cd ui
npm install
npm run dev                  # http://localhost:5173 (proxies /api + /v1 to the daemon)
```

For a separate-origin deployment, set `VITE_LLMODE_API` (and `VITE_LLMODE_TOKEN`
if auth is enabled) instead of relying on the dev proxy.

## Requirements

- Python 3.12+
- Node 18+ (for the UI)
- At least one backend runner installed for actual inference:
  `llama.cpp` (universal/GGUF), `mlx-lm` (Apple Silicon), `vllm` (Linux+NVIDIA),
  or `ollama`.
