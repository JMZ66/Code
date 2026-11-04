"""空白、QC、重复、数据库规模、备份、确认分层和报告。"""

import json
import time
from pathlib import Path

import pytest

from lcms_kb.core.chromatogram import eic
from lcms_kb.core.qc import blank_flag, drift_report, pearson
from lcms_kb.core.readers import read_run
from lcms_kb.db.database import Database
from lcms_kb.errors import BackupError, ConfirmationError
from lcms_kb.hashing import sha256_file
from lcms_kb.services.backup import create_backup, inspect_backup, restore_backup
from lcms_kb.services.conclusions import confirm, list_conclusions, record_algorithm, record_candidate
from lcms_kb.services.importer import import_open_file, list_datasets
from lcms_kb.services.library import add_entry, export_library, import_library_file
from lcms_kb.services.reports import export_excel, export_pdf
from lcms_kb.services.search import search_archive_ions, search_library
from tests.synthetic_mzml import write_blank_mzml, write_synthetic_mzml


def test_blank_qc_and_replicates(tmp_path):
    import numpy as np
    from lcms_kb.core.chromatogram import Chromatogram

    sample = Chromatogram(
        rt_min=np.array([1.0, 2.0]), intensity=np.array([30.0, 10.0]),
        kind="eic", polarity="positive", ms_level=1, layer="raw_signal", label="样品",
    )
    blank = Chromatogram(
        rt_min=np.array([1.0, 2.0]), intensity=np.array([12.0, 0.0]),
        kind="eic", polarity="positive", ms_level=1, layer="raw_signal", label="空白",
    )
    # 样品最高点在 1.0 min、强度 30；同一时间空白强度 12，比值 0.4。
    flagged = blank_flag(sample, blank, ratio_threshold=0.3)
    assert flagged.flagged
    assert flagged.ratio_blank_over_sample == pytest.approx(12 / 30)
    assert flagged.layer == "algorithm_result"
    quiet = blank_flag(sample, blank, ratio_threshold=0.9)
    assert not quiet.flagged
    negative = Chromatogram(
        rt_min=np.array([1.0]), intensity=np.array([1.0]),
        kind="eic", polarity="negative", ms_level=1, layer="raw_signal", label="负",
    )
    with pytest.raises(ValueError):
        blank_flag(sample, negative)
    # 文件里的 EIC 仍能算出，并且不会把负离子算进来。
    sample_scans = read_run(write_synthetic_mzml(tmp_path / "s.mzML"))[1]
    blank_scans = read_run(write_blank_mzml(tmp_path / "b.mzML"))[1]
    assert eic(sample_scans, 200, 0.01, "da", polarity="negative", ms_level=1).intensity.sum() == 0
    assert eic(blank_scans, 200, 0.01, "da", polarity="positive", ms_level=1).intensity.max() == pytest.approx(12)

    report = drift_report([(1.00, 100), (1.02, 98), (1.20, 40)], name="QC", rt_limit=0.1, rsd_limit=0.2)
    assert report.rt_flag
    assert report.rsd_flag
    stable = drift_report([(1.0, 100), (1.01, 101), (1.02, 99)], name="重复", rt_limit=0.1, rsd_limit=0.2)
    assert not stable.rt_flag
    assert not stable.rsd_flag
    assert pearson([1, 2, 3], [1, 2, 3]) == pytest.approx(1)
    assert pearson([1, 1, 1], [1, 2, 3]) is None


