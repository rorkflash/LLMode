"""SQLite persistence for catalog, events, and metrics history.

Design notes:
  * One file DB at ``settings.db_path``; created/migrated on first use.
  * Model manifests are stored as JSON blobs (the manifest schema evolves more
    often than we want to write migrations for) keyed by id.
  * ``events`` and ``metrics`` are append-only time series; metrics are pruned
    to a rolling window so the DB stays small on SoCs.
  * Live run state is NOT stored here authoritatively — the lifecycle manager
    owns it in memory; we persist runs only for crash-recovery/reaping.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from llmode.schemas import ModelManifest

# Schema definition. Executed with ``executescript`` and idempotent thanks to
# ``IF NOT EXISTS`` so it doubles as the migration for v1.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS models (
    id        TEXT PRIMARY KEY,   -- manifest id
    data      TEXT NOT NULL,      -- full ModelManifest as JSON
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id   TEXT NOT NULL,
    backend    TEXT NOT NULL,
    pid        INTEGER,           -- recorded so orphans can be reaped after a crash
    port       INTEGER,
    started_at REAL NOT NULL,
    stopped_at REAL,              -- NULL while running
    exit_reason TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    kind      TEXT NOT NULL,      -- load | unload | evict | download | crash | error
    model_id  TEXT,
    message   TEXT
);

CREATE TABLE IF NOT EXISTS metrics (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    payload   TEXT NOT NULL       -- SystemMetrics JSON snapshot
);
"""


class Database:
    """Synchronous SQLite access layer.

    SQLite calls are fast and local, so we keep them synchronous and rely on a
    single connection guarded by SQLite's own locking. Methods are intentionally
    small and verb-named.
    """

    def __init__(self, db_path: Path) -> None:
        """Open (creating if needed) the database at ``db_path`` and migrate it."""
        self._path = db_path
        # ``check_same_thread=False`` lets the FastAPI threadpool reuse the conn;
        # writes are short and serialized by SQLite.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        # Return rows as dict-like objects for ergonomic access.
        self._conn.row_factory = sqlite3.Row
        # WAL improves concurrent read/write behaviour for our mixed workload.
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._migrate()

    def _migrate(self) -> None:
        """Apply the schema (idempotent)."""
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying connection (called on daemon shutdown)."""
        self._conn.close()

    # --- Model catalog -----------------------------------------------------
    def upsert_model(self, manifest: ModelManifest) -> None:
        """Insert or replace a model manifest, stamping the update time."""
        self._conn.execute(
            "INSERT INTO models(id, data, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
            (manifest.id, manifest.model_dump_json(), time.time()),
        )
        self._conn.commit()

    def get_model(self, model_id: str) -> ModelManifest | None:
        """Fetch a single manifest by id, or None if unknown."""
        row = self._conn.execute("SELECT data FROM models WHERE id=?", (model_id,)).fetchone()
        return ModelManifest.model_validate_json(row["data"]) if row else None

    def list_models(self) -> list[ModelManifest]:
        """Return every known manifest (catalog + local)."""
        rows = self._conn.execute("SELECT data FROM models ORDER BY id").fetchall()
        return [ModelManifest.model_validate_json(r["data"]) for r in rows]

    def delete_model(self, model_id: str) -> None:
        """Remove a manifest from the catalog (does not touch files on disk)."""
        self._conn.execute("DELETE FROM models WHERE id=?", (model_id,))
        self._conn.commit()

    # --- Runs (for crash recovery / reaping) -------------------------------
    def record_run_start(self, model_id: str, backend: str, pid: int, port: int) -> int:
        """Persist that a backend process was started; returns the run id."""
        cur = self._conn.execute(
            "INSERT INTO runs(model_id, backend, pid, port, started_at) VALUES(?,?,?,?,?)",
            (model_id, backend, pid, port, time.time()),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def record_run_stop(self, run_id: int, reason: str) -> None:
        """Mark a run as finished with the given exit reason."""
        self._conn.execute(
            "UPDATE runs SET stopped_at=?, exit_reason=? WHERE id=?",
            (time.time(), reason, run_id),
        )
        self._conn.commit()

    def list_orphan_runs(self) -> list[sqlite3.Row]:
        """Return runs that were never marked stopped (possible orphan processes).

        Used on startup to reap subprocesses left behind by a daemon crash.
        """
        return self._conn.execute("SELECT * FROM runs WHERE stopped_at IS NULL").fetchall()

    # --- Events ------------------------------------------------------------
    def add_event(self, kind: str, message: str, model_id: str | None = None) -> None:
        """Append a structured audit event (load/unload/evict/download/crash...)."""
        self._conn.execute(
            "INSERT INTO events(timestamp, kind, model_id, message) VALUES(?,?,?,?)",
            (time.time(), kind, model_id, message),
        )
        self._conn.commit()

    def recent_events(self, limit: int = 100) -> list[dict]:
        """Return the most recent events, newest first, as plain dicts."""
        rows = self._conn.execute(
            "SELECT timestamp, kind, model_id, message FROM events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Metrics history ---------------------------------------------------
    def add_metrics(self, payload_json: str) -> None:
        """Append a system-metrics snapshot (already serialized to JSON)."""
        self._conn.execute(
            "INSERT INTO metrics(timestamp, payload) VALUES(?,?)",
            (time.time(), payload_json),
        )
        self._conn.commit()

    def prune_metrics(self, max_age_seconds: float) -> None:
        """Delete metric rows older than the retention window to bound DB size."""
        cutoff = time.time() - max_age_seconds
        self._conn.execute("DELETE FROM metrics WHERE timestamp < ?", (cutoff,))
        self._conn.commit()

    def recent_metrics(self, limit: int = 300) -> list[dict]:
        """Return recent metric snapshots (oldest first) for charting."""
        rows = self._conn.execute(
            "SELECT payload FROM metrics ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        # Reverse so the caller gets chronological order for line charts.
        return [json.loads(r["payload"]) for r in reversed(rows)]
