"""自建谱库：标准品和历史样品谱图，以及 MSP/MGF 导入导出。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from lcms_kb.core.library_io import LibrarySpectrum, read_mgf, read_msp, write_mgf, write_msp
from lcms_kb.db.database import Database
from lcms_kb.version import __version__


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def add_entry(db: Database, *, entry_type: str, compound_name: str, operator: str,
              formula: str = "", adduct: str = "", polarity: str = "",
              rt_min: float | None = None, precursor_mz: float | None = None,
              collision_energy: float | None = None, activation: str = "",
              scan_mode: str = "", source_dataset_id: int | None = None,
              source_scan_number: int | None = None, source_sha256: str = "",
              notes: str = "", mz=None, intensity=None) -> int:
    if entry_type not in {"standard", "historical"}:
        raise ValueError("谱库类型只能是 standard 或 historical")
    mz_arr = np.asarray([] if mz is None else mz, dtype=float)
    inten = np.asarray([] if intensity is None else intensity, dtype=float)
    peaks = [[float(a), float(b)] for a, b in zip(mz_arr, inten)]
    cur = db.conn.cursor()
    cur.execute(
        """
        INSERT INTO library_entries(
            entry_type, compound_name, formula, adduct, polarity, rt_min, precursor_mz,
            collision_energy, activation, scan_mode, source_dataset_id, source_scan_number,
            source_sha256, created_at, created_by, notes, peaks_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            entry_type, compound_name, formula or None, adduct or None, polarity or None,
            rt_min, precursor_mz, collision_energy, activation or None, scan_mode or None,
            source_dataset_id, source_scan_number, source_sha256 or None,
            _now(), operator, notes, json.dumps(peaks),
        ),
    )
    entry_id = int(cur.lastrowid)
    if peaks:
        order = np.argsort(inten)[::-1][:30]
        cur.executemany(
            "INSERT INTO library_fragments(entry_id, mz, intensity) VALUES (?,?,?)",
            [(entry_id, float(mz_arr[i]), float(inten[i])) for i in order],
        )
    cur.execute(
        "INSERT INTO provenance(action, detail_json, operator, created_at, software_version) VALUES (?,?,?,?,?)",
        ("library_add", json.dumps({"entry_id": entry_id, "entry_type": entry_type, "name": compound_name}, ensure_ascii=False),
         operator, _now(), __version__),
    )
    db.conn.commit()
    return entry_id


def list_entries(db: Database, entry_type: str | None = None) -> list[dict]:
    if entry_type:
        rows = db.conn.execute(
            "SELECT * FROM library_entries WHERE entry_type = ? ORDER BY id", (entry_type,)
        ).fetchall()
    else:
        rows = db.conn.execute("SELECT * FROM library_entries ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def entry_peaks(db: Database, entry_id: int) -> tuple[list[float], list[float]]:
    row = db.conn.execute("SELECT peaks_json FROM library_entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        return [], []
    peaks = json.loads(row["peaks_json"])
    if not peaks:
        return [], []
    mz = [item[0] for item in peaks]
    intensity = [item[1] for item in peaks]
    return mz, intensity


def import_library_file(db: Database, path: Path | str, *, operator: str, entry_type: str) -> int:
    path = Path(path)
    if path.suffix.lower() == ".msp":
        spectra = read_msp(path)
    elif path.suffix.lower() == ".mgf":
        spectra = read_mgf(path)
    else:
        raise ValueError("只接受 MSP 或 MGF")
    count = 0
    for spec in spectra:
        add_entry(
            db,
            entry_type=entry_type,
            compound_name=spec.name or path.stem,
            operator=operator,
            formula=spec.formula or "",
            adduct=spec.adduct or "",
            polarity=spec.polarity or "",
            rt_min=spec.retention_time_min,
            precursor_mz=spec.precursor_mz,
            collision_energy=spec.collision_energy,
            activation=spec.activation or "",
            notes=spec.comments or f"导入自 {path.name}",
            mz=spec.mz,
            intensity=spec.intensity,
        )
        count += 1
    return count


def export_library(db: Database, path: Path | str, *, entry_ids: list[int] | None = None) -> int:
    path = Path(path)
    if entry_ids:
        rows = [dict(row) for row in db.conn.execute(
            f"SELECT * FROM library_entries WHERE id IN ({','.join('?' for _ in entry_ids)})",
            entry_ids,
        ).fetchall()]
    else:
        rows = list_entries(db)
    spectra = []
    for row in rows:
        mz, intensity = entry_peaks(db, row["id"])
        spectra.append(LibrarySpectrum(
            name=row.get("compound_name") or "",
            formula=row.get("formula"),
            adduct=row.get("adduct"),
            polarity=row.get("polarity"),
            retention_time_min=row.get("rt_min"),
            precursor_mz=row.get("precursor_mz"),
            collision_energy=row.get("collision_energy"),
            activation=row.get("activation"),
            mz=np.asarray(mz, dtype=float),
            intensity=np.asarray(intensity, dtype=float),
            comments=row.get("notes") or "",
        ))
    if path.suffix.lower() == ".mgf":
        write_mgf(path, spectra)
    else:
        write_msp(path, spectra)
    return len(spectra)
