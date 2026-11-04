from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from gcms_kb.constants import (
    BASIS_TEXT,
    CANDIDATE_LABEL,
    DECISION_TEXT,
    DISCLAIMER,
    LAYER_ALGORITHM,
    LAYER_CANDIDATE,
    LAYER_CONFIRMED,
    LAYER_RAW,
)
from gcms_kb.paths import resource_path

_FONT_READY = False


def _register_font() -> str:
    global _FONT_READY
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if not _FONT_READY:
        pdfmetrics.registerFont(
            TTFont("WQYMicroHei", str(resource_path("fonts", "wqy-microhei.ttc")), subfontIndex=0)
        )
        _FONT_READY = True
    return "WQYMicroHei"


def _num(value, digits=4):
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.{digits}g}"
    except (TypeError, ValueError):
        return str(value)


def write_excel(report: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    header_font = Font(name="Microsoft YaHei", bold=True, color="FFFFFF")
    body_font = Font(name="Microsoft YaHei")
    header_fill = PatternFill("solid", fgColor="1F4E79")
    warn_fill = PatternFill("solid", fgColor="F4B183")

    def write_sheet(name: str, headers: list[str], rows: list[list], warn: bool = False):
        sheet = book.create_sheet(name)
        sheet.append([name])
        sheet["A1"].font = Font(name="Microsoft YaHei", bold=True, size=14)
        sheet.append([DISCLAIMER])
        sheet.append(headers)
        for cell in sheet[3]:
            cell.font = header_font
            cell.fill = warn_fill if warn else header_fill
            cell.alignment = Alignment(wrap_text=True)
        for row in rows:
            sheet.append(["" if item is None else item for item in row])
        for row in sheet.iter_rows(min_row=4):
            for cell in row:
                cell.font = body_font
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        sheet.freeze_panes = "A4"
        sheet.auto_filter.ref = f"A3:{chr(64 + len(headers))}3" if len(headers) <= 26 else None
        for column in sheet.columns:
            letter = column[0].column_letter
            sheet.column_dimensions[letter].width = 18
        if not rows:
            sheet.append(["（无）"])

    cover = book.active
    cover.title = "封面"
    sample = report["sample"]
    cover["A1"] = "GCMS 谱图知识库报告"
    cover["A1"].font = Font(name="Microsoft YaHei", bold=True, size=16)
    lines = [
        DISCLAIMER,
        "四个层次分开列出：原始信号、算法结果、谱库候选（未确认）、确认结论。",
        "Excel 单元格是 Unicode 文本。中文显示使用本机字体（表格样式指定为微软雅黑）。"
        "xlsx 不能可靠嵌入字体。请同时使用 PDF，PDF 已嵌入文泉驿微米黑。",
        f"样品编号：{sample['sample_code']}",
        f"原始文件：{sample['original_path']}",
        f"SHA-256：{sample['original_sha256']}",
        f"格式：{sample['source_format']}",
        f"仪器/来源提示：{sample.get('instrument') or ''} {sample.get('file_hint') or ''}",
        f"是否合成数据：{'是' if sample.get('is_synthetic') else '否'}",
        f"导入者：{sample['imported_by']}  导入时间：{sample['imported_at']}",
        f"扫描数：{sample.get('n_scans')}  RT {sample.get('rt_min')} – {sample.get('rt_max')} min",
        f"备注：{sample.get('notes') or ''}",
    ]
    for index, line in enumerate(lines, start=3):
        cover.cell(index, 1, line).font = body_font
    cover.column_dimensions["A"].width = 88

    write_sheet(
        "原始样品",
        ["样品编号", "原始路径", "SHA-256", "格式", "合成数据", "文件提示"],
        [[
            sample["sample_code"],
            sample["original_path"],
            sample["original_sha256"],
            sample["source_format"],
            "是" if sample.get("is_synthetic") else "否",
            sample.get("file_hint") or "",
        ]],
    )
    write_sheet(
        "算法峰",
        ["层", "峰号", "RT(min)", "起点", "终点", "高度", "面积", "RI", "外推", "扣背景", "算法"],
        [
            [
                LAYER_ALGORITHM,
                peak["id"],
                peak["rt"],
                peak["rt_start"],
                peak["rt_end"],
                peak["height"],
                peak["area"],
                peak.get("ri"),
                "是" if peak.get("ri_extrapolated") else "",
                "是" if peak.get("background_subtracted") else "否",
                f"{peak['algorithm']} {peak['algorithm_version']}",
            ]
            for peak in report["peaks"]
        ],
    )
    write_sheet(
        "解卷积组分",
        ["层", "组分号", "RT(min)", "起点", "终点", "高度", "面积", "RI", "算法"],
        [
            [
                LAYER_ALGORITHM,
                item["id"],
                item["rt"],
                item["rt_start"],
                item["rt_end"],
                item["height"],
                item["area"],
                item.get("ri"),
                f"{item['algorithm']} {item['algorithm_version']}",
            ]
            for item in report["components"]
        ],
    )
    write_sheet(
        "谱库候选",
        ["层", "状态", "查询", "排名", "谱库名称", "CAS", "加权余弦", "反向分数", "匹配峰数", "RI差", "算法"],
        [
            [
                LAYER_CANDIDATE,
                hit["label"],
                f"{hit['query_kind']}#{hit.get('query_id')}",
                hit["rank"],
                hit["library_name"],
                hit.get("library_cas"),
                hit["score"],
                hit.get("reverse_score"),
                hit["matched_peaks"],
                hit.get("ri_delta"),
                hit["algorithm"],
            ]
            for hit in report["hits"]
        ],
        warn=True,
    )
    write_sheet(
        "确认结论",
        ["层", "类型", "化合物", "CAS", "依据", "操作者", "时间", "RT", "RI", "证据"],
        [
            [
                LAYER_CONFIRMED,
                DECISION_TEXT.get(item["decision"], item["decision"]),
                item["compound_name"],
                item.get("cas"),
                BASIS_TEXT.get(item["basis"], item["basis"]),
                item["user_name"],
                item["decided_at"],
                item.get("rt_observed"),
                item.get("ri_observed"),
                item["evidence"],
            ]
            for item in report["confirmations"]
        ],
    )
    write_sheet(
        "未知峰",
        ["层", "RT", "RI", "操作者", "时间", "状态", "说明"],
        [
            [
                "未知峰",
                item["rt"],
                item.get("ri"),
                item["user_name"],
                item["logged_at"],
                item["status"],
                item["note"],
            ]
            for item in report["unknowns"]
        ],
    )
    book.save(path)


def _p(text, style) -> Paragraph:
    safe = (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )
    return Paragraph(safe, style)


def write_pdf(report: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    font = _register_font()
    title = ParagraphStyle("title", fontName=font, fontSize=16, leading=22, textColor=colors.HexColor("#1F4E79"))
    body = ParagraphStyle("body", fontName=font, fontSize=9, leading=13)
    section = ParagraphStyle("section", fontName=font, fontSize=12, leading=16, textColor=colors.HexColor("#1F4E79"))
    small = ParagraphStyle("small", fontName=font, fontSize=8, leading=11)
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="GCMS 谱图知识库报告",
    )
    sample = report["sample"]
    story = [
        _p("GCMS 谱图知识库报告", title),
        Spacer(1, 4 * mm),
        _p(DISCLAIMER, body),
        _p("本 PDF 嵌入文泉驿微米黑，不依赖阅读电脑是否安装中文字体。", body),
        Spacer(1, 2 * mm),
        _p(f"样品编号：{sample['sample_code']}", body),
        _p(f"原始文件：{sample['original_path']}", body),
        _p(f"SHA-256：{sample['original_sha256']}", small),
        _p(
            f"格式：{sample['source_format']}；合成数据：{'是' if sample.get('is_synthetic') else '否'}；"
            f"提示：{sample.get('file_hint') or '无'}",
            body,
        ),
        _p(f"导入：{sample['imported_by']} {sample['imported_at']}", body),
        _p(f"{LAYER_RAW}。扫描数 {sample.get('n_scans')}，RT {sample.get('rt_min')}–{sample.get('rt_max')} min。", body),
    ]

    def add_table(heading: str, headers: list[str], rows: list[list]):
        story.append(Spacer(1, 4 * mm))
        story.append(_p(heading, section))
        data = [[_p(header, small) for header in headers]]
        usable = rows[:300]
        for row in usable:
            data.append([_p(_num(item) if not isinstance(item, str) else item, small) for item in row])
        if not rows:
            data.append([_p("（无）", small)] + [_p("", small) for _ in headers[1:]])
        table = Table(data, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        story.append(table)
        if len(rows) > len(usable):
            story.append(_p(f"以下仅列出前 {len(usable)} 条，共 {len(rows)} 条。", small))

    add_table(
        f"{LAYER_ALGORITHM} · 色谱峰",
        ["峰号", "RT", "面积", "高度", "RI"],
        [[peak["id"], peak["rt"], peak["area"], peak["height"], peak.get("ri")] for peak in report["peaks"]],
    )
    add_table(
        f"{LAYER_ALGORITHM} · 解卷积组分（纯化谱，不是鉴定）",
        ["组分", "RT", "面积", "高度", "RI"],
        [[item["id"], item["rt"], item["area"], item["height"], item.get("ri")] for item in report["components"]],
    )
    add_table(
        f"{LAYER_CANDIDATE}",
        ["状态", "名称", "余弦", "反向", "匹配峰"],
        [
            [CANDIDATE_LABEL, hit["library_name"], hit["score"], hit.get("reverse_score"), hit["matched_peaks"]]
            for hit in report["hits"]
        ],
    )
    add_table(
        f"{LAYER_CONFIRMED}",
        ["类型", "化合物", "操作者", "时间", "证据"],
        [
            [
                DECISION_TEXT.get(item["decision"], item["decision"]),
                item["compound_name"],
                item["user_name"],
                item["decided_at"],
                item["evidence"],
            ]
            for item in report["confirmations"]
        ],
    )
    add_table(
        "未知峰记录",
        ["RT", "操作者", "时间", "说明"],
        [[item["rt"], item["user_name"], item["logged_at"], item["note"]] for item in report["unknowns"]],
    )
    doc.build(story)