def test_import_hash_library_search_and_confirmation(tmp_path):
    path = write_synthetic_mzml(tmp_path / "s.mzML")
    before = sha256_file(path)
    db = Database(tmp_path / "kb.sqlite")
    dataset_id = import_open_file(
        db, path, operator="测试员", sample_name="合成样品", sample_type="sample",
        replicate_group="R1", inject_order=1,
    )
    assert sha256_file(path) == before
    stored = list_datasets(db)[0]
    assert stored["sha256"] == before
    assert stored["test_only_synthetic"] == 1
    assert stored["n_spectra"] == 11

    entry_id = add_entry(
        db, entry_type="standard", compound_name="葡萄糖", operator="测试员",
        formula="C6H12O6", adduct="[M+H]+", polarity="positive", rt_min=1.2,
        precursor_mz=181.07066, collision_energy=20, mz=[50, 80, 120], intensity=[5, 9, 2],
        source_dataset_id=dataset_id, source_scan_number=4, source_sha256=before,
    )
    found = search_library(db, name="葡萄", formula="C6H12O6", mz=181.07066, ppm=5,
                           rt_min=1.0, rt_max=2.0, fragment_mz=80, fragment_ppm=10,
                           polarity="positive", collision_energy=20)
    assert len(found) == 1
    assert found[0]["label_zh"] == "谱库候选（未确认）"
    assert found[0]["status"] == "candidate_unconfirmed"
    missed = search_library(db, polarity="negative", allow_polarity_mismatch=False, name="葡萄")
    assert missed == []
    ions = search_archive_ions(db, 200.0, ppm=5, polarity="positive", ms_level=1)
    assert ions
    assert ions[0]["label_zh"].startswith("归档离子索引")

    candidate_id = record_candidate(
        db, operator="测试员", dataset_id=dataset_id, library_entry_id=entry_id,
        similarity=0.99, ppm_error=0.2, detail={"note": "仅候选"}, source_sha256=before, scan_number=4,
    )
    record_algorithm(db, operator="测试员", dataset_id=dataset_id, summary="ppm", detail={"ppm": 0.2},
                     source_sha256=before)
    with pytest.raises(ConfirmationError):
        confirm(db, candidate_id, operator="测试员", basis="   ")
    confirm(db, candidate_id, operator="审核人", basis="与标准品保留时间和 20 eV 正离子谱一致")
    rows = list_conclusions(db, dataset_id)
    confirmed = next(row for row in rows if row["id"] == candidate_id)
    assert confirmed["status"] == "confirmed"
    assert confirmed["label_zh"] == "人工确认结论"
    assert confirmed["layer"] == "human_conclusion"
    assert "标准品" in confirmed["basis"]
    candidates = [row for row in rows if row["status"] == "candidate_unconfirmed"]
    assert candidates == []
    algorithms = [row for row in rows if row["layer"] == "algorithm_result"]
    assert algorithms and algorithms[0]["label_zh"].startswith("算法结果")

    msp = tmp_path / "out.msp"
    assert export_library(db, msp) == 1
    other = Database(tmp_path / "other.sqlite")
    assert import_library_file(other, msp, operator="测试员", entry_type="historical") == 1
    assert search_library(other, name="葡萄糖")[0]["entry_type"] == "historical"

    xlsx = export_excel(db, tmp_path / "报告.xlsx", operator="测试员")
    pdf = export_pdf(db, tmp_path / "报告.pdf", operator="测试员")
    from openpyxl import load_workbook
    book = load_workbook(xlsx)
    assert "谱库候选" in book.sheetnames
    assert "人工结论" in book.sheetnames
    human = book["人工结论"]
    labels = [human.cell(row, 6).value for row in range(2, human.max_row + 1)]
    assert "人工确认结论" in labels
    assert "谱库候选（未确认）" not in labels
    blob = pdf.read_bytes()
    assert blob.startswith(b"%PDF")
    assert "WenQuan".encode("latin1") in blob or b"WenQuan" in blob
    db.close()
    other.close()


