"""把 mzML / mzXML 编入索引。原始文件只读，哈希前后必须一致。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from lcms_kb.core.models import SAMPLE_TYPES
from lcms_kb.core.readers import read_header, iter_scans
from lcms_kb.db.database import Database
from lcms_kb.errors import RawFileChanged
from lcms_kb.hashing import sha256_file
from lcms_kb.version import __version__

TOP_IONS_PER_SCAN = 8


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def import_open_file(db: Database, path: Path | str, *, operator: str,
                     sample_name: str = "", sample_type: str = "unknown",
                     replicate_group: str = "", inject_order: int | None = None,
                     notes: str = "") -> int:
    """导入一个开放格式文件，返回数据集 id。"""
    path = Path(path)
    if sample_type not in SAMPLE_TYPES:
        raise ValueError(f"未知样品类型 {sample_type}")
    before = sha256_file(path)
    size = path.stat().st_size
    header = read_header(path)
    scan_rows = []
    ion_rows = []
    rt_values = []
    for scan in iter_scans(path, header):
        scan_rows.append(scan)
        if scan.rt_min is not None:
            rt_values.append(scan.rt_min)
        if scan.mz.size:
            order = np.argsort(scan.intensity)[::-1][:TOP_IONS_PER_SCAN]
            for index in order:
                ion_rows.append((
                    scan.scan_number,
                    scan.ms_level,
                    scan.polarity,
                    scan.rt_min,
                    float(scan.mz[index]),
                    float(scan.intensity[index]),
                ))
    after = sha256_file(path)
    if before != after:
        raise RawFileChanged(f"{path} 在读取过程中哈希发生变化，已中止导入。")

    cur = db.conn.cursor()
    cur.execute(
        """
        INSERT INTO datasets(
            file_name, source_path, sha256, byte_size, format_name,
            sample_name, sample_type, replicate_group, inject_order,
            instrument_text, vendors_inferred, acquisition_text, test_only_synthetic,
            imported_at, imported_by, software_version, n_spectra, rt_start, rt_end, notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            path.name,
            str(path.resolve()),
            before,
            size,
            header.format_name,
            sample_name or path.stem,
            sample_type,
            replicate_group or None,
            inject_order,
            "; ".join(header.instrument_terms[:40]),
            ", ".join(header.vendors_inferred),
            "; ".join(header.acquisition_terms),
            1 if header.test_only_synthetic else 0,
            _now(),
            operator,
            __version__,
            len(scan_rows),
            min(rt_values) if rt_values else None,
            max(rt_values) if rt_values else None,
            notes,
        ),
    )
    dataset_id = int(cur.lastrowid)
    cur.executemany(
        """
        INSERT INTO scans(
            dataset_id, scan_number, index_in_file, ms_level, polarity, rt_min,
            scan_mode, scan_mode_basis, precursor_mz, precursor_charge, isolation_width,
            collision_energy, activation, tic, bpc, bpc_mz, filter_string
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (
                dataset_id, scan.scan_number, scan.index_in_file, scan.ms_level, scan.polarity,
                scan.rt_min, scan.scan_mode, scan.scan_mode_basis, scan.precursor_mz,
                scan.precursor_charge, scan.isolation_width, scan.collision_energy,
                scan.activation, scan.tic, scan.bpc, scan.bpc_mz, scan.filter_string,
            )
            for scan in scan_rows
        ],
    )
    cur.executemany(
        """
        INSERT INTO archive_ions(dataset_id, scan_number, ms_level, polarity, rt_min, mz, intensity)
        VALUES (?,?,?,?,?,?,?)
        """,
        [(dataset_id, *row) for row in ion_rows],
    )
    detail = {
        "dataset_id": dataset_id,
        "source_path": str(path.resolve()),
        "sha256": before,
        "n_spectra": len(scan_rows),
        "sample_type": sample_type,
        "vendors_inferred": header.vendors_inferred,
        "test_only_synthetic": header.test_only_synthetic,
    }
    cur.execute(
        "INSERT INTO provenance(action, detail_json, operator, created_at, software_version) VALUES (?,?,?,?,?)",
        ("import", json.dumps(detail, ensure_ascii=False), operator, _now(), __version__),
    )
    db.conn.commit()
    return dataset_id


def list_datasets(db: Database) -> list[dict]:
    rows = db.conn.execute(
        "SELECT * FROM datasets ORDER BY inject_order IS NULL, inject_order, id"
    ).fetchall()
    return [dict(row) for row in rows]


def get_dataset(db: Database, dataset_id: int) -> dict | None:
    row = db.conn.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    return dict(row) if row else None


def update_sample_meta(db: Database, dataset_id: int, *, sample_name: str, sample_type: str,
                       replicate_group: str, inject_order: int | None, operator: str) -> None:
    if sample_type not in SAMPLE_TYPES:
        raise ValueError(sample_type)
    db.conn.execute(
        """
        UPDATE datasets
        SET sample_name = ?, sample_type = ?, replicate_group = ?, inject_order = ?
        WHERE id = ?
        """,
        (sample_name, sample_type, replicate_group or None, inject_order, dataset_id),
    )
    db.conn.execute(
        "INSERT INTO provenance(action, detail_json, operator, created_at, software_version) VALUES (?,?,?,?,?)",
        (
            "update_sample_meta",
            json.dumps({"dataset_id": dataset_id, "sample_type": sample_type}, ensure_ascii=False),
            operator,
            _now(),
            __version__,
        ),
    )
    db.conn.commit()


def scans_for(db: Database, dataset_id: int, *, ms_level: int | None = None,
              polarity: str | None = None) -> list[dict]:
    sql = "SELECT * FROM scans WHERE dataset_id = ?"
    args: list = [dataset_id]
    if ms_level is not None:
        sql += " AND ms_level = ?"
        args.append(ms_level)
    if polarity:
        sql += " AND polarity = ?"
        args.append(polarity)
    sql += " ORDER BY rt_min, index_in_file"
    return [dict(row) for row in db.conn.execute(sql, args).fetchall()]
