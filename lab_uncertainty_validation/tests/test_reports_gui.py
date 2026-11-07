import os
import shutil
from pathlib import Path

import pytest
from openpyxl import load_workbook

from labuv.database import ProjectStore
from labuv.examples import load_example
from labuv.reporting import assert_pdf_contains, build_report, write_excel, write_pdf
from labuv.uncertainty import evaluate_bottom_up


def test_pdf_excel_and_sqlite_round_trip(tmp_path):
    result = evaluate_bottom_up(load_example("migration.json"))
    report = build_report(title="迁移", module="A1", operator="测试", model_id=result["model_id"], result=result)
    pdf = tmp_path / "报告.pdf"
    xlsx = tmp_path / "报告.xlsx"
    write_pdf(pdf, report)
    write_excel(xlsx, report)
    assert_pdf_contains(pdf, [result["display"]["uc"], result["display"]["y"]])
    sheet = load_workbook(xlsx)["结果"]
    values = [row[1].value for row in sheet.iter_rows(min_row=2)]
    assert result["display"]["uc"] in values
    blob = "x,y\n1,2\n".encode("utf-8")
    (tmp_path / "原始.csv").write_bytes(blob)
    store = ProjectStore(tmp_path / "项目.sqlite")
    project_id = store.save_project(
        name="迁移",
        module="A1",
        operator="测试",
        model_id=result["model_id"],
        parameters=load_example("migration.json"),
        result=result,
        process_text=result["trace"],
        source_path=str(tmp_path / "原始.csv"),
        raw_bytes=blob,
    )
    loaded = store.get_project(project_id)
    store.close()
    assert loaded["raw_sha256_checked"] == loaded["source_sha256"]
    assert loaded["result"]["display"]["uc"] == result["display"]["uc"]
    assert loaded["app_version"]


def test_gui_chain(tmp_path, monkeypatch):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication

    from labuv.gui.window import MainWindow
    from labuv.paths import examples_dir

    application = QApplication.instance() or QApplication([])
    window = MainWindow(tmp_path / "gui.sqlite")
    window.show()
    window.operator.setText("界面测试")
    window.project_name.setText("迁移项目")
    window.pages[0].load_named("migration.json")
    window.calculate_current()
    assert window.last["uc"] == pytest.approx(0.049246827308974936)
    image = window.result.chart.grab().toImage()
    assert not image.isNull() and image.width() > 20
    pdf = tmp_path / "界面.pdf"
    xlsx = tmp_path / "界面.xlsx"
    window.export_pdf(pdf)
    window.export_excel(xlsx)
    assert_pdf_contains(pdf, [window.last["display"]["uc"]])
    folder = tmp_path / "中文路径"
    folder.mkdir()
    copied = folder / "校准.csv"
    shutil.copyfile(examples_dir() / "calibration.csv", copied)
    window.pages[2].import_path(copied)
    window.menu.setCurrentRow(2)
    window.calculate_current()
    assert window.last["n"] == 4
    bad = folder / "坏.csv"
    shutil.copyfile(examples_dir() / "bad_calibration.csv", bad)
    window.pages[2].import_path(bad)
    window.calculate_current()
    assert window.last is None
    assert "第3行" in window.result.trace.toPlainText()
    window.pages[0].load_named("standard_solution.json")
    window.menu.setCurrentRow(0)
    window.calculate_current()
    project_id = window.save_current()
    loaded = window.store.get_project(project_id)
    assert loaded["operator"] == "界面测试"
    assert loaded["engine_version"]
    window.pages[5].apply_preset()
    window.menu.setCurrentRow(5)
    window.calculate_current()
    assert window.last["verified"] is False
    window.menu.setCurrentRow(6)
    window.calculate_current()
    assert window.last["characteristics"][0]["status"] == "未评价"
    window.close()
    application.processEvents()
