"""SQLite connection owner + unit of work for portable configuration.

Store owns the connection and schema; per-aggregate repositories
(repositories/) provide persistence operations and are the only
supported data path. write_txn() is the unit-of-work context manager
used for atomic check-and-mutate (If-Match + write + revision bump).
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .repositories import (
    SqliteMetaRepository,
    SqlitePersonaRepository,
    SqliteProfileRepository,
    SqliteSettingsRepository,
    new_revision,
)


class _LockedConnection:
    """Serializes statement execution across threads.

    A single sqlite3 connection is not safe for concurrent use even with
    check_same_thread=False. write_txn() holds the same re-entrant lock
    for its whole transaction so statements issued inside it pass
    through while other threads wait.
    """

    def __init__(self, conn: sqlite3.Connection, lock: threading.RLock) -> None:
        self._conn = conn
        self._lock = lock

    def execute(self, *args, **kwargs):
        with self._lock:
            return self._conn.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        with self._lock:
            return self._conn.executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        with self._lock:
            return self._conn.executescript(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._conn, name)


class Store:
    """Persistent portable configuration: setting overrides, profiles,
    personas, managed snapshot and the logical config revision."""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        if data_dir is None:
            raw = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
            self.data_dir = None
            self.db_path = None
        else:
            self.data_dir = Path(data_dir)
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = self.data_dir / "opal-look-yolo.db"
            raw = sqlite3.connect(
                self.db_path, check_same_thread=False, isolation_level=None
            )
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.RLock()
        self._txn_state = threading.local()
        self._conn = _LockedConnection(raw, self._lock)
        self._init_schema()

        self.meta = SqliteMetaRepository(self._conn)
        self.settings = SqliteSettingsRepository(self._conn)
        self.profiles = SqliteProfileRepository(self._conn)
        self.personas = SqlitePersonaRepository(self._conn)

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS setting_overrides (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS profiles (
                profile_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                active INTEGER NOT NULL DEFAULT 0,
                shared TEXT NOT NULL DEFAULT '{}',
                modules TEXT NOT NULL DEFAULT '{}',
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS personas (
                persona_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                voice_id TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                origin TEXT NOT NULL DEFAULT 'local',
                created_at TEXT,
                updated_at TEXT
            );
            """
        )
        if self._conn.execute(
            "SELECT value FROM meta WHERE key = 'config_revision'"
        ).fetchone() is None:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES ('config_revision', ?)",
                (new_revision(),),
            )

    def ping(self) -> bool:
        try:
            self._conn.execute("SELECT 1")
        except sqlite3.Error:
            return False
        return True

    @contextmanager
    def write_txn(self) -> Iterator[Store]:
        """Exclusive write transaction for atomic check-and-mutate.

        Nestable: an inner write_txn on the same thread becomes a
        SAVEPOINT; an inner failure rolls back only to its savepoint, an
        outer failure rolls back everything.
        """
        with self._lock:
            depth = getattr(self._txn_state, "depth", 0)
            if depth == 0:
                self._txn_state.depth = 1
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    yield self
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
                else:
                    self._conn.execute("COMMIT")
                finally:
                    self._txn_state.depth = 0
            else:
                savepoint = f"opal_sp_{depth}"
                self._txn_state.depth = depth + 1
                self._conn.execute(f"SAVEPOINT {savepoint}")
                try:
                    yield self
                except BaseException:
                    self._conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                    raise
                else:
                    self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                finally:
                    self._txn_state.depth = depth

    def config_revision(self) -> str:
        return self.meta.revision()

    def bump_revision(self) -> str:
        """Advance the global configuration revision. Call inside write_txn."""
        return self.meta.bump_revision()

    def close(self) -> None:
        self._conn.close()
