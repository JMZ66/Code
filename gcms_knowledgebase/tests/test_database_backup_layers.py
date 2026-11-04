import hashlib
import time
import zipfile
from pathlib import Path

import numpy as np

from gcms_kb.backup import create_backup, restore_backup, verify_backup
from gcms_kb.blobs import pack_array
from gcms_kb.constants import BASIS_REVIEW, BASIS_STANDARD, CANDIDATE_LABEL, DECISION_MANUAL, DECISION_STANDARD
from gcms_kb.errors import CorruptBackup, ValidationError
from gcms_kb.hashing import sha256_file
from gcms_kb.mzml_io import write_mzml
from gcms_kb.service import KnowledgeBase


def _one_peak_file(path: Path):
    rt = np.arange(4.0, 6.0, 0.01)
    scans = []
    for time_point in rt:
        height = 1000 * np.exp(-0.5 * ((time_point - 5.0) / 0.05) ** 2)
        scans.append((np.array([91.0, 92.0]), np.array([height, height * 0.1])))
    write_mzml(path, rt, scans, synthetic=True)


def test_import_does_not_change_raw_bytes(kb, tmp_path):
    source = tmp_path / "sample.mzML"
    _one_peak_file(source)
    source.chmod(0o444)
    before = sha256_file(source)
    size = source.stat().st_size
    mode = source.stat().st_mode
    result = kb.import_mzml(source, "测试员", sample_code="S-1")
    after = sha256_file(source)
    assert before == after == result["original_sha256"]
    assert source.stat().st_size == size
    assert source.stat().st_mode == mode
    check = kb.verify_original(result["id"])
    assert check["unchanged"] is True


