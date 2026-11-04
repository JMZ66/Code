from __future__ import annotations

import sqlite3
from pathlib import Path

from gcms_kb.blobs import pack_array, unpack_array
from gcms_kb.constants import CANDIDATE_LABEL
from gcms_kb.db import Database


def _rows(conn, sql: str, params=()) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def insert_sample(db: Database, record: dict) -> int:
    columns = [
        "sample_code",
        "original_path",
        "original_sha256",
        "original_size",
        "source_format",
        "mzml_relpath",
        "archive_relpath",
        "instrument",
        "method_name",
        "acquired_at",
        "imported_at",
        "imported_by",
        "notes",
        "file_hint",
        "is_synthetic",
        "n_scans",
        "rt_min",
        "rt_max",
    ]
    sql = f"INSERT INTO samples({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
    with db.connect() as conn:
        cur = conn.execute(sql, [record.get(column) for column in columns])
        return int(cur.lastrowid)


def get_sample(db: Database, sample_id: int) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM samples WHERE id=?", (sample_id,)).fetchone()
    return dict(row) if row else None


def like_contains(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def list_samples(db: Database, text: str = "", limit: int = 5000) -> list[dict]:
    text = text.strip()
    with db.connect() as conn:
        if text:
            pattern = like_contains(text)
            return _rows(
                conn,
                """
                SELECT * FROM samples
                WHERE sample_code LIKE ? ESCAPE '\\' COLLATE NOCASE
                   OR ifnull(notes,'') LIKE ? ESCAPE '\\' COLLATE NOCASE
                   OR ifnull(instrument,'') LIKE ? ESCAPE '\\' COLLATE NOCASE
                ORDER BY id DESC
                LIMIT ?
                """,
                (pattern, pattern, pattern, limit),
            )
        return _rows(conn, "SELECT * FROM samples ORDER BY id DESC LIMIT ?", (limit,))


def count_samples(db: Database) -> int:
    with db.connect() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0])


def delete_sample(db: Database, sample_id: int) -> dict | None:
    sample = get_sample(db, sample_id)
    if sample is None:
        return None
    with db.connect() as conn:
        conn.execute("DELETE FROM samples WHERE id=?", (sample_id,))
    return sample


def supersede_peaks(db: Database, sample_id: int) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE peaks SET superseded=1 WHERE sample_id=? AND superseded=0", (sample_id,))
        conn.execute(
            "UPDATE library_hits SET superseded=1 WHERE sample_id=? AND query_kind='peak' AND superseded=0",
            (sample_id,),
        )


def insert_peak(db: Database, record: dict) -> int:
    with db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO peaks(
              sample_id, superseded, algorithm, algorithm_version, rt, rt_start, rt_end,
              height, area, apex_scan, baseline_start, baseline_end, ri, ri_extrapolated,
              background_subtracted, mz_blob, int_blob, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                record["sample_id"],
                0,
                record["algorithm"],
                record["algorithm_version"],
                record["rt"],
                record["rt_start"],
                record["rt_end"],
                record["height"],
                record["area"],
                record.get("apex_scan"),
                record.get("baseline_start"),
                record.get("baseline_end"),
                record.get("ri"),
                record.get("ri_extrapolated"),
                1 if record.get("background_subtracted") else 0,
                pack_array(record.get("mz", [])),
                pack_array(record.get("intensity", [])),
                record["created_at"],
            ),
        )
        return int(cur.lastrowid)


def list_peaks(db: Database, sample_id: int, *, current: bool = True) -> list[dict]:
    sql = "SELECT * FROM peaks WHERE sample_id=?"
    params: list = [sample_id]
    if current:
        sql += " AND superseded=0"
    sql += " ORDER BY rt"
    with db.connect() as conn:
        rows = _rows(conn, sql, params)
    for row in rows:
        row["mz"] = unpack_array(row.pop("mz_blob"))
        row["intensity"] = unpack_array(row.pop("int_blob"))
    return rows


def update_peak_ri(db: Database, peak_id: int, ri: float | None, extrapolated: bool) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE peaks SET ri=?, ri_extrapolated=? WHERE id=?",
            (ri, 1 if extrapolated else 0, peak_id),
        )


