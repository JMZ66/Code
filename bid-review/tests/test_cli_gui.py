import json
from pathlib import Path

import pytest

from bidreview.cli import main
from bidreview.selftest import run_self_test
from tests.corpus_builder import build_corpus


def test_self_test_passes():
    assert run_self_test() == 0


def test_cli_manifest_and_hash(tmp_path: Path, capsys):
    corpus = build_corpus(tmp_path / "corpus")
    out = tmp_path / "out"
    code = main(["check", "--manifest", str(corpus / "manifest.json"), "--out", str(out)])
    assert code == 0
    captured = capsys.readouterr().out
    summary = json.loads(captured.split("报告目录", 1)[0])
    assert summary["inputs_unchanged"] is True
    assert summary["finding_count"] > 0
    assert (out / "审查报告.xlsx").is_file()
    assert (out / "审查报告.html").is_file()
    assert (out / "审查报告.md").is_file()
    capsys.readouterr()
    hash_code = main(["hash", str(corpus / "01_招标文件.docx")])
    assert hash_code == 0
    assert len(capsys.readouterr().out.strip().split()[0]) == 64


def test_gui_runs_review(tmp_path: Path):
    tkinter = pytest.importorskip("tkinter")
    try:
        root = tkinter.Tk()
    except tkinter.TclError:
        pytest.skip("当前环境没有图形显示")
    root.withdraw()
    from bidreview.gui import ReviewApp
    from bidreview.ooxml_build import write_minimal_docx

    template = tmp_path / "template.docx"
    left = tmp_path / "left.docx"
    right = tmp_path / "right.docx"
    write_minimal_docx(template, ["模板"])
    write_minimal_docx(left, ["本项目总工期为10日历天。"])
    write_minimal_docx(right, ["本项目总工期为12日历天。"])
    app = ReviewApp(root)
    app.template_var.set(str(template))
    app.out_var.set(str(tmp_path / "gui-out"))
    app.add_path("tender", str(left))
    app.add_path("contract", str(right))
    app.execute()
    log = app.log.get("1.0", "end")
    root.destroy()
    assert "审查完成" in log
    assert "总工期" in log
    assert (tmp_path / "gui-out" / "审查报告.md").is_file()
    assert left.read_bytes()  # file still readable after the GUI review
