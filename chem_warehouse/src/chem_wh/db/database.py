"""SQLite connection helpers.

WAL plus synchronous=FULL keeps committed inventory durable across power loss.
Migrations of an existing file copy it aside before any ALTER.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

from chem_wh.db.schema import CURRENT_SCHEMA_VERSION, MIGRATIONS, SCHEMA_SQL
from chem_wh.utils.timeutil import now_iso


def get_default_db_path(*, demo: bool = False) -> Path:
    base = Path.home() / ".chem_warehouse"
    if demo:
        base = base / "demo"
    base.mkdir(parents=True, exist_ok=True)
    name = "chem_warehouse_demo.db" if demo else "chem_warehouse.db"
    return base / name


def remove_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():
            sidecar.unlink()


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists() and self.path.stat().st_size > 0
        self._conn = sqlite3.connect(
            str(self.path), timeout=5.0, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._configure()
        self._init_schema(existed)

    def _configure(self) -> None:
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = FULL")
        self._conn.execute("PRAGMA busy_timeout = 5000")

    def _init_schema(self, existed: bool) -> None:
        version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        has_chem = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chemicals'"
        ).fetchone()
        if existed and has_chem is not None and version < CURRENT_SCHEMA_VERSION:
            self._backup_before_migration()
        self._conn.executescript(SCHEMA_SQL)
        self._run_migrations()
        self._rebuild_constraints()
        self._conn.execute(f"PRAGMA user_version = {int(CURRENT_SCHEMA_VERSION)}")
        self._conn.commit()

    def _backup_before_migration(self) -> Path:
        self._conn.execute("PRAGMA wal_checkpoint(FULL)")
        stamp = now_iso().replace(":", "").replace("+", "")
        dest = self.path.with_name(self.path.name + f".bak-migrate-{stamp}")
        shutil.copy2(self.path, dest)
        if not dest.is_file() or dest.stat().st_size <= 0:
            raise RuntimeError("迁移前备份失败，已中止，未继续修改数据库结构")
        return dest

    def _run_migrations(self) -> None:
        for sql in MIGRATIONS:
            try:
                self._conn.execute(sql)
                self._conn.commit()
            except sqlite3.OperationalError as exc:
                message = str(exc).lower()
                if "duplicate column" in message or "no such table" in message:
                    continue
                raise

    def _table_sql(self, name: str) -> str:
        row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return row[0] if row and row[0] else ""

    def _rebuild_constraints(self) -> None:
        self._rebuild_users_if_needed()
        self._rebuild_inventory_sessions_if_needed()

    def _rebuild_users_if_needed(self) -> None:
        sql = self._table_sql("users")
        if not sql or "auditor" in sql:
            return
        self._conn.execute("PRAGMA foreign_keys=OFF")
        try:
            self._conn.execute("BEGIN")
            self._conn.execute(
                """
                CREATE TABLE users_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN (
                        'admin','warehouse','safety','viewer','user','auditor'
                    )),
                    display_name TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    is_demo INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                INSERT INTO users_new(
                    id, username, password_hash, salt, role, display_name,
                    is_active, is_demo, created_at
                )
                SELECT id, username, password_hash, salt, role, display_name,
                       is_active, COALESCE(is_demo, 0), created_at
                FROM users
                """
            )
            self._conn.execute("DROP TABLE users")
            self._conn.execute("ALTER TABLE users_new RENAME TO users")
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            self._conn.execute("PRAGMA foreign_keys=ON")

    def _rebuild_inventory_sessions_if_needed(self) -> None:
        sql = self._table_sql("inventory_sessions")
        if not sql or "cancelled" in sql:
            return
        self._conn.execute("PRAGMA foreign_keys=OFF")
        try:
            self._conn.execute("BEGIN")
            self._conn.execute(
                """
                CREATE TABLE inventory_sessions_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_no TEXT NOT NULL UNIQUE,
                    location_id INTEGER REFERENCES locations(id),
                    operator_id INTEGER NOT NULL REFERENCES users(id),
                    status TEXT NOT NULL DEFAULT 'open'
                        CHECK(status IN ('open','closing','closed','cancelled')),
                    adjustments_posted INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    closed_at TEXT
                )
                """
            )
            self._conn.execute(
                """
                INSERT INTO inventory_sessions_new(
                    id, session_no, location_id, operator_id, status,
                    adjustments_posted, created_at, closed_at
                )
                SELECT id, session_no, location_id, operator_id, status,
                       COALESCE(adjustments_posted, 0), created_at, closed_at
                FROM inventory_sessions
                """
            )
            self._conn.execute("DROP TABLE inventory_sessions")
            self._conn.execute(
                "ALTER TABLE inventory_sessions_new RENAME TO inventory_sessions"
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            self._conn.execute("PRAGMA foreign_keys=ON")

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        cur = self._conn.execute(sql, tuple(params))
        self._conn.commit()
        return cur

    def executemany(self, sql: str, seq: Iterable[Iterable[Any]]) -> sqlite3.Cursor:
        cur = self._conn.executemany(sql, list(seq))
        self._conn.commit()
        return cur

    def fetchone(self, sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
        return self._conn.execute(sql, tuple(params)).fetchone()

    def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return list(self._conn.execute(sql, tuple(params)).fetchall())

    def integrity_check(self) -> str:
        row = self._conn.execute("PRAGMA integrity_check").fetchone()
        return str(row[0]) if row else "fail"

    def foreign_key_violations(self) -> list[sqlite3.Row]:
        return list(self._conn.execute("PRAGMA foreign_key_check").fetchall())

    def reopen(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass
        self._conn = sqlite3.connect(
            str(self.path), timeout=5.0, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._configure()

    def close(self) -> None:
        self._conn.close()
