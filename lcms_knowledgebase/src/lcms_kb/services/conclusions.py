"""四层结果里，只有人工确认会变成结论。确认必须带依据。"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from lcms_kb.db.database import Database
from lcms_kb.errors import ConfirmationError
from lcms_kb.version import __version__

CANDIDATE_LABEL = "谱库候选（未确认）"
CONFIRMED_LABEL = "人工确认结论"
REJECTED_LABEL = "人工否定"
ALGORITHM_LABEL = "算法结果（非鉴定）"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def record_algorithm(db: Database, *, operator: str, dataset_id: int | None, summary: str,
                     detail: dict, source_sha256: str = "") -> int:
    cur = db.conn.cursor()
    cur.execute(
        """
        INSERT INTO conclusions(
            dataset_id, layer, status, label_zh, detail_json, basis, operator,
            created_at, software_version, source_sha256
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            dataset_id, "algorithm_result", "algorithm_only", ALGORITHM_LABEL,
            json.dumps({"summary": summary, **detail}, ensure_ascii=False),
            None, operator, _now(), __version__, source_sha256 or None,
        ),
    )
    db.conn.commit()
    return int(cur.lastrowid)


def record_candidate(db: Database, *, operator: str, dataset_id: int | None,
                     library_entry_id: int | None, similarity: float | None,
                     ppm_error: float | None, detail: dict, source_sha256: str = "",
                     scan_number: int | None = None) -> int:
    """写入谱库候选。状态固定为未确认，不能从检索直接跳到确认。"""
    cur = db.conn.cursor()
    cur.execute(
        """
        INSERT INTO conclusions(
            dataset_id, scan_number, library_entry_id, layer, status, label_zh,
            similarity, ppm_error, detail_json, operator, created_at, software_version, source_sha256
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            dataset_id, scan_number, library_entry_id, "library_candidate", "candidate_unconfirmed",
            CANDIDATE_LABEL, similarity, ppm_error, json.dumps(detail, ensure_ascii=False),
            operator, _now(), __version__, source_sha256 or None,
        ),
    )
    db.conn.commit()
    return int(cur.lastrowid)


def confirm(db: Database, conclusion_id: int, *, operator: str, basis: str) -> None:
    """把一条未确认候选改成人工确认。依据不能为空。"""
    text = (basis or "").strip()
    if not text:
        raise ConfirmationError("确认必须填写依据。空依据不会被保存。")
    row = db.conn.execute("SELECT * FROM conclusions WHERE id = ?", (conclusion_id,)).fetchone()
    if row is None:
        raise ConfirmationError("找不到这条记录。")
    if row["status"] != "candidate_unconfirmed":
        raise ConfirmationError("只有“谱库候选（未确认）”可以被人工确认。")
    db.conn.execute(
        """
        UPDATE conclusions
        SET layer = 'human_conclusion', status = 'confirmed', label_zh = ?,
            basis = ?, operator = ?, created_at = ?, software_version = ?
        WHERE id = ?
        """,
        (CONFIRMED_LABEL, text, operator, _now(), __version__, conclusion_id),
    )
    db.conn.execute(
        "INSERT INTO provenance(action, detail_json, operator, created_at, software_version) VALUES (?,?,?,?,?)",
        (
            "confirm",
            json.dumps({"conclusion_id": conclusion_id, "basis": text}, ensure_ascii=False),
            operator, _now(), __version__,
        ),
    )
    db.conn.commit()


def reject(db: Database, conclusion_id: int, *, operator: str, basis: str) -> None:
    text = (basis or "").strip()
    if not text:
        raise ConfirmationError("否定也必须填写依据。")
    row = db.conn.execute("SELECT status FROM conclusions WHERE id = ?", (conclusion_id,)).fetchone()
    if row is None or row["status"] != "candidate_unconfirmed":
        raise ConfirmationError("只能否定尚未确认的候选。")
    db.conn.execute(
        """
        UPDATE conclusions
        SET layer = 'human_conclusion', status = 'rejected', label_zh = ?,
            basis = ?, operator = ?, created_at = ?, software_version = ?
        WHERE id = ?
        """,
        (REJECTED_LABEL, text, operator, _now(), __version__, conclusion_id),
    )
    db.conn.commit()


def list_conclusions(db: Database, dataset_id: int | None = None) -> list[dict]:
    if dataset_id is None:
        rows = db.conn.execute("SELECT * FROM conclusions ORDER BY id").fetchall()
    else:
        rows = db.conn.execute(
            "SELECT * FROM conclusions WHERE dataset_id IS NULL OR dataset_id = ? ORDER BY id",
            (dataset_id,),
        ).fetchall()
    return [dict(row) for row in rows]
