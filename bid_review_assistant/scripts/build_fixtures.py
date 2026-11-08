#!/usr/bin/env python3
"""构造复杂中文招标测试集（只用于测试，写入 testdata/generated）。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from docx import Document
from docx.enum.text import WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from openpyxl import Workbook
from pypdf import PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "testdata" / "generated"


def _set_run_font(run, name: str, size_pt: float, bold: bool = False) -> None:
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size_pt)
    run.bold = bold


def _add_comment(paragraph, text: str) -> None:
    # 简化：在段落后追加批注提示文本，并创建 comments 部件较复杂；
    # 这里用 document 自定义写入 comments.xml 由后续步骤完成。
    pass


def _ensure_comments_part(docx_path: Path, comment_text: str) -> None:
    """向已有 docx 注入 comments.xml 与关系，标记含批注。"""
    import zipfile
    from io import BytesIO

    comments_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:comment w:id="0" w:author="审查测试" w:date="2024-01-01T00:00:00Z" w:initials="T">
    <w:p><w:r><w:t>{comment_text}</w:t></w:r></w:p>
  </w:comment>
</w:comments>
"""
    buf = BytesIO()
    with zipfile.ZipFile(docx_path, "r") as zin, zipfile.ZipFile(buf, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "[Content_Types].xml" and "comments.xml" not in data.decode(
                "utf-8", errors="ignore"
            ):
                text = data.decode("utf-8")
                text = text.replace(
                    "</Types>",
                    '<Override PartName="/word/comments.xml" '
                    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>'
                    "</Types>",
                )
                data = text.encode("utf-8")
            if item.filename == "word/_rels/document.xml.rels" and "comments.xml" not in data.decode(
                "utf-8", errors="ignore"
            ):
                text = data.decode("utf-8")
                text = text.replace(
                    "</Relationships>",
                    '<Relationship Id="rIdComments" '
                    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" '
                    'Target="comments.xml"/></Relationships>',
                )
                data = text.encode("utf-8")
            zout.writestr(item, data)
        zout.writestr("word/comments.xml", comments_xml.encode("utf-8"))
    docx_path.write_bytes(buf.getvalue())


def _add_revision_ins(docx_path: Path) -> None:
    import zipfile
    from io import BytesIO

    with zipfile.ZipFile(docx_path, "r") as zin:
        xml = zin.read("word/document.xml").decode("utf-8")
        # 注入一个简单的 w:ins
        inject = (
            '<w:ins w:id="1" w:author="测试" w:date="2024-01-01T00:00:00Z">'
            "<w:r><w:t>修订插入文本</w:t></w:r></w:ins>"
        )
        xml = xml.replace("</w:body>", inject + "</w:body>")
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "word/document.xml":
                    data = xml.encode("utf-8")
                zout.writestr(item, data)
    docx_path.write_bytes(buf.getvalue())


def build_template() -> Path:
    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.54)
        section.bottom_margin = Cm(2.54)
        section.left_margin = Cm(3.17)
        section.right_margin = Cm(3.17)
        section.header.paragraphs[0].text = "XX市公共资源交易中心招标文件模板"

    title = doc.add_paragraph()
    run = title.add_run("招标文件")
    _set_run_font(run, "宋体", 16, bold=True)

    for text in (
        "一、项目概况",
        "项目名称：________________",
        "二、招标要求",
        "三、资格要求",
        "四、技术要求",
        "五、合同条款",
        "六、采购清单",
        "附件1 技术规格书",
        "附件2 预算表",
    ):
        p = doc.add_paragraph()
        r = p.add_run(text)
        _set_run_font(r, "宋体", 12)
        p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        p.paragraph_format.line_spacing = 1.5

    table = doc.add_table(rows=3, cols=4)
    hdr = ["序号", "名称", "数量", "单位"]
    for i, h in enumerate(hdr):
        table.rows[0].cells[i].text = h
    table.rows[1].cells[0].text = "1"
    table.rows[1].cells[1].text = "示例设备"
    table.rows[1].cells[2].text = "1"
    table.rows[1].cells[3].text = "台"

    path = OUT / "官方模板.docx"
    doc.save(path)
    return path


