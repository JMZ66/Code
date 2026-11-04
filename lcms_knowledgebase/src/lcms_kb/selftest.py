"""安装包自检。不打开界面，也不把合成谱当作采集数据。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from lcms_kb.core.masscalc import ion_mz
from lcms_kb.core.similarity import modified_cosine
from lcms_kb.db.database import Database
from lcms_kb.errors import BackupError
from lcms_kb.offline import enforce_offline_ontology
from lcms_kb.services.backup import create_backup, inspect_backup, restore_backup
from lcms_kb.version import __version__


def run_self_test() -> int:
    enforce_offline_ontology()
    report: dict = {
        "software": "LCMS_KnowledgeBase",
        "version": __version__,
        "network_required": False,
        "synthetic_data": "none stored; numeric checks only",
        "checks": [],
    }
    try:
        theoretical = ion_mz("C8H10N4O2", charge=1, charge_carrier="H+")
        # 咖啡因 [M+H]+ 的常用参考值。这里只检查计算，不生成谱图。
        if abs(theoretical - 195.08765) > 5e-4:
            raise RuntimeError(f"咖啡因 [M+H]+ 计算值 {theoretical} 偏离参考值")
        report["checks"].append({"name": "caffeine_mh", "ok": True, "mz": theoretical})

        score = modified_cosine([50.0, 80.0], [3.0, 4.0], 100.0, [50.0, 80.0], [3.0, 4.0], 100.0)
        if abs(score.score - 1.0) > 1e-6:
            raise RuntimeError(f"相同谱图的修正余弦不是 1：{score.score}")
        report["checks"].append({"name": "modified_cosine_identical", "ok": True, "score": score.score})

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = Database(root / "selftest.sqlite")
            db.conn.execute(
                "INSERT INTO datasets(file_name, source_path, sha256, byte_size, format_name, sample_type, imported_at, imported_by, software_version, n_spectra) VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("selftest", "selftest", "abc", 1, "mzML", "unknown", "2026-01-01T00:00:00+00:00", "selftest", __version__, 0),
            )
            db.conn.commit()
            backup = create_backup(db, root)
            inspect_backup(backup)
            broken = root / "broken.zip"
            broken.write_bytes(b"this is not a zip")
            try:
                inspect_backup(broken)
            except BackupError:
                report["checks"].append({"name": "corrupt_backup_rejected", "ok": True})
            else:
                raise RuntimeError("损坏的备份没有被拒绝")
            db.conn.execute("DELETE FROM datasets")
            db.conn.commit()
            restore_backup(db, backup, confirm=True)
            count = db.conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
            if count != 1:
                raise RuntimeError("恢复后数据集数量不对")
            report["checks"].append({"name": "backup_restore", "ok": True})
            db.close()
        report["ok"] = True
        print("SELF_TEST_OK")
        print(json.dumps(report, ensure_ascii=False))
        return 0
    except Exception as exc:
        report["ok"] = False
        report["error"] = str(exc)
        print("SELF_TEST_FAIL")
        print(json.dumps(report, ensure_ascii=False))
        return 1
