"""Filesystem path resolution following platform conventions.

We centralize *where things live* so the rest of the code never hardcodes
paths. Defaults respect XDG on Linux and ``~/Library`` on macOS, and can be
overridden via settings/env (see settings.py).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Application identifier used in directory names.
APP_NAME = "llmode"


def _xdg_data_home() -> Path:
    """Return the base data directory per platform.

    Order of preference:
      1. ``XDG_DATA_HOME`` if set (Linux/standard).
      2. ``~/Library/Application Support`` on macOS.
      3. ``~/.local/share`` as the POSIX fallback.
    """
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path.home() / ".local" / "share"


def default_data_dir() -> Path:
    """Directory holding the SQLite DB, logs, and runtime state."""
    return _xdg_data_home() / APP_NAME


def default_models_dir() -> Path:
    """Directory where downloaded model weights are stored."""
    return default_data_dir() / "models"


def default_config_file() -> Path:
    """Path to the user's YAML config file."""
    # Config conventionally lives under XDG_CONFIG_HOME / ~/.config on Linux,
    # but for simplicity (homelab) we keep it alongside the data dir.
    return default_data_dir() / "config.yaml"


def default_ui_dir() -> Path | None:
    """Locate the ``ui/`` React app relative to this package installation.

    For an editable install (``pip install -e .``) this file sits at
    ``<repo>/llmode/config/paths.py``, so two ``parent`` calls reach the repo
    root where ``ui/`` lives.  Returns ``None`` when the directory is not found
    (e.g. a wheel install without the UI sources).
    """
    candidate = Path(__file__).resolve().parent.parent.parent / "ui"
    return candidate if candidate.is_dir() else None


def ensure_dirs(*dirs: Path) -> None:
    """Create each given directory (and parents) if it does not yet exist.

    Idempotent — safe to call on every daemon startup.
    """
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
