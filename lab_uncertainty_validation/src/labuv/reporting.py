"""Excel and PDF reports. PDF text uses the same formatted numbers as the result."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from labuv.errors import LabError
from labuv.numbers import fmt
from labuv.paths import font_path
from labuv.version import APP_NAME, ENGINE_VERSION, __version__

_FONT = "LabUVCJK"
_registered = False


def _ensure_font():
    global _registered
    if not _registered:
        pdfmetrics.registerFont(TTFont(_FONT, str(font_path()), subfontIndex=0))
        _registered = True


def write_excel(path: str | Path, report: dict):
    book = Workbook()
    sheet = book.active
    sheet.title = "结果"
    sheet.append(["项目", "值"])
    for key in ("title", "module", "operator", "model_id", "app_version", "engine_version"):
        sheet.append([key, str(report.get(key, ""))])
    for key, value in (report.get("numbers") or {}).items():
        sheet.append([key, value])
    process = book.create_sheet("计算过程")
    for line in str(report.get("trace") or "").splitlines() or [""]:
        process.append([line])
    raw = book.create_sheet("原始快照")
    raw.append(["来源", report.get("source_path") or ""])
    raw.append(["SHA-256", report.get("source_sha256") or ""])
    headers = report.get("raw_headers") or []
    if headers:
        raw.append(headers)
        for row in report.get("raw_rows") or []:
            raw.append([row.get(header, "") for header in headers])
    budget = book.create_sheet("预算或表格")
    rows = report.get("table_rows") or []
    if rows:
        columns = list(rows[0].keys())
        budget.append(columns)
        for row in rows:
            budget.append([row.get(column) for column in columns])
    book.save(path)


def write_pdf(path: str | Path, report: dict):
    _ensure_font()
    document = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    y = height - 18 * mm
    document.setTitle(report.get("title") or APP_NAME)

    def line(text, size=10, gap=6):
        nonlocal y
        if y < 18 * mm:
            document.showPage()
            y = height - 18 * mm
            document.setFont(_FONT, size)
        document.setFont(_FONT, size)
        document.drawString(15 * mm, y, text[:110])
        y -= gap * mm

    line(APP_NAME, 14, 8)
    line(report.get("title") or "计算报告", 12, 7)
    line(f"版本 {__version__}    计算引擎 {ENGINE_VERSION}")
    line(f"模块 {report.get('module', '')}    操作者 {report.get('operator', '')}")
    line(f"模型 {report.get('model_id', '')}")
    line("本软件不声明 CNAS 认可，程序未做数字签名。")
    if report.get("source_sha256"):
        line(f"原始文件 SHA-256 {report['source_sha256']}")
    line("主要数值", 12, 7)
    for key, value in (report.get("numbers") or {}).items():
        line(f"{key} = {value}")
    line("计算过程", 12, 7)
    for text in str(report.get("trace") or "").splitlines():
        while text:
            line(text[:90], 9, 5)
            text = text[90:]
    for note in report.get("warnings") or []:
        line("注意：" + note, 9, 5)
    document.save()


def build_report(*, title, module, operator, model_id, result, source_path=None, source_sha256=None, raw_headers=None, raw_rows=None) -> dict:
    numbers = {}
    display = result.get("display") or {}
    if "y" in result:
        numbers["y"] = display.get("y", fmt(result.get("y")))
    if "uc" in result:
        numbers["uc"] = display.get("uc", fmt(result.get("uc")))
    if result.get("coverage"):
        numbers["U"] = fmt(result["coverage"].get("expanded"))
        numbers["k"] = fmt(result["coverage"].get("k"))
    if "lod" in result:
        numbers["LOD"] = fmt(result.get("lod"))
        numbers["LOQ"] = fmt(result.get("loq"))
    if "slope" in result and "intercept" in result:
        numbers["intercept"] = fmt(result.get("intercept"))
        numbers["slope"] = fmt(result.get("slope"))
    if "mean_recovery" in result:
        numbers["mean_recovery"] = fmt(result.get("mean_recovery"))
    if "bias" in result:
        numbers["bias"] = fmt(result.get("bias"))
    unit = result.get("unit")
    if unit:
        numbers["unit"] = unit
    table = result.get("budget")
    if table is None and result.get("characteristics"):
        table = result["characteristics"]
    return {
        "title": title,
        "module": module,
        "operator": operator,
        "model_id": model_id,
        "app_version": __version__,
        "engine_version": ENGINE_VERSION,
        "numbers": numbers,
        "trace": result.get("trace") or "",
        "warnings": result.get("warnings") or [],
        "table_rows": table or [],
        "source_path": source_path,
        "source_sha256": source_sha256,
        "raw_headers": raw_headers,
        "raw_rows": raw_rows,
    }


def assert_pdf_contains(path: str | Path, snippets: list[str]):
    from pypdf import PdfReader

    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    missing = [snippet for snippet in snippets if snippet not in text]
    if missing:
        raise LabError("PDF 文本中没有这些结果：" + "、".join(missing), code="pdf")
    return text