def test_database_scale_search_stays_responsive(tmp_path):
    db = Database(tmp_path / "scale.sqlite")
    n_datasets = 3000
    db.conn.executemany(
        """
        INSERT INTO datasets(
            file_name, source_path, sha256, byte_size, format_name, sample_name, sample_type,
            imported_at, imported_by, software_version, n_spectra, test_only_synthetic
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,1)
        """,
        [
            (f"synthetic-{i}.mzML", f"/tmp/synthetic-{i}.mzML", f"{i:064x}", 10, "mzML",
             f"化合物{i % 50}", "sample", "2026-01-01T00:00:00+00:00", "测试", "1.0.0", 1)
            for i in range(n_datasets)
        ],
    )
    db.conn.executemany(
        """
        INSERT INTO scans(
            dataset_id, scan_number, index_in_file, ms_level, polarity, rt_min, scan_mode,
            precursor_mz, collision_energy, tic, bpc
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            (i + 1, 1, 0, 2, "positive" if i % 2 == 0 else "negative", 1.0 + (i % 10) * 0.1,
             "dda", 100 + (i % 400) * 0.5, 20 if i % 3 else 40, 10, 5)
            for i in range(n_datasets)
        ],
    )
    db.conn.executemany(
        "INSERT INTO library_entries(entry_type, compound_name, formula, polarity, rt_min, precursor_mz, collision_energy, created_at, created_by, peaks_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            ("standard", f"化合物{i}", "C6H12O6" if i % 2 == 0 else "C8H10N4O2",
             "positive", 1.2, 100 + i * 0.01, 20, "2026-01-01T00:00:00+00:00", "测试", "[]")
            for i in range(4000)
        ],
    )
    db.conn.commit()
    started = time.perf_counter()
    rows = db.conn.execute(
        "SELECT id FROM scans WHERE polarity = ? AND precursor_mz BETWEEN ? AND ? AND collision_energy = ?",
        ("positive", 200, 210, 20),
    ).fetchall()
    elapsed = time.perf_counter() - started
    assert rows
    assert elapsed < 1.0
    started = time.perf_counter()
    named = search_library(db, name="化合物1", formula="C6H12O6", polarity="positive")
    assert time.perf_counter() - started < 1.0
    assert named
    db.close()


def test_backup_roundtrip_and_corrupt_rejection(tmp_path):
    db = Database(tmp_path / "kb.sqlite")
    path = write_synthetic_mzml(tmp_path / "s.mzML")
    import_open_file(db, path, operator="测试员", sample_type="qc")
    backup = create_backup(db, tmp_path / "backups")
    manifest = inspect_backup(backup)
    assert manifest["format"] == "lcms-kb-backup"
    db.conn.execute("DELETE FROM datasets")
    db.conn.commit()
    assert list_datasets(db) == []
    with pytest.raises(BackupError):
        restore_backup(db, backup, confirm=False)
    assert list_datasets(db) == []
    pre = restore_backup(db, backup, confirm=True)
    assert pre.exists()
    assert pre.name.startswith("pre-restore-")
    assert len(list_datasets(db)) == 1
    # 损坏的清单哈希
    broken = tmp_path / "broken.zip"
    import zipfile
    with zipfile.ZipFile(backup, "r") as source, zipfile.ZipFile(broken, "w") as dest:
        manifest = json.loads(source.read("manifest.json"))
        manifest["files"][0]["sha256"] = "0" * 64
        dest.writestr("manifest.json", json.dumps(manifest))
        dest.writestr("database.sqlite", source.read("database.sqlite"))
    with pytest.raises(BackupError):
        inspect_backup(broken)
    with pytest.raises(BackupError):
        restore_backup(db, broken, confirm=True)
    assert len(list_datasets(db)) == 1
    garbage = tmp_path / "garbage.zip"
    garbage.write_bytes(b"not a zip")
    with pytest.raises(BackupError):
        inspect_backup(garbage)
    db.close()


def test_raw_file_not_opened_for_write(tmp_path):
    path = write_synthetic_mzml(tmp_path / "s.mzML")
    original = path.read_bytes()
    db = Database(tmp_path / "kb.sqlite")
    import_open_file(db, path, operator="测试员")
    assert path.read_bytes() == original
    assert sha256_file(path) == list_datasets(db)[0]["sha256"]
    db.close()
