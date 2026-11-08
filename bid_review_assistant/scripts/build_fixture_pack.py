#!/usr/bin/env python3
"""构造复杂中文招标测试集（验收用）。只写新文件，不改任何“原始业务文件”。"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from openpyxl import Workbook
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject


ROOT = Path(__file__).resolve().parents[1] / "testdata" / "complex_pack"


def set_run_font(run, name: str, size_pt: float, bold: bool = False) -> None:
    run.font.size = Pt(size_pt)
    run.bold = bold
    run.font.name = name
    r = run._element
    rPr = r.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:ascii"), name)
    rFonts.set(qn("w:hAnsi"), name)
    rFonts.set(qn("w:eastAsia"), name)


def add_para(doc, text, *, style=None, font="宋体", size=12, bold=False, spacing=1.5, align="justify"):
    if style:
        p = doc.add_paragraph(style=style)
        if p.runs:
            p.runs[0].text = text
            set_run_font(p.runs[0], font, size, bold)
        else:
            run = p.add_run(text)
            set_run_font(run, font, size, bold)
    else:
        p = doc.add_paragraph()
        run = p.add_run(text)
        set_run_font(run, font, size, bold)
    pf = p.paragraph_format
    pf.line_spacing = spacing
    mapping = {
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
    }
    p.alignment = mapping.get(align, WD_ALIGN_PARAGRAPH.JUSTIFY)
    return p


def set_margins(doc, top=2.54, bottom=2.54, left=3.17, right=3.17):
    for section in doc.sections:
        section.top_margin = Cm(top)
        section.bottom_margin = Cm(bottom)
        section.left_margin = Cm(left)
        section.right_margin = Cm(right)


def add_comment_like_placeholder(doc):
    # python-docx 不便直接写 comments.xml；用正文批注式残留 + 修订 XML 片段模拟
    p = add_para(doc, "本条供内部讨论【请填写】具体罚则。")
    # 插入修订痕迹
    ins = OxmlElement("w:ins")
    ins.set(qn("w:author"), "内部审核")
    ins.set(qn("w:date"), "2026-01-01T00:00:00Z")
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = "（修订残留：拟改为90天）"
    r.append(t)
    ins.append(r)
    p._p.append(ins)


def build_template() -> Path:
    doc = Document()
    set_margins(doc)
    add_para(doc, "招标文件模板", style="Heading 1", font="黑体", size=16, bold=True, spacing=1.0, align="center")
    add_para(doc, "招标公告", style="Heading 1", font="黑体", size=16, bold=True, spacing=1.0)
    add_para(doc, "项目名称：________", font="宋体", size=12)
    add_para(doc, "投标人须知", style="Heading 1", font="黑体", size=16, bold=True, spacing=1.0)
    add_para(doc, "技术要求", style="Heading 1", font="黑体", size=16, bold=True, spacing=1.0)
    add_para(doc, "合同条款", style="Heading 1", font="黑体", size=16, bold=True, spacing=1.0)
    path = ROOT / "00_官方模板.docx"
    doc.save(path)
    return path


def build_main_doc() -> Path:
    doc = Document()
    set_margins(doc)
    add_para(doc, "某某市智慧实验室设备采购招标文件", style="Heading 1", font="黑体", size=16, bold=True, spacing=1.0, align="center")
    add_para(doc, "招标公告", style="Heading 1", font="黑体", size=16, bold=True, spacing=1.0)
    add_para(doc, "项目名称：某某市智慧实验室设备采购项目", font="宋体", size=12)
    add_para(doc, "预算金额：120万元", font="宋体", size=12)
    add_para(doc, "工期：90日历天", font="宋体", size=12)
    add_para(doc, "不接受联合体投标。", font="宋体", size=12)
    add_para(doc, "投标人须知", style="Heading 1", font="黑体", size=16, bold=True, spacing=1.0)
    add_para(doc, "资质要求：具备机电设备安装工程专业承包二级及以上资质。", font="宋体", size=12)
    add_para(doc, "投标保证金：2万元", font="宋体", size=12)
    add_para(doc, "附件：资格证明材料、技术方案、报价表", font="宋体", size=12)
    add_para(doc, "技术要求", style="Heading 1", font="黑体", size=16, bold=True, spacing=1.0)
    add_para(doc, "技术指标：气相色谱仪检测限不高于0.1ppm，数量：2台。", font="宋体", size=12)
    add_para(doc, "合同条款", style="Heading 1", font="黑体", size=16, bold=True, spacing=1.0)
    add_para(doc, "合同金额以中标价为准，最高限价120万元。", font="宋体", size=12)
    # 隐藏在不同章节的工期矛盾
    add_para(doc, "交货与验收", style="Heading 2", font="黑体", size=14, bold=True, spacing=1.0)
    add_para(doc, "卖方应在合同签订后60天内完成供货安装。", font="宋体", size=12)
    # 条件性条款：不冲突
    add_para(doc, "如遇不可抗力，工期可延长30天。", font="宋体", size=12)
    # 未填占位
    add_para(doc, "联系人：【请填写】 电话：________", font="宋体", size=12)
    add_comment_like_placeholder(doc)
    # 故意格式错误但文字正确（字体改为楷体）
    add_para(doc, "本项目采购数量合计2台气相色谱仪。", font="楷体", size=12)

    # 表格
    table = doc.add_table(rows=3, cols=4)
    hdr = ["序号", "货物名称", "数量", "单位"]
    data = [
        ["1", "气相色谱仪", "2", "台"],
        ["2", "配套气体发生器", "2", "套"],
    ]
    for i, h in enumerate(hdr):
        table.rows[0].cells[i].text = h
    for r, row in enumerate(data, start=1):
        for c, val in enumerate(row):
            table.rows[r].cells[c].text = val

    path = ROOT / "01_招标正文.docx"
    doc.save(path)
    return path


def build_budget_xlsx() -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "预算表"
    ws.append(["序号", "名称", "数量", "单位", "单价(元)", "合价(元)"])
    # 故意：数量写成 3 台，单位仍为台；金额合计与正文不一致
    ws.append([1, "气相色谱仪", 3, "台", 500000, 1500000])
    ws.append([2, "配套气体发生器", 2, "套", 50000, 100000])
    ws.append(["合计", "", "", "", "", 1600000])
    path = ROOT / "02_预算与采购清单.xlsx"
    wb.save(path)
    return path


def build_tech_pdf() -> Path:
    # 简易 PDF：写文本流
    writer = PdfWriter()
    content = (
        "BT /F1 12 Tf 50 750 Td (技术附件) Tj ET "
        "BT /F1 11 Tf 50 720 Td (项目名称：某某市智慧实验室设备采购项目) Tj ET "
        "BT /F1 11 Tf 50 700 Td (技术指标：气相色谱仪检测限不高于0.05ppm) Tj ET "
        "BT /F1 11 Tf 50 680 Td (数量：2台) Tj ET "
        "BT /F1 11 Tf 50 660 Td (工期：3个月) Tj ET "
        "BT /F1 11 Tf 50 640 Td (如经采购人批准，试运行阶段可增加15天调试期。) Tj ET "
        "BT /F1 11 Tf 50 620 Td (附件：缺失的资格要求见招标正文) Tj ET "
    ).encode("utf-8")
    # 更稳妥：用 reportlab 若可用；否则最小 PDF
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfgen import canvas

        path = ROOT / "03_技术附件.pdf"
        c = canvas.Canvas(str(path))
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        c.setFont("STSong-Light", 14)
        c.drawString(50, 800, "技术附件")
        c.setFont("STSong-Light", 11)
        lines = [
            "项目名称：某某市智慧实验室设备采购项目",
            "技术指标：气相色谱仪检测限不高于0.05ppm",
            "数量：2台",
            "工期：3个月",
            "如经采购人批准，试运行阶段可增加15天调试期。",
            "计量单位：台",
        ]
        y = 770
        for line in lines:
            c.drawString(50, y, line)
            y -= 22
        c.showPage()
        c.save()
        return path
    except Exception:
        # fallback minimal blank page — tests that need text will skip PDF specifics
        page = writer.add_blank_page(width=612, height=792)
        path = ROOT / "03_技术附件.pdf"
        writer.write(path)
        # also write a sidecar text for fallback parsing in tests if needed
        (ROOT / "03_技术附件.txt").write_text(
            "技术附件\n项目名称：某某市智慧实验室设备采购项目\n"
            "技术指标：气相色谱仪检测限不高于0.05ppm\n数量：2台\n工期：3个月\n"
            "如经采购人批准，试运行阶段可增加15天调试期。\n",
            encoding="utf-8",
        )
        return path


def build_contract() -> Path:
    doc = Document()
    set_margins(doc)
    add_para(doc, "采购合同（草案）", style="Heading 1", font="黑体", size=16, bold=True, spacing=1.0)
    add_para(doc, "合同条款", style="Heading 1", font="黑体", size=16, bold=True, spacing=1.0)
    add_para(doc, "项目名称：某某市智慧实验室设备采购项目", font="宋体", size=12)
    add_para(doc, "合同金额：最高限价人民币1200000元", font="宋体", size=12)
    # 与正文联合体一致
    add_para(doc, "不允许联合体投标。", font="宋体", size=12)
    # 条件工期：不与正文一般工期冲突
    add_para(doc, "在质保期内，乙方应在接到通知后7个工作日内响应。", font="宋体", size=12)
    # 故意缺资质章节（正文有，合同无）——不算错误
    add_para(doc, "交货地点：采购人指定实验室场地", font="宋体", size=12)
    path = ROOT / "04_合同条款.docx"
    doc.save(path)
    return path


def build_bad_margin_doc() -> Path:
    doc = Document()
    set_margins(doc, top=1.0, bottom=1.0, left=1.0, right=1.0)
    add_para(doc, "格式异常副本", style="Heading 1", font="黑体", size=16, bold=True)
    add_para(doc, "项目名称：某某市智慧实验室设备采购项目", font="宋体", size=12)
    add_para(doc, "本文件文字与正文相同，但页边距被修改。", font="宋体", size=12)
    path = ROOT / "05_格式被改但文字相同.docx"
    doc.save(path)
    return path


def build_profile() -> Path:
    import json

    profile = {
        "version": 1,
        "name": "验收测试配置",
        "body": {"font_name": "宋体", "font_size_pt": 12.0, "line_spacing": 1.5, "alignment": "justify"},
        "heading1": {"font_name": "黑体", "font_size_pt": 16.0, "bold": True},
        "heading2": {"font_name": "黑体", "font_size_pt": 14.0, "bold": True},
        "margins_cm": {"top": 2.54, "bottom": 2.54, "left": 3.17, "right": 3.17, "tolerance": 0.15},
        "table": {"min_cols": 2, "require_header_row": True},
        "required_sections": ["招标公告", "投标人须知", "技术要求", "合同条款"],
        "required_attachments": ["资格证明材料", "技术方案", "报价表"],
        "placeholders": ["____", "【请填写】", "待填写", "XXX", "TODO"],
    }
    path = ROOT / "profile.json"
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    build_template()
    build_main_doc()
    build_budget_xlsx()
    build_tech_pdf()
    build_contract()
    build_bad_margin_doc()
    build_profile()
    manifest = ROOT / "MANIFEST.md"
    manifest.write_text(
        """# 复杂中文招标测试集说明

故意植入的问题：
1. 正文工期 90 天 vs 交货章节 60 天（确定冲突）
2. 正文数量 2 台 vs 预算表 3 台（确定冲突）
3. 正文金额 120 万 vs 预算合计 160 万（确定冲突）
4. 技术附件检测限 0.05ppm vs 正文 0.1ppm（疑似/需判断）
5. 技术附件工期 3 个月≈90 天，与正文一般工期一致（不应误报为冲突）
6. 不可抗力延期、质保响应期等条件条款（不应仅因数值不同判冲突）
7. 未填占位【请填写】与下划线
8. 修订痕迹残留
9. 正文楷体段落（格式错误，文字正确）
10. 页边距被改文件
11. 缺少独立的资格证明材料/技术方案/报价表附件文件

期望：漏报关键冲突尽量低；条件条款误报尽量低。
""",
        encoding="utf-8",
    )
    print(f"Fixture pack written to {ROOT}")


if __name__ == "__main__":
    main()
