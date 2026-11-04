"""本地设置。转换程序路径由用户填写，程序不下载它们。"""

from __future__ import annotations

import getpass
import json

from lcms_kb.db.database import Database

DEFAULTS = {
    "operator_name": "",
    "msconvert_path": "",
    "thermo_parser_path": "",
    "mzmine_path": "",
    "msdial_path": "",
    "default_ppm": "5",
    "blank_ratio": "0.3",
    "qc_rt_limit_min": "0.1",
    "qc_rsd_limit": "0.2",
    "dia_width_da": "8",
}


class Settings:
    def __init__(self, db: Database):
        self.db = db
        for key, value in DEFAULTS.items():
            self.db.conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO NOTHING",
                (key, value),
            )
        self.db.conn.commit()

    def get(self, key: str) -> str:
        row = self.db.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return DEFAULTS.get(key, "")
        return row["value"]

    def set(self, key: str, value: str) -> None:
        self.db.conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.db.conn.commit()

    def operator(self) -> str:
        name = self.get("operator_name").strip()
        if name:
            return name
        try:
            return getpass.getuser()
        except Exception:
            return "unknown"

    def as_dict(self) -> dict[str, str]:
        rows = self.db.conn.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def dump_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True)
