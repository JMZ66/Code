import sys
from pathlib import Path

import numpy as np
from openpyxl import load_workbook
from pypdf import PdfReader

from gcms_kb.constants import BASIS_STANDARD, DECISION_STANDARD
from gcms_kb.convert import build_msconvert_command, build_thermo_command
from gcms_kb.errors import ConverterNotConfigured, OriginalModified
from gcms_kb.hashing import sha256_file
from gcms_kb.mzml_io import write_mzml


def _peak_file(path: Path):
    rt = np.arange(4.0, 6.0, 0.02)
    scans = []
    for time_point in rt:
        height = 800 * np.exp(-0.5 * ((time_point - 5.0) / 0.06) ** 2)
        scans.append((np.array([91.0]), np.array([height])))
    write_mzml(path, rt, scans, synthetic=True)


def test_excel_and_pdf_keep_layers(kb, tmp_path):
    source = tmp_path / "report.mzML"
    _peak_file(source)
    sample = kb.import_mzml(source, "测试员", sample_code="报告样品")
    peaks = kb.detect_peaks_for(sample["id"])
    kb.add_library_spectrum(
        {
            "name": "合成甲苯",
            "cas": "108-88-3",
            "mz": peaks[0]["mz"],
            "intensity": peaks[0]["intensity"],
            "added_by": "测试员",
            "source": "sample",
            "is_synthetic": True,
        }
    )
    kb.search_library(sample["id"], "peak", peaks[0]["id"])
    kb.confirm(
        {
            "sample_id": sample["id"],
            "target_kind": "peak",
            "target_id": peaks[0]["id"],
            "decision": DECISION_STANDARD,
            "basis": BASIS_STANDARD,
            "compound_name": "标准品已核对",
            "basis_detail": "同方法标准品的保留时间与谱图一致",
            "user_name": "审核员甲",
            "evidence": "标准品 RT 与谱图均对照过，此条才是确认结论。",
            "rt_observed": peaks[0]["rt"],
        }
    )
    xlsx = tmp_path / "报告.xlsx"
    pdf = tmp_path / "报告.pdf"
    kb.export_excel(sample["id"], xlsx)
    kb.export_pdf(sample["id"], pdf)
    book = load_workbook(xlsx)
    assert "鉴定结果" not in book.sheetnames
    assert "谱库候选" in book.sheetnames
    assert "确认结论" in book.sheetnames
    cover = book["封面"]["A3"].value
    assert "不是化合物鉴定" in cover
    candidate = book["谱库候选"]
    labels = [candidate.cell(row, 2).value for row in range(4, candidate.max_row + 1)]
    assert "谱库候选（未确认）" in labels
    text = "\n".join((page.extract_text() or "") for page in PdfReader(str(pdf)).pages)
    assert "谱库候选（未确认）" in text
    assert "标准品已核对" in text
    raw = pdf.read_bytes()
    assert raw.startswith(b"%PDF")
    assert b"WenQuanYi" in raw or b"WQY" in raw or b"MicroHei" in raw


def _as_converter(tmp_path: Path, script: Path) -> str:
    """Windows 不能靠 shebang 直接执行 .py，改用 cmd 转给当前解释器。"""
    script.write_text(script.read_text(encoding="utf-8"), encoding="utf-8")
    if sys.platform == "win32":
        cmd = tmp_path / f"{script.stem}.cmd"
        cmd.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
        return str(cmd)
    script.chmod(0o755)
    return str(script)


def test_converter_commands_and_optional_execution(kb, tmp_path):
    raw = tmp_path / "demo.RAW"
    raw.write_bytes(b"RAW-BYTES-MUST-STAY")
    out = tmp_path / "out"
    command = build_thermo_command("/opt/ThermoRawFileParser.exe", raw, out)
    assert command[1:] == [f"-i={raw}", f"-o={out}", "-f=1", "-m=0"]
    ms = build_msconvert_command("msconvert", raw, out)
    assert ms[-2:] == ["-o", str(out)]
    try:
        kb.import_raw(raw, "测试员")
    except ConverterNotConfigured:
        pass
    else:
        raise AssertionError("未配置转换器时不能导入 RAW")
    assert raw.read_bytes() == b"RAW-BYTES-MUST-STAY"

    template = tmp_path / "template.mzML"
    _peak_file(template)
    script = tmp_path / "parser.py"
    script.write_text(
        "#!" + sys.executable + "\n"
        "import sys\nfrom pathlib import Path\nimport shutil\n"
        "raw = out = None\n"
        "for arg in sys.argv[1:]:\n"
        "    if arg.startswith('-i='): raw = Path(arg[3:])\n"
        "    elif arg.startswith('-o='): out = Path(arg[3:])\n"
        f"shutil.copyfile(r'{template}', out / (raw.stem + '.mzML'))\n",
        encoding="utf-8",
    )
    kb.settings.thermo_parser_path = _as_converter(tmp_path, script)
    before = sha256_file(raw)
    imported = kb.import_raw(raw, "测试员", sample_code="RAW-COPY")
    assert sha256_file(raw) == before
    assert imported["source_format"] == "raw"
    assert kb.verify_original(imported["id"])["unchanged"] is True

    evil = tmp_path / "evil.py"
    evil.write_text(
        "#!" + sys.executable + "\n"
        "import sys\nfrom pathlib import Path\n"
        "for arg in sys.argv[1:]:\n"
        "    if arg.startswith('-i='):\n"
        "        Path(arg[3:]).write_bytes(b'changed')\n",
        encoding="utf-8",
    )
    victim = tmp_path / "victim.RAW"
    victim.write_bytes(b"keep-me")
    kb.settings.thermo_parser_path = _as_converter(tmp_path, evil)
    try:
        kb.import_raw(victim, "测试员")
    except OriginalModified:
        pass
    else:
        raise AssertionError("转换器改动原始文件时必须中止")


def test_gui_smoke_import_and_peak_table(qtbot, tmp_path):
    from gcms_kb.gui.main_window import MainWindow

    source = tmp_path / "gui.mzML"
    _peak_file(source)
    window = MainWindow(tmp_path / "gui-data", interactive_notices=False)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    results = window.import_paths_sync([source], "界面测试", sample_code="界面样品")
    assert results[0]["ok"]
    assert window.sample_list.count() == 1
    peaks = window.detect_peaks_sync()
    assert peaks
    headers = [window.peak_table.horizontalHeaderItem(i).text() for i in range(window.peak_table.columnCount())]
    assert "面积" in "".join(headers)
    assert all("鉴定" not in header for header in headers)
    assert window.layer_banner.text().count("谱库候选（未确认）") == 1


def test_source_has_no_network_client():
    root = Path(__file__).resolve().parents[1] / "src" / "gcms_kb"
    banned = ("import requests", "urllib.request", "http.client", "pubchempy", "socket.create_connection")
    for path in root.rglob("*.py"):
        if path.name == "net_probe.py":
            continue
        text = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"{path.name} 含有 {token}"


def test_delete_sample_keeps_original_file(kb, tmp_path):
    source = tmp_path / "keep.mzML"
    _peak_file(source)
    before = source.read_bytes()
    sample = kb.import_mzml(source, "测试员")
    kb.delete_sample(sample["id"])
    assert source.read_bytes() == before
    assert kb.list_samples() == []
