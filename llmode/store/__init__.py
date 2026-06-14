"""Persistence package: a thin SQLite wrapper.

We use stdlib ``sqlite3`` (no ORM) to keep the core dependency-light and the
schema obvious. The :class:`~llmode.store.db.Database` class is the only entry
point the rest of the app uses.
"""

from llmode.store.db import Database

__all__ = ["Database"]
