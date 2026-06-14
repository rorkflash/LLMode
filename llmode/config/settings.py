"""Layered application settings.

Settings are resolved from (lowest to highest priority):
    1. Field defaults defined below.
    2. The YAML config file (if present).
    3. Environment variables prefixed ``LLMODE_`` (e.g. ``LLMODE_PORT=9000``).

A single cached :func:`get_settings` instance is shared process-wide.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from llmode.config import paths


class Settings(BaseSettings):
    """All tunable knobs for the daemon, grouped by concern."""

    # Pydantic-settings behaviour: read ``LLMODE_*`` env vars, ignore unknowns.
    model_config = SettingsConfigDict(env_prefix="LLMODE_", extra="ignore")

    # --- Network / API -----------------------------------------------------
    host: str = Field(default="127.0.0.1", description="Daemon bind address (localhost by default).")
    port: int = Field(default=8080, description="Daemon HTTP port.")
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173"],
        description="CORS origins allowed to call the API (the React UI dev server).",
    )
    auth_token: str | None = Field(
        default=None,
        description="Optional bearer token. None = localhost-trusted (no auth).",
    )

    # --- Storage paths -----------------------------------------------------
    data_dir: Path = Field(default_factory=paths.default_data_dir, description="State + DB dir.")
    models_dir: Path = Field(default_factory=paths.default_models_dir, description="Weights dir.")

    # --- Memory budget (auto load/unload guard) ----------------------------
    ram_budget_fraction: float = Field(
        default=0.8, description="Max fraction of total RAM LLMode may commit to models."
    )
    vram_budget_fraction: float = Field(
        default=0.9, description="Max fraction of total VRAM LLMode may commit to models."
    )

    # --- Lifecycle ---------------------------------------------------------
    lazy_load: bool = Field(
        default=True, description="Load a model automatically on its first inference request."
    )
    idle_ttl_seconds: int = Field(
        default=600, description="Unload a model after this many seconds with no requests."
    )

    # --- Monitoring --------------------------------------------------------
    metrics_interval_seconds: float = Field(
        default=2.0, description="How often to sample system/model metrics."
    )

    # --- UI ----------------------------------------------------------------
    ui_dir: Path | None = Field(
        default_factory=paths.default_ui_dir,
        description=(
            "Path to the ui/ React app directory. "
            "Auto-detected from the package location; override with LLMODE_UI_DIR."
        ),
    )

    # --- Logging -----------------------------------------------------------
    log_level: str = Field(default="INFO", description="Root log level.")

    @property
    def db_path(self) -> Path:
        """Absolute path to the SQLite database file."""
        return self.data_dir / "llmode.db"


def _load_yaml(config_file: Path) -> dict:
    """Read a YAML config file into a plain dict, tolerating absence.

    Returns an empty dict if the file does not exist or is empty so callers can
    always splat the result into ``Settings(**data)``.
    """
    if not config_file.exists():
        return {}
    with config_file.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build (once) and return the process-wide settings singleton.

    Priority order (highest wins):
      1. Real environment variables (``LLMODE_*`` in the shell).
      2. ``.env`` file at the repo root (loaded by pydantic-settings).
      3. YAML config file values.
      4. Field defaults defined in :class:`Settings`.

    The ``.env`` path is resolved to an absolute path so it is found
    regardless of the working directory the process was launched from.
    """
    yaml_data = _load_yaml(paths.default_config_file())
    env_file = paths.default_env_file()
    # _env_file is a pydantic-settings v2 constructor override: it tells the
    # settings loader which .env file to read, taking precedence over any
    # env_file set in model_config and resolving to an absolute path.
    settings = Settings(_env_file=env_file, **yaml_data)
    # Make sure the directories we depend on exist before anyone uses them.
    paths.ensure_dirs(settings.data_dir, settings.models_dir)
    return settings
