"""数据库连接。每次写入都留在本程序自己的文件里。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from lcms_kb.db.schema import SCHEMA
from lcms_kb.version import __version__


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', '1') "
            "ON CONFLICT(key) DO NOTHING"
        )
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES('software_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (__version__,),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
