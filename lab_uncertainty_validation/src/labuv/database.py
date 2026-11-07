"""SQLite history. Raw file bytes are stored with their SHA-256 and are not rewritten."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from labuv.version import APP_NAME, ENGINE_VERSION, __version__


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    name TEXT NOT NULL,
    module TEXT NOT NULL,
    operator TEXT NOT NULL,
    app_version TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    model_id TEXT,
    source_path TEXT,
    source_sha256 TEXT,
    raw_blob BLOB,
    parameters_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    process_text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    name TEXT NOT NULL,
    module TEXT NOT NULL,
    parameters_json TEXT NOT NULL
);
"""


class ProjectStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    def close(self):
        self._connection.close()

    def save_project(self, *, name, module, operator, model_id, parameters, result, process_text, source_path=None, raw_bytes=None):
        digest = hashlib.sha256(raw_bytes).hexdigest() if raw_bytes is not None else None
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._connection.execute(
            """
            INSERT INTO projects (
                created_at, name, module, operator, app_version, engine_version, model_id,
                source_path, source_sha256, raw_blob, parameters_json, result_json, process_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now, name, module, operator, __version__, ENGINE_VERSION, model_id,
                source_path, digest, raw_bytes,
                json.dumps(parameters, ensure_ascii=False, default=str),
                json.dumps(result, ensure_ascii=False, default=str),
                process_text,
            ),
        )
        self._connection.commit()
        return int(cursor.lastrowid)

    def save_template(self, *, name, module, parameters):
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._connection.execute(
            "INSERT INTO templates (created_at, name, module, parameters_json) VALUES (?, ?, ?, ?)",
            (now, name, module, json.dumps(parameters, ensure_ascii=False, default=str)),
        )
        self._connection.commit()
        return int(cursor.lastrowid)

    def search(self, text: str = "", module: str = ""):
        query = "SELECT id, created_at, name, module, operator, model_id, source_sha256, app_version, engine_version FROM projects WHERE 1=1"
        args = []
        if text:
            query += " AND (name LIKE ? OR operator LIKE ?)"
            args.extend([f"%{text}%", f"%{text}%"])
        if module:
            query += " AND module = ?"
            args.append(module)
        query += " ORDER BY id DESC"
        return [dict(row) for row in self._connection.execute(query, args)]

    def get_project(self, project_id: int) -> dict:
        row = self._connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise KeyError(project_id)
        data = dict(row)
        data["parameters"] = json.loads(data.pop("parameters_json"))
        data["result"] = json.loads(data.pop("result_json"))
        if data["raw_blob"] is not None:
            data["raw_sha256_checked"] = hashlib.sha256(data["raw_blob"]).hexdigest()
        return data

    def templates(self, module: str = ""):
        if module:
            rows = self._connection.execute(
                "SELECT id, created_at, name, module, parameters_json FROM templates WHERE module = ? ORDER BY id DESC",
                (module,),
            )
        else:
            rows = self._connection.execute("SELECT id, created_at, name, module, parameters_json FROM templates ORDER BY id DESC")
        result = []
        for row in rows:
            item = dict(row)
            item["parameters"] = json.loads(item.pop("parameters_json"))
            result.append(item)
        return result


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def about_versions() -> dict:
    return {"app": APP_NAME, "version": __version__, "engine": ENGINE_VERSION}
