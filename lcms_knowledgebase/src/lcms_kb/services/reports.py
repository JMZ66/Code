"""Excel 和 PDF 报告。四层结果分表，确认结论和候选不会写在一起冒充鉴定。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas

from lcms_kb.db.database import Database
from lcms_kb.paths import font_path
from lcms_kb.services.conclusions import list_conclusions
from lcms_kb.services.importer import get_dataset, list_datasets
from lcms_kb.version import __version__

DISCLAIMER = (
    "本报告把结果分成四层：原始信号、算法结果、谱库候选（未确认）、人工确认结论。"
    "相似度、ppm 误差、同位素匹配和空白标记都不是化合物鉴定。"
    "只有带依据的人工确认结论可以当作本实验室的确认记录。"
)


def _stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def export_excel(db: Database, path: Path, *, operator: str, dataset_ids: list[int] | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    cover = book.active
    cover.title = "说明"
    cover["A1"] = "LCMS 知识库报告"
    cover["A1"].font = Font(bold=True, size=14)
    cover["A2"] = DISCLAIMER
    cover["A3"] = f"软件版本 {__version__}"
    cover["A4"] = f"导出人 {operator}"
    cover["A5"] = f"导出时间 { _stamp() }"
    cover.column_dimensions["A"].width = 100

    datasets = list_datasets(db)
    if dataset_ids:
        datasets = [item for item in datasets if item["id"] in dataset_ids]
    sheet = book.create_sheet("数据集")
    headers = ["id", "file_name", "sha256", "sample_name", "sample_type", "replicate_group",
               "inject_order", "vendors_inferred", "n_spectra", "imported_by", "software_version", "imported_at"]
    sheet.append(headers)
    for item in datasets:
        sheet.append([item.get(key) for key in headers])

    conclusions = []
    for item in datasets:
        conclusions.extend(list_conclusions(db, item["id"]))
    # 去重（list_conclusions 可能带上 dataset_id 为空的记录）
    seen = set()
    unique = []
    for row in conclusions:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        if dataset_ids and row.get("dataset_id") not in dataset_ids and row.get("dataset_id") is not None:
            continue
        unique.append(row)

    def add_layer(title: str, layer: str) -> None:
        ws = book.create_sheet(title)
        cols = ["id", "dataset_id", "scan_number", "library_entry_id", "status", "label_zh",
                "similarity", "ppm_error", "basis", "operator", "created_at", "software_version", "source_sha256", "detail_json"]
        ws.append(cols)
        for row in unique:
            if row["layer"] != layer:
                continue
            ws.append([row.get(col) for col in cols])

    add_layer("算法结果", "algorithm_result")
    add_layer("谱库候选", "library_candidate")
    add_layer("人工结论", "human_conclusion")

    prov = book.create_sheet("溯源")
    prov.append(["id", "action", "operator", "created_at", "software_version", "detail_json"])
    for row in db.conn.execute("SELECT * FROM provenance ORDER BY id"):
        prov.append([row["id"], row["action"], row["operator"], row["created_at"], row["software_version"], row["detail_json"]])

    book.save(path)
    return path


def _register_font() -> str:
    font_file = font_path()
    if not font_file.is_file():
        raise FileNotFoundError(f"缺少中文字体：{font_file}")
    pdfmetrics.registerFont(TTFont("WQY", str(font_file), subfontIndex=0))
    return "WQY"


def export_pdf(db: Database, path: Path, *, operator: str, dataset_ids: list[int] | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    font = _register_font()
    pdf = pdfcanvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    y = height - 18 * mm

    def line(text: str, size: int = 10, gap: float = 6 * mm) -> None:
        nonlocal y
        if y < 20 * mm:
            pdf.showPage()
            y = height - 18 * mm
        pdf.setFont(font, size)
        pdf.drawString(15 * mm, y, text[:110])
        y -= gap

    line("LCMS 知识库报告", 16, 8 * mm)
    line(f"软件版本 {__version__}    导出人 {operator}", 10)
    line(f"导出时间 {_stamp()}", 10)
    for chunk in _wrap(DISCLAIMER, 42):
        line(chunk, 9, 5 * mm)
    line("数据集（原始文件只记录路径和哈希，本报告不改写原始数据）", 12, 7 * mm)
    datasets = list_datasets(db)
    if dataset_ids:
        datasets = [item for item in datasets if item["id"] in set(dataset_ids)]
    if not datasets:
        line("没有数据集。", 10)
    for item in datasets:
        vendors = item.get("vendors_inferred") or "未从元数据推断出厂商"
        synthetic = "；文件内标记为测试用合成数据" if item.get("test_only_synthetic") else ""
        line(
            f"#{item['id']} {item['file_name']}  {item['sample_type']}  谱图 {item['n_spectra']}  厂商推断 {vendors}{synthetic}",
            9, 5 * mm,
        )
        line(f"SHA-256 {item['sha256']}", 8, 5 * mm)
    line("结论分层", 12, 7 * mm)
    for item in datasets:
        for row in list_conclusions(db, item["id"]):
            if dataset_ids and row.get("dataset_id") not in (None, item["id"]):
                continue
            basis = row.get("basis") or ""
            line(
                f"[{row['label_zh']}] 数据集 {row.get('dataset_id')} 扫描 {row.get('scan_number')} "
                f"相似度 {row.get('similarity')} ppm {row.get('ppm_error')}",
                9, 5 * mm,
            )
            if basis:
                line(f"依据：{basis}", 9, 5 * mm)
    line(f"报告由 LCMS_KnowledgeBase {__version__} 生成。", 8, 5 * mm)
    pdf.save()
    return path


def _wrap(text: str, width: int) -> list[str]:
    return [text[i:i + width] for i in range(0, len(text), width)] or [""]


def dataset_summary_line(db: Database, dataset_id: int) -> str:
    item = get_dataset(db, dataset_id)
    if not item:
        return ""
    return f"{item['file_name']} {item['sha256'][:12]}"
