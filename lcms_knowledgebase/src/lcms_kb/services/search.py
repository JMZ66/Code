"""检索。命中的谱库记录一律是“谱库候选（未确认）”，不会变成鉴定。"""

from __future__ import annotations

from lcms_kb.core.masscalc import tolerance_window
from lcms_kb.db.database import Database

CANDIDATE_LABEL = "谱库候选（未确认）"


def search_library(db: Database, *, name: str = "", formula: str = "",
                   mz: float | None = None, ppm: float | None = None, da: float | None = None,
                   rt_min: float | None = None, rt_max: float | None = None,
                   fragment_mz: float | None = None, fragment_ppm: float | None = None,
                   polarity: str | None = None, collision_energy: float | None = None,
                   allow_polarity_mismatch: bool = False,
                   allow_energy_mismatch: bool = False) -> list[dict]:
    sql = "SELECT * FROM library_entries WHERE 1=1"
    args: list = []
    if name.strip():
        sql += " AND compound_name LIKE ?"
        args.append(f"%{name.strip()}%")
    if formula.strip():
        sql += " AND formula = ?"
        args.append(formula.strip())
    if mz is not None:
        if ppm is not None:
            low, high = tolerance_window(mz, ppm, "ppm")
        elif da is not None:
            low, high = tolerance_window(mz, da, "da")
        else:
            low, high = tolerance_window(mz, 10, "ppm")
        sql += " AND precursor_mz BETWEEN ? AND ?"
        args.extend([low, high])
    if rt_min is not None:
        sql += " AND rt_min >= ?"
        args.append(rt_min)
    if rt_max is not None:
        sql += " AND rt_min <= ?"
        args.append(rt_max)
    if polarity and not allow_polarity_mismatch:
        sql += " AND (polarity IS NULL OR polarity = ? OR polarity = '')"
        args.append(polarity)
    if collision_energy is not None and not allow_energy_mismatch:
        sql += " AND (collision_energy IS NULL OR ABS(collision_energy - ?) < 1e-6)"
        args.append(collision_energy)
    if fragment_mz is not None:
        f_ppm = 10 if fragment_ppm is None else fragment_ppm
        low, high = tolerance_window(fragment_mz, f_ppm, "ppm")
        sql += " AND id IN (SELECT entry_id FROM library_fragments WHERE mz BETWEEN ? AND ?)"
        args.extend([low, high])
    sql += " ORDER BY id"
    rows = []
    for row in db.conn.execute(sql, args).fetchall():
        item = dict(row)
        item["layer"] = "library_candidate"
        item["status"] = "candidate_unconfirmed"
        item["label_zh"] = CANDIDATE_LABEL
        rows.append(item)
    return rows


def search_archive_ions(db: Database, mz: float, *, ppm: float = 5, polarity: str | None = None,
                        ms_level: int | None = None, limit: int = 200) -> list[dict]:
    """在导入时抽取的强峰索引里找特征离子。索引是算法结果，原始峰仍以文件为准。"""
    low, high = tolerance_window(mz, ppm, "ppm")
    sql = """
        SELECT i.*, d.file_name, d.sample_name, d.sample_type, d.sha256
        FROM archive_ions i
        JOIN datasets d ON d.id = i.dataset_id
        WHERE i.mz BETWEEN ? AND ?
    """
    args: list = [low, high]
    if polarity:
        sql += " AND i.polarity = ?"
        args.append(polarity)
    if ms_level is not None:
        sql += " AND i.ms_level = ?"
        args.append(ms_level)
    sql += " ORDER BY i.intensity DESC LIMIT ?"
    args.append(limit)
    rows = []
    for row in db.conn.execute(sql, args).fetchall():
        item = dict(row)
        item["layer"] = "algorithm_result"
        item["label_zh"] = "归档离子索引（算法结果，不是鉴定）"
        rows.append(item)
    return rows