def supersede_components(db: Database, sample_id: int) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE components SET superseded=1 WHERE sample_id=? AND superseded=0",
            (sample_id,),
        )
        conn.execute(
            "UPDATE library_hits SET superseded=1 WHERE sample_id=? AND query_kind='component' AND superseded=0",
            (sample_id,),
        )


def insert_component(db: Database, record: dict) -> int:
    with db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO components(
              sample_id, superseded, algorithm, algorithm_version, rt, rt_start, rt_end,
              height, area, ri, ri_extrapolated, mz_blob, int_blob, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                record["sample_id"],
                0,
                record["algorithm"],
                record["algorithm_version"],
                record["rt"],
                record["rt_start"],
                record["rt_end"],
                record["height"],
                record["area"],
                record.get("ri"),
                record.get("ri_extrapolated"),
                pack_array(record["mz"]),
                pack_array(record["intensity"]),
                record["created_at"],
            ),
        )
        return int(cur.lastrowid)


def list_components(db: Database, sample_id: int, *, current: bool = True) -> list[dict]:
    sql = "SELECT * FROM components WHERE sample_id=?"
    params: list = [sample_id]
    if current:
        sql += " AND superseded=0"
    sql += " ORDER BY rt"
    with db.connect() as conn:
        rows = _rows(conn, sql, params)
    for row in rows:
        row["mz"] = unpack_array(row.pop("mz_blob"))
        row["intensity"] = unpack_array(row.pop("int_blob"))
    return rows


def update_component_ri(db: Database, component_id: int, ri: float | None, extrapolated: bool) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE components SET ri=?, ri_extrapolated=? WHERE id=?",
            (ri, 1 if extrapolated else 0, component_id),
        )


def insert_library(db: Database, record: dict) -> int:
    with db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO library_entries(
              name, cas, formula, ri, rt, source, source_sample_id, added_by, added_at,
              notes, is_synthetic, mz_blob, int_blob
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                record["name"],
                record.get("cas") or None,
                record.get("formula") or None,
                record.get("ri"),
                record.get("rt"),
                record["source"],
                record.get("source_sample_id"),
                record["added_by"],
                record["added_at"],
                record.get("notes") or "",
                1 if record.get("is_synthetic") else 0,
                pack_array(record["mz"]),
                pack_array(record["intensity"]),
            ),
        )
        return int(cur.lastrowid)


def list_library(db: Database) -> list[dict]:
    with db.connect() as conn:
        rows = _rows(conn, "SELECT * FROM library_entries ORDER BY id")
    for row in rows:
        row["mz"] = unpack_array(row.pop("mz_blob"))
        row["intensity"] = unpack_array(row.pop("int_blob"))
    return rows


def get_library(db: Database, entry_id: int) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM library_entries WHERE id=?", (entry_id,)).fetchone()
    if row is None:
        return None
    record = dict(row)
    record["mz"] = unpack_array(record.pop("mz_blob"))
    record["intensity"] = unpack_array(record.pop("int_blob"))
    return record


def supersede_hits(db: Database, sample_id: int, query_kind: str, query_id: int) -> None:
    with db.connect() as conn:
        conn.execute(
            """
            UPDATE library_hits SET superseded=1
            WHERE sample_id=? AND query_kind=? AND query_id=? AND superseded=0
            """,
            (sample_id, query_kind, query_id),
        )


