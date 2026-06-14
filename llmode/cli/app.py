"""``llmode`` CLI — a Typer app that drives the daemon over HTTP.

Design: every command (except ``serve`` and ``doctor``) is a small wrapper that
calls a management endpoint and pretty-prints the result. This keeps the CLI and
the Web UI behaviourally identical — both are just API clients.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import typer

from llmode.config import get_settings

# The Typer application object; ``main`` invokes this.
cli = typer.Typer(help="LLMode — manage local LLMs from the command line.")


def _base_url() -> str:
    """Compute the daemon's base URL from settings (host/port)."""
    s = get_settings()
    # Use localhost explicitly so a 0.0.0.0 bind still resolves for the client.
    host = "127.0.0.1" if s.host in ("0.0.0.0", "") else s.host
    return f"http://{host}:{s.port}"


def _headers() -> dict:
    """Build auth headers when a token is configured."""
    token = get_settings().auth_token
    return {"Authorization": f"Bearer {token}"} if token else {}


def _client() -> httpx.Client:
    """Create an HTTP client pointed at the daemon with auth + sane timeout."""
    return httpx.Client(base_url=_base_url(), headers=_headers(), timeout=300.0)


def _print(obj) -> None:
    """Pretty-print a JSON-serializable object to stdout."""
    typer.echo(json.dumps(obj, indent=2))


@cli.command()
def serve() -> None:
    """Start the LLMode daemon (foreground)."""
    # Imported lazily so the CLI stays fast for non-serve commands.
    from llmode.daemon.app import main as run_daemon

    run_daemon()


@cli.command()
def doctor() -> None:
    """Diagnose the local environment: hardware + backend availability.

    Runs probes in-process (no daemon required) so it works even before the
    daemon is started.
    """
    from llmode.backends import all_adapters
    from llmode.hardware import detect_hardware

    _print(
        {
            "hardware": detect_hardware().model_dump(),
            "backends": [a.probe().model_dump() for a in all_adapters()],
        }
    )


@cli.command()
def status() -> None:
    """Show host hardware and installed backends (via the running daemon)."""
    with _client() as c:
        resp = c.get("/api/system")
        _print(resp.json())


@cli.command()
def models() -> None:
    """List known models and their current state."""
    with _client() as c:
        resp = c.get("/api/models")
        _print(resp.json())


@cli.command()
def search(query: str, limit: int = 20) -> None:
    """Search the remote catalog (Hugging Face Hub)."""
    with _client() as c:
        resp = c.post("/api/models/search", json={"query": query, "limit": limit})
        _print(resp.json())


@cli.command()
def download(
    repo_id: str,
    file: str = typer.Option(None, help="Specific filename to download (e.g. a GGUF)."),
) -> None:
    """Download a model into the local store."""
    with _client() as c:
        resp = c.post("/api/models/download", json={"repo_id": repo_id, "filename": file})
        _print(resp.json())


@cli.command()
def load(
    model_id: str,
    backend: str = typer.Option(None, help="Force a specific backend."),
) -> None:
    """Load a model and wait for it to become ready."""
    with _client() as c:
        resp = c.post(f"/api/models/{model_id}/load", json={"backend": backend})
        _print(resp.json())


@cli.command()
def unload(model_id: str) -> None:
    """Unload a running model and free its memory."""
    with _client() as c:
        resp = c.post(f"/api/models/{model_id}/unload")
        _print(resp.json())


@cli.command()
def logs(model_id: str) -> None:
    """Print the buffered backend logs for a running model."""
    with _client() as c:
        resp = c.get(f"/api/models/{model_id}/logs")
        for line in resp.json().get("logs", []):
            typer.echo(line)


@cli.command()
def metrics() -> None:
    """Print the latest metrics snapshot."""
    with _client() as c:
        resp = c.get("/api/metrics")
        _print(resp.json())


@cli.command()
def ui(
    preview: bool = typer.Option(
        False, "--preview", help="Serve the pre-built bundle (npm run preview) instead of the dev server."
    ),
    build: bool = typer.Option(
        False, "--build", help="Run `npm run build` before starting the preview server."
    ),
) -> None:
    """Start the React UI (dev server by default).

    Looks for the ``ui/`` directory next to the installed package. Override the
    location with the ``LLMODE_UI_DIR`` env var or the ``ui_dir`` config key.

    Modes:
      llmode ui             — Vite dev server with hot-reload (default, :5173).
      llmode ui --preview   — Serve the last production build (:4173).
      llmode ui --build     — Build first, then serve the production bundle.
    """
    # Resolve the UI directory from settings (auto-detected or user-configured).
    ui_path: Path | None = get_settings().ui_dir
    if ui_path is None:
        typer.echo(
            "Could not locate the ui/ directory.\n"
            "Set LLMODE_UI_DIR to its absolute path, or run from the repo root.",
            err=True,
        )
        raise typer.Exit(code=1)

    # Make sure npm is available before we try anything.
    npm = shutil.which("npm")
    if npm is None:
        typer.echo("npm not found. Install Node.js from https://nodejs.org.", err=True)
        raise typer.Exit(code=1)

    # Install node_modules on first run if they are absent.
    if not (ui_path / "node_modules").exists():
        typer.echo("node_modules not found — running npm install …")
        result = subprocess.run([npm, "install"], cwd=ui_path)
        if result.returncode != 0:
            raise typer.Exit(code=result.returncode)

    # Determine which npm script to run.
    if build:
        # Build the production bundle, then fall through to preview.
        typer.echo("Building production bundle …")
        result = subprocess.run([npm, "run", "build"], cwd=ui_path)
        if result.returncode != 0:
            raise typer.Exit(code=result.returncode)
        script = "preview"
    elif preview:
        script = "preview"
    else:
        script = "dev"

    typer.echo(f"Starting UI ({script}) in {ui_path} …")
    # subprocess.run with cwd correctly runs npm inside ui/ on all platforms.
    # Ctrl-C sends SIGINT to the whole process group, so npm exits cleanly too.
    result = subprocess.run([npm, "run", script], cwd=ui_path)
    raise typer.Exit(code=result.returncode)


def main() -> None:
    """Console entry point for the ``llmode`` script."""
    cli()


if __name__ == "__main__":
    main()
