"""Packaged smoke checks. Scientific comparisons live in tests/ and use literals."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from labuv.database import ProjectStore
from labuv.errors import LabError
from labuv.examples import load_example
from labuv.importers import import_table
from labuv.paths import examples_dir
from labuv.regression import fit_line
from labuv.reporting import assert_pdf_contains, build_report, write_excel, write_pdf
from labuv.uncertainty import evaluate_bottom_up
from labuv.version import __version__


def run_self_test(db_path=None, report_path=None) -> int:
    work = Path(tempfile.mkdtemp(prefix="labuv-selftest-"))
    database = Path(db_path) if db_path else work / "selftest.sqlite"
    report = {"version": __version__, "checks": []}
    try:
        result = evaluate_bottom_up(load_example("migration.json"))
        _check(report, "migration_uc", abs(result["uc"] - 0.049246827308974936) < 1e-12)
        _check(report, "migration_y", abs(result["y"] - 0.9) < 1e-12)
        folder = work / "实验数据"
        folder.mkdir()
        source = folder / "校准.csv"
        shutil.copyfile(examples_dir() / "bad_calibration.csv", source)
        table = import_table(source)
        failed = False
        try:
            fit_line({"rows": table["rows"], "weight_mode": "ols"})
        except LabError as exc:
            failed = exc.row == 3 and exc.column == "y"
        _check(report, "import_error_located", failed)
        _check(report, "source_not_rewritten", source.read_bytes() == (examples_dir() / "bad_calibration.csv").read_bytes())
        good = import_table(examples_dir() / "calibration.csv")
        fitted = fit_line({"rows": good["rows"], "weight_mode": "ols"})
        document = build_report(
            title="自检",
            module="B1",
            operator="自检",
            model_id=fitted["model_id"],
            result=fitted,
            source_path=good["path"],
            source_sha256=good["sha256"],
            raw_headers=good["headers"],
            raw_rows=[{key: value for key, value in row.items() if key != "_row"} for row in good["rows"]],
        )
        pdf = work / "自检.pdf"
        xlsx = work / "自检.xlsx"
        write_pdf(pdf, document)
        write_excel(xlsx, document)
        assert_pdf_contains(pdf, [document["numbers"]["slope"]])
        _check(report, "pdf_contains_slope", True)
        store = ProjectStore(database)
        project_id = store.save_project(
            name="自检",
            module="B1",
            operator="自检",
            model_id=fitted["model_id"],
            parameters={"rows": good["rows"]},
            result=fitted,
            process_text=fitted["trace"],
            source_path=good["path"],
            raw_bytes=Path(good["path"]).read_bytes(),
        )
        loaded = store.get_project(project_id)
        store.close()
        _check(report, "sqlite_hash", loaded["raw_sha256_checked"] == loaded["source_sha256"] == good["sha256"])
        report["ok"] = all(item["ok"] for item in report["checks"])
    except Exception as exc:
        report["ok"] = False
        report["error"] = str(exc)
    if report_path:
        Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report.get("ok") else 1


def run_gui_probe(db_path=None) -> int:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from labuv.gui.window import MainWindow

    application = QApplication.instance() or QApplication([])
    database = db_path or str(Path(tempfile.mkdtemp(prefix="labuv-gui-")) / "gui.sqlite")
    window = MainWindow(database)
    window.show()
    window.project_name.setText("界面自检")
    window.operator.setText("自检")
    for index, page in enumerate(window.pages):
        window.menu.setCurrentRow(index)
        application.processEvents()
        if getattr(page, "key", "") == "A1":
            page.load_named("migration.json")
            window.calculate_current()
        elif getattr(page, "key", "") == "A2":
            page.load_named("phosphate_recovery.json")
            window.calculate_current()
        elif getattr(page, "key", "") == "B1":
            page.import_path(examples_dir() / "calibration.csv")
            window.calculate_current()
        elif getattr(page, "key", "") in ("B2", "B3", "B5"):
            window.calculate_current()
        elif getattr(page, "key", "") == "B4":
            page.apply_preset()
            window.calculate_current()
        if window.last is None and getattr(page, "key", "") in ("A1", "A2", "B1", "B2", "B3", "B4", "B5"):
            return 1
    image = window.result.chart.grab().toImage()
    if image.isNull() or image.width() < 20:
        return 1
    pdf = Path(database).with_suffix(".pdf")
    xlsx = Path(database).with_suffix(".xlsx")
    window.menu.setCurrentRow(0)
    window.calculate_current()
    window.export_pdf(pdf)
    window.export_excel(xlsx)
    project_id = window.save_current()
    loaded = window.store.get_project(project_id)
    window.pages[7].refresh()
    application.processEvents()
    window.close()
    window.store.close()
    if not pdf.is_file() or not xlsx.is_file():
        return 1
    if loaded["module"] != "A1":
        return 1
    return 0


def _check(report, name, ok):
    report["checks"].append({"name": name, "ok": bool(ok)})
    if not ok:
        raise RuntimeError(name)
