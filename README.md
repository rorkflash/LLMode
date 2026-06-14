# LLMode

A single-host control plane to **discover, configure, run, and monitor local LLMs**
across heterogeneous hardware (macOS/Apple Silicon, Linux x86+GPU, Linux ARM SoCs).

LLMode does not perform inference itself — it **orchestrates existing runners**
(llama.cpp, MLX, vLLM, Ollama) as managed subprocesses and presents one unified
surface: an **OpenAI-compatible API**, a **CLI**, and a **React web dashboard**.

---

## Architecture — one repo, two services

```
llmode/              ← this repo
  llmode/            Python package: daemon + CLI
  ui/                React app: run on demand
  docs/              Requirements, architecture, release notes
```

At runtime the two halves are **independent processes**. The daemon is the
single source of truth; the UI is an optional client you start when you want
a dashboard.

```
ui/ (React + Vite)  ──HTTP / WebSocket──▶  llmoded (FastAPI)
  :3001  on demand                          :8080  always-on
                                            /api/*   management
                                            /v1/*    OpenAI-compatible inference
                                            /api/events  live metrics (WS)
```

---

## Hardware support

| Platform | Default backend |
|---|---|
| macOS / Apple Silicon | MLX (`mlx-lm`) |
| Linux x86\_64 + NVIDIA GPU | vLLM or llama.cpp+CUDA |
| Linux x86\_64 (CPU only) | llama.cpp |
| Linux aarch64 (ARM SoC) | llama.cpp (NEON) |

---

## Quick start

### 1. Install

```bash
git clone <repo>
cd llmode
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure (optional)

```bash
cp .env.example .env          # daemon settings (port, paths, auth, budget…)
cp ui/.env.example ui/.env    # UI settings (PORT, VITE_LLMODE_API…)
```

### 3. Check your environment

```bash
llmode doctor      # detects hardware + which backends are installed
```

### 4. Start the daemon

```bash
llmoded            # starts on http://127.0.0.1:8080 (or LLMODE_PORT from .env)
```

### 5. Use the CLI

```bash
llmode status                                        # hardware + backends
llmode search "qwen gguf"                            # search Hugging Face Hub
llmode download mlx-community/Qwen2.5-0.5B-Instruct-4bit
llmode load mlx-community/Qwen2.5-0.5B-Instruct-4bit
llmode models --running                              # show loaded models
llmode logs mlx-community/Qwen2.5-0.5B-Instruct-4bit
llmode unload mlx-community/Qwen2.5-0.5B-Instruct-4bit
llmode metrics
```

### 6. Run inference

Any OpenAI-compatible client works — just point `base_url` at the daemon:

```bash
curl http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mlx-community/Qwen2.5-0.5B-Instruct-4bit",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

### 7. Open the web UI (optional)

```bash
llmode ui                 # starts Vite dev server → http://localhost:3001
# or
llmode ui --preview       # serves the last production build
llmode ui --build         # builds then serves
```

---

## CLI reference

| Command | Description |
|---|---|
| `llmode serve` | Start the daemon (foreground) |
| `llmode doctor` | Diagnose hardware + backends (no daemon required) |
| `llmode status` | Hardware + backend availability |
| `llmode models` | List models (`--local` `--running` `--state` `--format`) |
| `llmode search <query>` | Search Hugging Face Hub |
| `llmode download <repo>` | Download a model into the local store |
| `llmode load <model>` | Load a model and wait for ready |
| `llmode unload <model>` | Stop a running model and free memory |
| `llmode logs <model>` | Print buffered backend logs |
| `llmode metrics` | Print the latest metrics snapshot |
| `llmode ui` | Launch the React UI (`--preview`, `--build`) |

---

## Configuration

| File | Purpose |
|---|---|
| `.env` | Daemon + CLI overrides (`LLMODE_PORT`, `LLMODE_HOST`, …) |
| `.env.example` | Documented template — copy to `.env` |
| `ui/.env` | UI overrides (`PORT`, `VITE_LLMODE_API`, …) |
| `ui/.env.example` | Documented template — copy to `ui/.env` |

Priority order (highest wins): shell env vars → `.env` file → YAML config → defaults.

The YAML config file lives at:
- macOS: `~/Library/Application Support/llmode/config.yaml`
- Linux: `~/.local/share/llmode/config.yaml`

---

## Requirements

- Python 3.12+
- Node 18+ (for the UI)
- At least one backend runner for inference:
  - **llama.cpp** — `brew install llama.cpp` (macOS) or build from source
  - **mlx-lm** — `pip install mlx-lm` (Apple Silicon only)
  - **vLLM** — `pip install vllm` (Linux + NVIDIA GPU)
  - **Ollama** — [ollama.com](https://ollama.com) (optional pass-through)

---

## Documentation

- [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) — full feature requirements
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system design and module layout
- [docs/RELEASE_v0.1.0.md](docs/RELEASE_v0.1.0.md) — v0.1.0 release notes