def build_main_tender() -> Path:
    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.54)
        section.bottom_margin = Cm(2.54)
        section.left_margin = Cm(3.17)
        section.right_margin = Cm(3.17)
        section.header.paragraphs[0].text = "XX市公共资源交易中心招标文件模板"

    def add(text: str, size: float = 12, font: str = "宋体", bold: bool = False) -> None:
        p = doc.add_paragraph()
        r = p.add_run(text)
        _set_run_font(r, font, size, bold)
        p.paragraph_format.line_spacing = 1.5

    add("招标文件", 16, bold=True)
    add("一、项目概况")
    add("项目名称：智慧实验室设备升级采购项目")
    add("二、招标要求")
    add("本项目工期为 180 天。")  # 与后面隐藏矛盾
    add("预算金额：人民币 1,200,000 元。")
    add("本项目不接受联合体投标。")
    add("三、资格要求")
    add("待填写")  # 缺失实质资格
    add("四、技术要求")
    add("技术指标：检测精度不低于 0.01mg，工作温度 15-30℃。")
    add("五、合同条款")
    add("合同金额为人民币 1200000 元。")
    # 条件不同的类似条款 — 不应判为矛盾
    add("质保期为 24 个月；若含安装调试服务，则调试期为 30 天。")
    add("六、采购清单")
    add("采购数量：10 台。计量单位：台。")
    add("详见附件1 技术规格书。")
    add("详见附件2 预算表。")
    add("详见附件3 资格审查表。")  # 故意缺失附件3
    # 隐藏在不同章节的工期矛盾
    add("七、进度安排")
    add("整体供货与安装工期为 120 天（不含质保期）。")
    add("八、其他")
    add("投标人应提交完整材料。")
    # 重复段落
    add("投标人应提交完整材料。")

    table = doc.add_table(rows=3, cols=4)
    for i, h in enumerate(["序号", "名称", "数量", "单位"]):
        table.rows[0].cells[i].text = h
    table.rows[1].cells[0].text = "1"
    table.rows[1].cells[1].text = "气相色谱仪"
    table.rows[1].cells[2].text = "10"
    table.rows[1].cells[3].text = "台"

    path = OUT / "01_招标正文.docx"
    doc.save(path)
    _ensure_comments_part(path, "请核对工期是否与合同一致")
    _add_revision_ins(path)
    return path


def build_format_drift_same_text() -> Path:
    """文字与正文关键句相同，但字体字号页边距被改。"""
    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(1.5)
        section.bottom_margin = Cm(1.5)
        section.left_margin = Cm(1.5)
        section.right_margin = Cm(1.5)

    def add(text: str) -> None:
        p = doc.add_paragraph()
        r = p.add_run(text)
        _set_run_font(r, "黑体", 14)

    add("招标文件")
    add("一、项目概况")
    add("项目名称：智慧实验室设备升级采购项目")
    add("二、招标要求")
    add("本项目工期为 180 天。")
    add("预算金额：人民币 1,200,000 元。")
    path = OUT / "01b_同文不同格式.docx"
    doc.save(path)
    return path


def build_contract() -> Path:
    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.54)
        section.bottom_margin = Cm(2.54)
        section.left_margin = Cm(3.17)
        section.right_margin = Cm(3.17)

    def add(text: str) -> None:
        p = doc.add_paragraph()
        r = p.add_run(text)
        _set_run_font(r, "宋体", 12)

    add("合同条款")
    add("项目名称：智慧实验室设备升级采购项目")
    add("合同金额为人民币 1,200,000 元。")
    add("交货期为 180 天。")  # 与正文“工期180”一致口径，但正文另有120天安装工期
    add("本项目不接受联合体投标。")
    add("质保期为 24 个月。")
    path = OUT / "02_合同条款.docx"
    doc.save(path)
    return path


def build_tech_pdf() -> Path:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    path = OUT / "03_技术附件.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("STSong-Light", 12)
    y = 800
    lines = [
        "附件1 技术规格书",
        "项目名称：智慧实验室设备升级采购项目",
        "技术指标：检测精度不低于 0.01mg，工作温度 15-30℃。",
        "采购数量：10 台。",
        # 数量单位不一致陷阱：写成 10 套
        "如采购备件包，数量为 10 套（备件，不含主机）。",
        "交货期为 90 天（仅指主机发货，不含安装）。",
    ]
    for line in lines:
        c.drawString(50, y, line)
        y -= 24
    c.showPage()
    c.setFont("STSong-Light", 12)
    c.drawString(50, 800, "第二页：安装要求")
    c.drawString(50, 770, "安装工期另计，见招标正文进度安排。")
    c.save()
    return path


def build_budget_xlsx() -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "预算表"
    ws.append(["序号", "名称", "数量", "单位", "单价(元)", "金额(元)"])
    ws.append([1, "气相色谱仪", 10, "台", 100000, 1000000])
    ws.append([2, "安装服务", 1, "项", 200000, 200000])
    ws.append(["合计", "", "", "", "", 1200000])
    ws2 = wb.create_sheet("说明")
    ws2.append(["预算金额", "人民币 1,250,000 元"])  # 与正文不一致
    ws2.append(["备注", "含暂估价备用金 50,000 元"])
    path = OUT / "04_预算表.xlsx"
    wb.save(path)
    return path


def build_manifest(paths: list[Path]) -> Path:
    lines = ["# 测试集清单", ""]
    for p in paths:
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        lines.append(f"- `{p.name}` SHA-256=`{h}`")
    path = OUT / "MANIFEST.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    paths = [
        build_template(),
        build_main_tender(),
        build_format_drift_same_text(),
        build_contract(),
        build_tech_pdf(),
        build_budget_xlsx(),
    ]
    build_manifest(paths)
    print("fixtures ->", OUT)
    for p in paths:
        print(" ", p.name)


if __name__ == "__main__":
    main()
