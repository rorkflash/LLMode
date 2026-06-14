"""LLMode — a single-host control plane for local LLMs.

This package contains the headless daemon (``llmode.daemon``) and the CLI
(``llmode.cli``). It *orchestrates* external inference runners (llama.cpp, MLX,
vLLM, Ollama) as subprocesses rather than performing inference itself.

Sub-packages:
    config    — settings + filesystem paths.
    schemas   — shared Pydantic domain models used across every layer.
    store     — SQLite persistence (catalog, runs, events, metrics).
    hardware  — host/accelerator detection probes.
    backends  — per-runner adapters behind a common interface.
    catalog   — remote model discovery + downloads (Hugging Face Hub).
    lifecycle — load/unload state machine, memory budget, process supervisor.
    metrics   — periodic system + per-model sampling.
    daemon    — FastAPI application wiring everything together.
    cli       — Typer command-line client of the daemon's HTTP API.
"""

# Single source of truth for the package version (kept in sync with pyproject).
__version__ = "0.1.0"
