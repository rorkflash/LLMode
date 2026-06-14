"""``llmode`` CLI — a Typer app that drives the daemon over HTTP.

Design: every command (except ``serve``, ``doctor``, and ``ui``) is a small
wrapper that calls a management endpoint and pretty-prints the result. This keeps
the CLI and the Web UI behaviourally identical — both are just API clients.

All daemon-calling commands route through :func:`_daemon_call` so connection
errors always produce a clean, actionable message instead of a raw traceback.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

import httpx
import typer

from llmode.config import get_settings

# The Typer application object; ``main`` invokes this.
cli = typer.Typer(help="LLMode — manage local LLMs from the command line.")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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


@contextmanager
def _daemon_call():
    """Context manager that converts httpx errors into clean CLI messages.

    Wraps every block of code that talks to the daemon so that:
      * Connection refused  → tells the user to run ``llmode serve``.
      * HTTP error response → shows the status code and detail from the daemon.
      * Any other request error → shows a short message without a traceback.
    """
    try:
        yield
    except httpx.ConnectError:
        url = _base_url()
        typer.echo(
            f"Cannot connect to the LLMode daemon at {url}.\n"
            "Start it first with:  llmode serve",
            err=True,
        )
        raise typer.Exit(code=1)
    except httpx.HTTPStatusError as exc:
        # The daemon replied with a 4xx/5xx — surface its error detail.
        try:
            detail = exc.response.json().get("detail", exc.response.text)
        except Exception:
            detail = exc.response.text
        typer.echo(f"Daemon error {exc.response.status_code}: {detail}", err=True)
        raise typer.Exit(code=1)
    except httpx.RequestError as exc:
        typer.echo(f"Request failed: {exc}", err=True)
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Commands that do NOT need the daemon
# ---------------------------------------------------------------------------

@cli.command()
def serve() -> None:
    """Start the LLMode daemon (foreground)."""
    # Imported lazily so the CLI stays fast for non-serve commands.
    from llmode.daemon.app import main as run_daemon
    run_daemon()


@cli.command()
def doctor() -> None:
    """Diagnose the local environment: hardware + backend availability.

    Runs probes in-process (no daemon required) so it works even before
    the daemon is started.
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
def ui(
    preview: bool = typer.Option(
        False, "--preview", help="Serve the pre-built bundle (npm run preview) instead of the dev server."
    ),
    build: bool = typer.Option(
        False, "--build", help="Run `npm run build` before starting the preview server."
    ),
) -> None:
    """Start the React UI (dev server by default).

    Looks for the ``ui/`` directory next to the installed package. Override
    the location with the ``LLMODE_UI_DIR`` env var or the ``ui_dir`` config key.

    Modes:

      llmode ui             — Vite dev server with hot-reload (default, :5173).
      llmode ui --preview   — Serve the last production build (:4173).
      llmode ui --build     — Build first, then serve the production bundle.
    """
    ui_path: Path | None = get_settings().ui_dir
    if ui_path is None:
        typer.echo(
            "Could not locate the ui/ directory.\n"
            "Set LLMODE_UI_DIR to its absolute path, or run from the repo root.",
            err=True,
        )
        raise typer.Exit(code=1)

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

    if build:
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
    # Ctrl-C sends SIGINT to the whole process group so npm exits cleanly too.
    result = subprocess.run([npm, "run", script], cwd=ui_path)
    raise typer.Exit(code=result.returncode)


# ---------------------------------------------------------------------------
# Commands that require the daemon
# ---------------------------------------------------------------------------

@cli.command()
def status() -> None:
    """Show host hardware and installed backends (via the running daemon)."""
    with _daemon_call():
        with _client() as c:
            _print(c.get("/api/system").json())


@cli.command()
def models(
    local: bool = typer.Option(False, "--local", help="Only show models downloaded to disk."),
    running: bool = typer.Option(False, "--running", help="Only show currently loaded models (ready/idle/loading)."),
    state: str = typer.Option(None, "--state", help="Filter by lifecycle state: available | loading | ready | idle | unloading | error."),
    format: str = typer.Option(None, "--format", help="Filter by weight format: gguf | mlx | safetensors."),
) -> None:
    """List known models and their current state.

    Examples:

      llmode models                   # everything in the catalog
      llmode models --local           # only downloaded models
      llmode models --running         # only models currently loaded
      llmode models --state ready     # only models in the ready state
      llmode models --format gguf     # only GGUF models
    """
    with _daemon_call():
        with _client() as c:
            items = c.get("/api/models").json()

    # Apply filters in order; each narrows the previous result.
    if local:
        items = [m for m in items if m.get("path")]
    if running:
        items = [m for m in items if m.get("run") and m["run"]["state"] in ("ready", "idle", "loading")]
    if state:
        items = [
            m for m in items
            if (m.get("run") and m["run"]["state"] == state)
            or (not m.get("run") and state == "available")
        ]
    if format:
        items = [m for m in items if m.get("format", "").lower() == format.lower()]

    if not items:
        typer.echo("No models match the given filters.")
        return

    _print(items)


@cli.command()
def search(query: str, limit: int = 20) -> None:
    """Search the remote catalog (Hugging Face Hub)."""
    with _daemon_call():
        with _client() as c:
            _print(c.post("/api/models/search", json={"query": query, "limit": limit}).json())


@cli.command()
def download(
    repo_id: str,
    file: str = typer.Option(None, help="Specific filename to download (e.g. a GGUF quant)."),
) -> None:
    """Download a model into the local store."""
    with _daemon_call():
        with _client() as c:
            _print(c.post("/api/models/download", json={"repo_id": repo_id, "filename": file}).json())


@cli.command()
def load(
    model_id: str,
    backend: str = typer.Option(None, help="Force a specific backend."),
) -> None:
    """Load a model and wait for it to become ready."""
    with _daemon_call():
        with _client() as c:
            _print(c.post(f"/api/models/{model_id}/load", json={"backend": backend}).json())


@cli.command()
def unload(model_id: str) -> None:
    """Unload a running model and free its memory."""
    with _daemon_call():
        with _client() as c:
            _print(c.post(f"/api/models/{model_id}/unload").json())


@cli.command()
def logs(model_id: str) -> None:
    """Print the buffered backend logs for a running model."""
    with _daemon_call():
        with _client() as c:
            for line in c.get(f"/api/models/{model_id}/logs").json().get("logs", []):
                typer.echo(line)


@cli.command()
def metrics() -> None:
    """Print the latest system + model metrics snapshot."""
    with _daemon_call():
        with _client() as c:
            _print(c.get("/api/metrics").json())


def main() -> None:
    """Console entry point for the ``llmode`` script."""
    cli()


if __name__ == "__main__":
    main()