def insert_hit(db: Database, record: dict) -> int:
    label = record.get("label") or CANDIDATE_LABEL
    with db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO library_hits(
              sample_id, query_kind, query_id, query_rt, library_entry_id, rank, score,
              reverse_score, matched_peaks, ri_query, ri_library, ri_delta, ri_pass,
              algorithm, superseded, created_at, label
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)
            """,
            (
                record["sample_id"],
                record["query_kind"],
                record.get("query_id"),
                record.get("query_rt"),
                record["library_entry_id"],
                record["rank"],
                record["score"],
                record.get("reverse_score"),
                record["matched_peaks"],
                record.get("ri_query"),
                record.get("ri_library"),
                record.get("ri_delta"),
                record.get("ri_pass"),
                record["algorithm"],
                record["created_at"],
                label,
            ),
        )
        return int(cur.lastrowid)


def list_hits(db: Database, sample_id: int, *, current: bool = True) -> list[dict]:
    sql = """
    SELECT h.*, e.name AS library_name, e.cas AS library_cas, e.formula AS library_formula,
           e.is_synthetic AS library_synthetic
    FROM library_hits h
    JOIN library_entries e ON e.id = h.library_entry_id
    WHERE h.sample_id=?
    """
    params: list = [sample_id]
    if current:
        sql += " AND h.superseded=0"
    sql += " ORDER BY h.query_kind, h.query_id, h.rank"
    with db.connect() as conn:
        return _rows(conn, sql, params)


def insert_calibration(db: Database, name: str, user: str, created_at: str, notes: str, points: list[dict]) -> int:
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO alkane_calibrations(name, created_by, created_at, notes) VALUES (?,?,?,?)",
            (name, user, created_at, notes),
        )
        calibration_id = int(cur.lastrowid)
        conn.executemany(
            """
            INSERT INTO alkane_points(calibration_id, carbon_number, rt, compound_name)
            VALUES (?,?,?,?)
            """,
            [
                (calibration_id, int(point["carbon_number"]), float(point["rt"]), point.get("name") or "")
                for point in points
            ],
        )
        return calibration_id


def list_calibrations(db: Database) -> list[dict]:
    with db.connect() as conn:
        return _rows(conn, "SELECT * FROM alkane_calibrations ORDER BY id DESC")


def calibration_points(db: Database, calibration_id: int) -> list[dict]:
    with db.connect() as conn:
        return _rows(
            conn,
            """
            SELECT carbon_number, rt, compound_name AS name
            FROM alkane_points WHERE calibration_id=? ORDER BY rt
            """,
            (calibration_id,),
        )


def insert_confirmation(db: Database, record: dict) -> int:
    with db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO confirmations(
              sample_id, target_kind, target_id, decision, compound_name, cas, basis,
              basis_detail, standard_sample_id, library_entry_id, rt_observed, ri_observed,
              ri_expected, score_informational, user_name, decided_at, evidence
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                record["sample_id"],
                record["target_kind"],
                record.get("target_id"),
                record["decision"],
                record["compound_name"],
                record.get("cas") or None,
                record["basis"],
                record["basis_detail"],
                record.get("standard_sample_id"),
                record.get("library_entry_id"),
                record.get("rt_observed"),
                record.get("ri_observed"),
                record.get("ri_expected"),
                record.get("score_informational"),
                record["user_name"],
                record["decided_at"],
                record["evidence"],
            ),
        )
        return int(cur.lastrowid)


def list_confirmations(db: Database, sample_id: int | None = None) -> list[dict]:
    sql = "SELECT * FROM confirmations"
    params: tuple = ()
    if sample_id is not None:
        sql += " WHERE sample_id=?"
        params = (sample_id,)
    sql += " ORDER BY id"
    with db.connect() as conn:
        return _rows(conn, sql, params)


def insert_unknown(db: Database, record: dict) -> int:
    with db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO unknown_log(
              sample_id, target_kind, target_id, rt, ri, user_name, logged_at, note, evidence, status
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                record["sample_id"],
                record.get("target_kind"),
                record.get("target_id"),
                record["rt"],
                record.get("ri"),
                record["user_name"],
                record["logged_at"],
                record["note"],
                record.get("evidence") or "",
                record.get("status") or "open",
            ),
        )
        return int(cur.lastrowid)


def list_unknowns(db: Database, sample_id: int | None = None) -> list[dict]:
    sql = "SELECT * FROM unknown_log"
    params: tuple = ()
    if sample_id is not None:
        sql += " WHERE sample_id=?"
        params = (sample_id,)
    sql += " ORDER BY id"
    with db.connect() as conn:
        return _rows(conn, sql, params)


def peak_is_superseded(db: Database, peak_id: int) -> bool | None:
    with db.connect() as conn:
        row = conn.execute("SELECT superseded FROM peaks WHERE id=?", (peak_id,)).fetchone()
    if row is None:
        return None
    return bool(row["superseded"])


def open_connection(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
