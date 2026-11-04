from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from gcms_kb.errors import SchemaError

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS samples (
  id INTEGER PRIMARY KEY,
  sample_code TEXT NOT NULL,
  original_path TEXT NOT NULL,
  original_sha256 TEXT NOT NULL,
  original_size INTEGER NOT NULL,
  source_format TEXT NOT NULL,
  mzml_relpath TEXT,
  archive_relpath TEXT NOT NULL,
  instrument TEXT,
  method_name TEXT,
  acquired_at TEXT,
  imported_at TEXT NOT NULL,
  imported_by TEXT NOT NULL,
  notes TEXT,
  file_hint TEXT,
  is_synthetic INTEGER NOT NULL DEFAULT 0,
  n_scans INTEGER,
  rt_min REAL,
  rt_max REAL
);
CREATE INDEX IF NOT EXISTS idx_samples_code ON samples(sample_code);
CREATE INDEX IF NOT EXISTS idx_samples_imported ON samples(imported_at);

CREATE TABLE IF NOT EXISTS peaks (
  id INTEGER PRIMARY KEY,
  sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
  superseded INTEGER NOT NULL DEFAULT 0,
  algorithm TEXT NOT NULL,
  algorithm_version TEXT NOT NULL,
  rt REAL NOT NULL,
  rt_start REAL NOT NULL,
  rt_end REAL NOT NULL,
  height REAL NOT NULL,
  area REAL NOT NULL,
  apex_scan INTEGER,
  baseline_start REAL,
  baseline_end REAL,
  ri REAL,
  ri_extrapolated INTEGER,
  background_subtracted INTEGER NOT NULL DEFAULT 0,
  mz_blob BLOB,
  int_blob BLOB,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_peaks_sample ON peaks(sample_id, superseded, rt);
CREATE INDEX IF NOT EXISTS idx_peaks_ri ON peaks(ri);

CREATE TABLE IF NOT EXISTS components (
  id INTEGER PRIMARY KEY,
  sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
  superseded INTEGER NOT NULL DEFAULT 0,
  algorithm TEXT NOT NULL,
  algorithm_version TEXT NOT NULL,
  rt REAL NOT NULL,
  rt_start REAL NOT NULL,
  rt_end REAL NOT NULL,
  height REAL NOT NULL,
  area REAL NOT NULL,
  ri REAL,
  ri_extrapolated INTEGER,
  mz_blob BLOB NOT NULL,
  int_blob BLOB NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comp_sample ON components(sample_id, superseded, rt);
CREATE INDEX IF NOT EXISTS idx_comp_ri ON components(ri);

CREATE TABLE IF NOT EXISTS library_entries (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  cas TEXT,
  formula TEXT,
  ri REAL,
  rt REAL,
  source TEXT NOT NULL,
  source_sample_id INTEGER,
  added_by TEXT NOT NULL,
  added_at TEXT NOT NULL,
  notes TEXT,
  is_synthetic INTEGER NOT NULL DEFAULT 0,
  mz_blob BLOB NOT NULL,
  int_blob BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lib_name ON library_entries(name);
CREATE INDEX IF NOT EXISTS idx_lib_cas ON library_entries(cas);
CREATE INDEX IF NOT EXISTS idx_lib_ri ON library_entries(ri);

CREATE TABLE IF NOT EXISTS library_hits (
  id INTEGER PRIMARY KEY,
  sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
  query_kind TEXT NOT NULL,
  query_id INTEGER,
  query_rt REAL,
  library_entry_id INTEGER NOT NULL REFERENCES library_entries(id),
  rank INTEGER NOT NULL,
  score REAL NOT NULL,
  reverse_score REAL,
  matched_peaks INTEGER NOT NULL,
  ri_query REAL,
  ri_library REAL,
  ri_delta REAL,
  ri_pass INTEGER,
  algorithm TEXT NOT NULL,
  superseded INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '谱库候选（未确认）' CHECK (label = '谱库候选（未确认）')
);
CREATE INDEX IF NOT EXISTS idx_hits_sample ON library_hits(sample_id, superseded);
CREATE INDEX IF NOT EXISTS idx_hits_query ON library_hits(query_kind, query_id);

CREATE TABLE IF NOT EXISTS alkane_calibrations (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  notes TEXT
);
CREATE TABLE IF NOT EXISTS alkane_points (
  id INTEGER PRIMARY KEY,
  calibration_id INTEGER NOT NULL REFERENCES alkane_calibrations(id) ON DELETE CASCADE,
  carbon_number INTEGER NOT NULL,
  rt REAL NOT NULL,
  compound_name TEXT
);

CREATE TABLE IF NOT EXISTS confirmations (
  id INTEGER PRIMARY KEY,
  sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
  target_kind TEXT NOT NULL,
  target_id INTEGER,
  decision TEXT NOT NULL CHECK (decision IN ('standard_confirmed', 'manual_review')),
  compound_name TEXT NOT NULL,
  cas TEXT,
  basis TEXT NOT NULL,
  basis_detail TEXT NOT NULL,
  standard_sample_id INTEGER REFERENCES samples(id) ON DELETE SET NULL,
  library_entry_id INTEGER,
  rt_observed REAL,
  ri_observed REAL,
  ri_expected REAL,
  score_informational REAL,
  user_name TEXT NOT NULL,
  decided_at TEXT NOT NULL,
  evidence TEXT NOT NULL,
  CHECK (
    (decision = 'standard_confirmed' AND basis = 'standard_rt_ri_spectrum')
    OR (decision = 'manual_review' AND basis = 'reviewer_judgment')
  ),
  CHECK (length(trim(user_name)) > 0),
  CHECK (length(trim(evidence)) > 0),
  CHECK (length(trim(basis_detail)) > 0),
  CHECK (length(trim(compound_name)) > 0)
);
CREATE INDEX IF NOT EXISTS idx_conf_sample ON confirmations(sample_id);
CREATE INDEX IF NOT EXISTS idx_conf_name ON confirmations(compound_name);
CREATE INDEX IF NOT EXISTS idx_conf_cas ON confirmations(cas);

CREATE TABLE IF NOT EXISTS unknown_log (
  id INTEGER PRIMARY KEY,
  sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
  target_kind TEXT,
  target_id INTEGER,
  rt REAL NOT NULL,
  ri REAL,
  user_name TEXT NOT NULL,
  logged_at TEXT NOT NULL,
  note TEXT NOT NULL,
  evidence TEXT,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
  CHECK (length(trim(user_name)) > 0),
  CHECK (length(trim(note)) > 0)
);
CREATE INDEX IF NOT EXISTS idx_unk_sample ON unknown_log(sample_id);
CREATE INDEX IF NOT EXISTS idx_unk_rt ON unknown_log(rt);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  user_name TEXT NOT NULL,
  action TEXT NOT NULL,
  detail TEXT
);
"""


class Database:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "gcms.sqlite3"
        self._ensure_schema()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=60)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row is None:
                conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '1')")
            elif row["value"] != "1":
                raise SchemaError(f"数据库版本是 {row['value']}，本程序只打开版本 1。")

    def integrity_ok(self) -> bool:
        with self.connect() as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        return row is not None and row[0] == "ok"

    def checkpoint(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA wal_checkpoint(FULL)")

    def audit(self, ts: str, user_name: str, action: str, detail: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO audit_log(ts, user_name, action, detail) VALUES (?,?,?,?)",
                (ts, user_name or "", action, detail),
            )