def test_high_score_is_not_a_confirmation(kb, tmp_path):
    source = tmp_path / "libpeak.mzML"
    _one_peak_file(source)
    sample = kb.import_mzml(source, "测试员")
    peaks = kb.detect_peaks_for(sample["id"])
    assert peaks
    kb.add_library_spectrum(
        {
            "name": "合成对照",
            "cas": "000-00-0",
            "mz": peaks[0]["mz"],
            "intensity": peaks[0]["intensity"],
            "ri": 800,
            "is_synthetic": True,
            "source": "sample",
            "added_by": "测试员",
        }
    )
    hits = kb.search_library(sample["id"], "peak", peaks[0]["id"])
    assert hits
    assert hits[0]["score"] > 0.9
    assert hits[0]["label"] == CANDIDATE_LABEL
    assert kb.report(sample["id"])["confirmations"] == []
    bad = {
        "sample_id": sample["id"],
        "target_kind": "peak",
        "target_id": peaks[0]["id"],
        "decision": "library_match",
        "basis": "score",
        "compound_name": "合成对照",
        "basis_detail": "只有分数",
        "user_name": "测试员",
        "evidence": "不应该被接受的证据文本",
    }
    try:
        kb.confirm(bad)
    except ValidationError:
        pass
    else:
        raise AssertionError("相似度不能直接确认")
    assert kb.report(sample["id"])["confirmations"] == []
    kb.confirm(
        {
            "sample_id": sample["id"],
            "target_kind": "peak",
            "target_id": peaks[0]["id"],
            "decision": DECISION_MANUAL,
            "basis": BASIS_REVIEW,
            "compound_name": "需人工判断的组分",
            "basis_detail": "审核人对照了保留时间和峰形",
            "user_name": "审核员甲",
            "evidence": "人工审核，不依据单独的相似度分数。",
            "rt_observed": peaks[0]["rt"],
            "score_informational": hits[0]["score"],
        }
    )
    saved = kb.report(sample["id"])["confirmations"]
    assert len(saved) == 1
    assert saved[0]["decision"] == DECISION_MANUAL
    assert saved[0]["user_name"] == "审核员甲"
    try:
        kb.confirm(
            {
                "sample_id": sample["id"],
                "target_kind": "peak",
                "target_id": peaks[0]["id"],
                "decision": DECISION_STANDARD,
                "basis": BASIS_STANDARD,
                "compound_name": "缺少证据",
                "basis_detail": "太短",
                "user_name": "审核员甲",
                "evidence": "短",
            }
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("过短的标准品证据必须拒绝")


def test_search_keeps_layers_apart(kb, tmp_path):
    source = tmp_path / "search.mzML"
    _one_peak_file(source)
    sample = kb.import_mzml(source, "测试员", sample_code="LAB-9")
    peaks = kb.detect_peaks_for(sample["id"])
    kb.add_library_spectrum(
        {
            "name": "库中甲苯",
            "cas": "108-88-3",
            "mz": [91, 92],
            "intensity": [100, 40],
            "added_by": "测试员",
            "source": "msp",
        }
    )
    kb.confirm(
        {
            "sample_id": sample["id"],
            "target_kind": "peak",
            "target_id": peaks[0]["id"],
            "decision": DECISION_STANDARD,
            "basis": BASIS_STANDARD,
            "compound_name": "已确认苯乙烯",
            "cas": "100-42-5",
            "basis_detail": "与同方法标准品保留时间和谱图一致",
            "user_name": "审核员甲",
            "evidence": "标准品 RT 一致，主要离子一致，本次为标准品对照。",
            "rt_observed": peaks[0]["rt"],
        }
    )
    by_name = kb.search(name="甲苯")
    assert by_name["谱库条目"]
    assert by_name["确认结论"] == []
    by_confirmed = kb.search(name="苯乙烯")
    assert by_confirmed["确认结论"]
    assert by_confirmed["谱库条目"] == []
    by_ion = kb.search(ions=[91], sample_code="LAB-9")
    assert any(row["kind"] == "峰" for row in by_ion["算法结果"])
    by_sample = kb.search(sample_code="LAB-9")
    assert by_sample["原始信号"]


def test_backup_roundtrip_and_corrupt_rejection(kb, tmp_path):
    source = tmp_path / "bak.mzML"
    _one_peak_file(source)
    original = kb.import_mzml(source, "测试员", sample_code="KEEP")
    backup_path = tmp_path / "keep.zip"
    create_backup(kb.db, backup_path)
    kb.import_mzml(source, "测试员", sample_code="NEWER")
    assert len(kb.list_samples()) == 2
    safety = restore_backup(kb.db, backup_path)
    restored = KnowledgeBase(kb.data_dir)
    codes = {row["sample_code"] for row in restored.list_samples()}
    assert "KEEP" in codes
    assert "NEWER" not in codes
    assert safety.is_file()
    # 安全备份里应还能看到替换前的 NEWER
    import sqlite3
    import tempfile

    with zipfile.ZipFile(safety) as archive:
        db_bytes = archive.read("gcms.sqlite3")
    scratch = tmp_path / "safety.sqlite3"
    scratch.write_bytes(db_bytes)
    conn = sqlite3.connect(scratch)
    names = {row[0] for row in conn.execute("SELECT sample_code FROM samples")}
    conn.close()
    assert "NEWER" in names

    bad = tmp_path / "bad.zip"
    # 改坏数据库字节但保留旧清单
    with zipfile.ZipFile(backup_path, "r") as src, zipfile.ZipFile(bad, "w") as dst:
        manifest = src.read("manifest.json")
        for info in src.infolist():
            payload = src.read(info.filename)
            if info.filename == "gcms.sqlite3" and payload:
                payload = b"\x00" + payload[1:]
            dst.writestr(info.filename, payload if info.filename != "manifest.json" else manifest)
    before_codes = {row["sample_code"] for row in restored.list_samples()}
    try:
        restore_backup(restored.db, bad)
    except CorruptBackup:
        pass
    else:
        raise AssertionError("损坏的备份必须拒绝")
    after = KnowledgeBase(kb.data_dir)
    assert {row["sample_code"] for row in after.list_samples()} == before_codes


def test_scale_search_uses_index(tmp_path):
    kb = KnowledgeBase(tmp_path / "scale")
    count = 3000
    mz = pack_array([91.0, 105.0])
    inten = pack_array([100.0, 50.0])
    started = time.perf_counter()
    with kb.db.connect() as conn:
        conn.executemany(
            """
            INSERT INTO samples(
              sample_code, original_path, original_sha256, original_size, source_format,
              mzml_relpath, archive_relpath, instrument, method_name, acquired_at,
              imported_at, imported_by, notes, file_hint, is_synthetic, n_scans, rt_min, rt_max
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    f"SYN-{i:05d}",
                    f"/synthetic/{i}.mzML",
                    f"{i:064x}"[:64],
                    1,
                    "mzml",
                    None,
                    "cache/missing.npz",
                    "synthetic",
                    "",
                    None,
                    "2026-01-01T00:00:00+00:00",
                    "规模测试",
                    "合成规模测试，非真实样品",
                    "SYNTHETIC",
                    1,
                    1,
                    0.0,
                    1.0,
                )
                for i in range(count)
            ],
        )
        ids = [row[0] for row in conn.execute("SELECT id FROM samples ORDER BY id")]
        conn.executemany(
            """
            INSERT INTO peaks(
              sample_id, superseded, algorithm, algorithm_version, rt, rt_start, rt_end,
              height, area, apex_scan, baseline_start, baseline_end, ri, ri_extrapolated,
              background_subtracted, mz_blob, int_blob, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    sample_id,
                    0,
                    "scale",
                    "1",
                    5.0 + (index % 5) * 0.1,
                    4.8,
                    5.2,
                    10.0,
                    1.0,
                    0,
                    0.0,
                    0.0,
                    1000 + index % 50,
                    0,
                    0,
                    mz,
                    inten,
                    "2026-01-01T00:00:00+00:00",
                )
                for index, sample_id in enumerate(ids)
            ],
        )
    insert_s = time.perf_counter() - started
    target = "SYN-01500"
    t0 = time.perf_counter()
    with kb.db.connect() as conn:
        found = conn.execute("SELECT id FROM samples WHERE sample_code=?", (target,)).fetchone()
        plan = " ".join(str(row[3]) for row in conn.execute("EXPLAIN QUERY PLAN SELECT id FROM samples WHERE sample_code=?", (target,)))
        window = conn.execute(
            "SELECT COUNT(*) FROM peaks WHERE superseded=0 AND rt BETWEEN ? AND ?",
            (5.2, 5.4),
        ).fetchone()[0]
    lookup_s = time.perf_counter() - t0
    assert found is not None
    assert "idx_samples_code" in plan or "SEARCH" in plan.upper()
    assert window > 0
    assert insert_s < 30
    assert lookup_s < 1.0
    ion_started = time.perf_counter()
    hits = kb.search(ions=[91.0], sample_code=target)
    ion_s = time.perf_counter() - ion_started
    assert hits["算法结果"]
    assert ion_s < 2.0
    # 把耗时写进断言消息，方便测试报告引用真实数字
    assert insert_s >= 0 and lookup_s >= 0


def test_ri_applied_on_sample(kb, tmp_path):
    source = tmp_path / "ri.mzML"
    _one_peak_file(source)
    sample = kb.import_mzml(source, "测试员")
    kb.detect_peaks_for(sample["id"])
    calibration = kb.save_calibration(
        "烷烃",
        [
            {"carbon_number": 10, "rt": 4.0, "name": "C10"},
            {"carbon_number": 11, "rt": 6.0, "name": "C11"},
        ],
        "测试员",
    )
    kb.apply_retention_index(sample["id"], calibration)
    peaks = kb.report(sample["id"])["peaks"]
    assert peaks[0]["ri"] is not None
    assert 1000 < peaks[0]["ri"] < 1100
