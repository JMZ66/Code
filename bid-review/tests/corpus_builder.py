"""Build the synthetic Chinese tender package used by the accuracy test.

The documents are fictional. They are generated, not copied from a real bid.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from lxml import etree
from openpyxl import Workbook
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

SENTENCE_A = "投标人应仔细阅读招标文件的全部内容，并按要求编制投标文件。"
SENTENCE_B = "投标文件应当对招标文件提出的实质性要求和条件作出响应。"
DUPLICATE = "投标报价包括完成本项目所需的全部费用。"
PROJECT_A = "滨江市第一人民医院信息化机房改造项目"
PROJECT_B = "滨江市第二人民医院信息化机房改造项目"

# Machine keys the review must emit for this package, and nothing else.
EXPECTED = [
    {"key": "FORMAT_PARAGRAPH:02:投标人应仔细阅读", "category": "确定错误", "contains": ["楷体"]},
    {"key": "FORMAT_MARGIN:02", "category": "确定错误"},
    {"key": "FORMAT_HEADER:02", "category": "确定错误", "contains": ["草稿"]},
    {"key": "FORMAT_SECTION:02", "category": "确定错误"},
    {"key": "FORMAT_TABLE:02:报价一览表", "category": "确定错误", "contains": ["报价一览表"]},
    {"key": "FORMAT_NUMBERING:02:Heading1", "category": "确定错误"},
    {"key": "FORMAT_FOOTER:02", "category": "确定错误"},
    {"key": "UNFILLED:02:bracket:待填写", "category": "确定错误", "contains": ["待填写"]},
    {"key": "UNFILLED:02:underline", "category": "确定错误"},
    {"key": "UNFILLED:02:empty-cell:投标人名称", "category": "确定错误", "contains": ["投标人名称"]},
    {"key": "RESIDUE_TEMPLATE:02", "category": "确定错误", "contains": ["模板说明"]},
    {"key": "DUPLICATE_PARAGRAPH:02:投标报价包括完成", "category": "确定错误", "contains": ["投标报价包括"]},
    {"key": "MISSING_SECTION:法定代表人身份证明", "category": "确定错误"},
    {"key": "MISSING_ATTACHMENT:电子与智能化工程专业承包资质证书", "category": "确定错误"},
    {"key": "RESIDUE_REVISION:01:del", "category": "确定错误", "contains": ["200日历天"]},
    {"key": "RESIDUE_REVISION:01:ins", "category": "确定错误"},
    {"key": "RESIDUE_COMMENT:01", "category": "确定错误", "contains": ["李工"]},
    {"key": "VALUE_CONFLICT:总工期", "category": "确定错误", "contains": ["180", "150", "90"], "pdf_page": 2},
    {"key": "VALUE_CONFLICT:预算合计", "category": "确定错误", "contains": ["1,280", "12500000"]},
    {"key": "VALUE_CONFLICT:采购项:机柜", "category": "确定错误", "contains": ["12", "10"]},
    {"key": "UNIT_CONFLICT:采购项:六类网线", "category": "确定错误", "contains": ["米", "卷"]},
    {"key": "VALUE_CONFLICT:资质:电子与智能化工程专业承包", "category": "确定错误", "contains": ["一级", "二级"]},
    {"key": "VALUE_CONFLICT:联合体", "category": "确定错误", "values": ["不接受", "接受"]},
    {"key": "VALUE_CONFLICT:项目名称", "category": "确定错误", "values": [PROJECT_A, PROJECT_B]},
    {"key": "VALUE_CONFLICT:UPS容量", "category": "确定错误", "contains": ["30kVA", "20kVA"]},
    {"key": "APPROXIMATE_CONFLICT:交换机交换容量", "category": "疑似冲突", "contains": ["2Tbps", "1.8Tbps"]},
    {"key": "UNIT_FAMILY:服务期", "category": "需要人工判断", "contains": ["12个月", "360日历天"]},
    {"key": "MISSING_BASIS:GB/T50314", "category": "缺少依据", "contains": ["GB/T 50314"]},
]

NEGATIVES = [
    {"id": "NEG-SUPPLY", "subject": "供货期"},
    {"id": "NEG-PART-A", "subject": "主体施工工期"},
    {"id": "NEG-PART-B", "subject": "竣工验收及资料移交"},
    {"id": "NEG-KAOHE", "subject": "考核工期"},
    {"id": "NEG-CEILING", "text": "210"},
    {"id": "NEG-DELETED", "rules": ["VALUE_CONFLICT", "UNIT_CONFLICT", "APPROXIMATE_CONFLICT", "UNIT_FAMILY"], "text": "200"},
    {"id": "NEG-COND", "text": "不得超过2家"},
    {"id": "NEG-RECOMMEND", "text": "40kVA"},
    {"id": "NEG-AC", "subject_contains": "精密空调"},
    {"id": "NEG-BACKUP", "subject_contains": "备用机柜"},
    {"id": "NEG-CABLE", "subject_contains": "光缆"},
    {"id": "NEG-TEMP", "subject": "暂列金额"},
    {"id": "NEG-ALIAS", "subject": "项目名称", "value_exact": "信息化机房改造项目"},
    {"id": "NEG-FORMAT-OK", "rule_id": "FORMAT_PARAGRAPH", "text": "实质性要求和条件"},
    {"id": "NEG-WORKDAY", "text": "工作日"},
]


def _force_font(element, east_asia: str, size_pt: float) -> None:
    element.font.size = Pt(size_pt)
    element.font.name = "Times New Roman"
    rPr = element.element.get_or_add_rPr() if hasattr(element, "element") else element._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    for attr, value in (("w:ascii", "Times New Roman"), ("w:hAnsi", "Times New Roman"), ("w:eastAsia", east_asia), ("w:cs", "Times New Roman")):
        rFonts.set(qn(attr), value)


def _style(style, east_asia: str, size_pt: float, line: float | None) -> None:
    _force_font(style, east_asia, size_pt)
    if line is not None:
        style.paragraph_format.line_spacing = line


def _run(run, east_asia: str, size_pt: float) -> None:
    run.font.size = Pt(size_pt)
    run.font.name = "Times New Roman"
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    for attr, value in (("w:ascii", "Times New Roman"), ("w:hAnsi", "Times New Roman"), ("w:eastAsia", east_asia), ("w:cs", "Times New Roman")):
        rFonts.set(qn(attr), value)


def _prepare(doc: Document) -> None:
    _style(doc.styles["Normal"], "宋体", 12, 1.5)
    _style(doc.styles["Heading 1"], "黑体", 16, None)


def _margins(section, top: float, bottom: float, left: float, right: float) -> None:
    section.top_margin = Cm(top)
    section.bottom_margin = Cm(bottom)
    section.left_margin = Cm(left)
    section.right_margin = Cm(right)
    section.header_distance = Cm(1.5)
    section.footer_distance = Cm(1.5)


def _header(section, text: str) -> None:
    section.header.is_linked_to_previous = False
    paragraph = section.header.paragraphs[0]
    paragraph.text = text


def _footer_page(section) -> None:
    section.footer.is_linked_to_previous = False
    paragraph = section.footer.paragraphs[0]
    paragraph.text = ""
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(end)


def _body(doc: Document, text: str, east="宋体", size=12, line=1.5):
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.line_spacing = line
    run = paragraph.add_run(text)
    _run(run, east, size)
    return paragraph


def _heading(doc: Document, text: str):
    paragraph = doc.add_heading(text, level=1)
    if paragraph.runs:
        _run(paragraph.runs[0], "黑体", 16)
    return paragraph


def _save_parts(path: Path, parts: dict[str, bytes]) -> None:
    temporary = path.with_suffix(".zip-tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for name, data in parts.items():
            package.writestr(name, data)
    temporary.replace(path)


def _read_parts(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path, "r") as package:
        return {name: package.read(name) for name in package.namelist()}


def _enable_numbering(path: Path) -> None:
    parts = _read_parts(path)
    numbering = etree.fromstring(parts["word/numbering.xml"])
    abstract = etree.SubElement(numbering, f"{W}abstractNum")
    abstract.set(f"{W}abstractNumId", "70")
    level = etree.SubElement(abstract, f"{W}lvl")
    level.set(f"{W}ilvl", "0")
    start = etree.SubElement(level, f"{W}start")
    start.set(f"{W}val", "1")
    fmt = etree.SubElement(level, f"{W}numFmt")
    fmt.set(f"{W}val", "chineseCounting")
    text = etree.SubElement(level, f"{W}lvlText")
    text.set(f"{W}val", "第%1章")
    align = etree.SubElement(level, f"{W}lvlJc")
    align.set(f"{W}val", "left")
    num = etree.SubElement(numbering, f"{W}num")
    num.set(f"{W}numId", "70")
    link = etree.SubElement(num, f"{W}abstractNumId")
    link.set(f"{W}val", "70")
    parts["word/numbering.xml"] = etree.tostring(numbering, xml_declaration=True, encoding="UTF-8", standalone=True)

    styles = etree.fromstring(parts["word/styles.xml"])
    for style in styles.findall(f"{W}style"):
        if style.get(f"{W}styleId") != "Heading1":
            continue
        pPr = style.find(f"{W}pPr")
        if pPr is None:
            pPr = etree.SubElement(style, f"{W}pPr")
        numPr = etree.SubElement(pPr, f"{W}numPr")
        ilvl = etree.SubElement(numPr, f"{W}ilvl")
        ilvl.set(f"{W}val", "0")
        numId = etree.SubElement(numPr, f"{W}numId")
        numId.set(f"{W}val", "70")
    parts["word/styles.xml"] = etree.tostring(styles, xml_declaration=True, encoding="UTF-8", standalone=True)
    _save_parts(path, parts)


def _inject_revision_and_comment(path: Path) -> None:
    parts = _read_parts(path)
    root = etree.fromstring(parts["word/document.xml"])
    for node in root.iter(f"{W}t"):
        if node.text and "REV_SLOT" in node.text:
            paragraph = node.getparent()
            while paragraph is not None and etree.QName(paragraph).localname != "p":
                paragraph = paragraph.getparent()
            for child in list(paragraph):
                if etree.QName(child).localname != "pPr":
                    paragraph.remove(child)
            deleted = etree.SubElement(paragraph, f"{W}del")
            deleted.set(f"{W}id", "1")
            deleted.set(f"{W}author", "张工")
            deleted.set(f"{W}date", "2026-03-01T00:00:00Z")
            deleted_run = etree.SubElement(deleted, f"{W}r")
            deleted_text = etree.SubElement(deleted_run, f"{W}delText")
            deleted_text.text = "本项目总工期为200日历天。"
            inserted = etree.SubElement(paragraph, f"{W}ins")
            inserted.set(f"{W}id", "2")
            inserted.set(f"{W}author", "张工")
            inserted.set(f"{W}date", "2026-03-01T00:00:00Z")
            inserted_run = etree.SubElement(inserted, f"{W}r")
            inserted_text = etree.SubElement(inserted_run, f"{W}t")
            inserted_text.text = "本项目总工期为180日历天。"
            break
    for node in root.iter(f"{W}t"):
        if node.text and "计划工期为一百八十日历天" in node.text:
            paragraph = node.getparent()
            while paragraph is not None and etree.QName(paragraph).localname != "p":
                paragraph = paragraph.getparent()
            start = etree.Element(f"{W}commentRangeStart")
            start.set(f"{W}id", "0")
            pPr = paragraph.find(f"{W}pPr")
            if pPr is not None:
                pPr.addnext(start)
            else:
                paragraph.insert(0, start)
            end = etree.SubElement(paragraph, f"{W}commentRangeEnd")
            end.set(f"{W}id", "0")
            marker = etree.SubElement(paragraph, f"{W}r")
            reference = etree.SubElement(marker, f"{W}commentReference")
            reference.set(f"{W}id", "0")
            break
    parts["word/document.xml"] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    comments = etree.Element(f"{W}comments", nsmap={"w": W[1:-1]})
    comment = etree.SubElement(comments, f"{W}comment")
    comment.set(f"{W}id", "0")
    comment.set(f"{W}author", "李工")
    comment.set(f"{W}date", "2026-03-02T00:00:00Z")
    comment_p = etree.SubElement(comment, f"{W}p")
    comment_r = etree.SubElement(comment_p, f"{W}r")
    comment_t = etree.SubElement(comment_r, f"{W}t")
    comment_t.text = "请确认总工期是否与前附表一致。"
    parts["word/comments.xml"] = etree.tostring(comments, xml_declaration=True, encoding="UTF-8", standalone=True)

    rels = etree.fromstring(parts["word/_rels/document.xml.rels"])
    ids = [int(rel.get("Id")[3:]) for rel in rels if rel.get("Id", "").startswith("rId") and rel.get("Id")[3:].isdigit()]
    new_id = f"rId{(max(ids) if ids else 0) + 1}"
    rel = etree.SubElement(rels, f"{REL}Relationship")
    rel.set("Id", new_id)
    rel.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments")
    rel.set("Target", "comments.xml")
    parts["word/_rels/document.xml.rels"] = etree.tostring(rels, xml_declaration=True, encoding="UTF-8", standalone=True)

    types = etree.fromstring(parts["[Content_Types].xml"])
    override = etree.SubElement(types, f"{CT}Override")
    override.set("PartName", "/word/comments.xml")
    override.set("ContentType", "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml")
    parts["[Content_Types].xml"] = etree.tostring(types, xml_declaration=True, encoding="UTF-8", standalone=True)
    _save_parts(path, parts)


def _template(path: Path) -> None:
    doc = Document()
    _prepare(doc)
    section = doc.sections[0]
    _margins(section, 2.5, 2.5, 2.8, 2.6)
    _header(section, "投标文件")
    _footer_page(section)
    cover = doc.add_paragraph()
    cover.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = cover.add_run("投标文件")
    _run(run, "黑体", 22)
    new_section = doc.add_section()
    _margins(new_section, 2.5, 2.5, 2.8, 2.6)
    _header(new_section, "投标文件")
    _footer_page(new_section)
    _body(doc, "（模板说明：正式投标时删除本段）")
    _heading(doc, "投标函")
    _body(doc, SENTENCE_A)
    _body(doc, SENTENCE_B)
    _heading(doc, "法定代表人身份证明")
    _body(doc, "法定代表人身份证明应当附身份证件复印件。")
    _heading(doc, "投标人资格要求")
    _body(doc, "投标人应按招标文件载明的资格条件提供证明材料。")
    _heading(doc, "技术方案")
    _body(doc, "技术方案应覆盖招标文件提出的技术标准和要求。")
    _heading(doc, "报价一览表")
    table = doc.add_table(rows=2, cols=5)
    for index, text in enumerate(["序号", "名称", "规格", "数量", "备注"]):
        table.rows[0].cells[index].text = text
    for index, text in enumerate(["1", "示例设备", "—", "1", "—"]):
        table.rows[1].cells[index].text = text
    doc.save(path)
    _enable_numbering(path)


def _response(path: Path) -> None:
    doc = Document()
    _prepare(doc)
    section = doc.sections[0]
    _margins(section, 1.5, 2.0, 1.5, 1.5)
    _header(section, "投标文件（草稿）")
    section.footer.is_linked_to_previous = False
    section.footer.paragraphs[0].text = "草稿页脚"
    _heading(doc, "投标函")
    _body(doc, SENTENCE_A, east="楷体", size=14, line=1.0)
    _body(doc, SENTENCE_B)
    _body(doc, "投标保证金：【待填写】")
    _body(doc, "授权代表联系电话：__________")
    _body(doc, "（模板说明：正式投标时删除本段）")
    _body(doc, DUPLICATE)
    _body(doc, DUPLICATE)
    fill = doc.add_table(rows=3, cols=2)
    fill.rows[0].cells[0].text = "字段"
    fill.rows[0].cells[1].text = "填写内容"
    fill.rows[1].cells[0].text = "投标人名称"
    fill.rows[1].cells[1].text = ""
    fill.rows[2].cells[0].text = "项目名称"
    fill.rows[2].cells[1].text = PROJECT_A
    _heading(doc, "投标人资格要求")
    _body(doc, "资格证明材料见投标人另行装订的资格文件。")
    _heading(doc, "技术方案")
    _body(doc, "技术方案按招标文件技术标准和要求编制。")
    _heading(doc, "报价一览表")
    table = doc.add_table(rows=2, cols=4)
    for index, text in enumerate(["序号", "名称", "数量", "备注"]):
        table.rows[0].cells[index].text = text
    for index, text in enumerate(["1", "示例设备", "1", "—"]):
        table.rows[1].cells[index].text = text
    doc.save(path)


def _tender(path: Path) -> None:
    doc = Document()
    _prepare(doc)
    _heading(doc, "投标人须知前附表")
    _body(doc, "本招标文件各组成部分的效力顺序如下：")
    for line in (
        "1. 投标人须知前附表",
        "2. 投标人须知正文",
        "3. 合同专用条款",
        "4. 合同通用条款",
        "5. 技术标准和要求",
        "6. 采购清单及预算",
    ):
        _body(doc, line)
    _body(doc, f"项目名称为{PROJECT_A}。")
    _body(doc, "本项目总工期为180日历天。")
    _body(doc, "预算合计金额为人民币1,280.00万元。")
    _body(doc, "暂列金额为人民币50.00万元。")
    _body(doc, "本项目不接受联合体投标。")
    _body(doc, "投标人须具备电子与智能化工程专业承包一级资质。")
    _body(doc, "详见附件1《营业执照》。")
    _body(doc, "详见附件2《电子与智能化工程专业承包资质证书》。")
    _body(doc, "六类网线采购数量为500米。")
    _heading(doc, "投标人须知正文")
    _body(doc, "计划工期为一百八十日历天。")
    _body(doc, "如遇不可抗力，工期可顺延，总工期最长不超过210日历天。")
    _body(doc, "其中主体施工工期150日历天，竣工验收及资料移交30日历天，合计总工期180日历天。")
    _body(doc, "考核工期为180工作日，该口径仅用于内部考核。")
    _body(doc, f"以下简称信息化机房改造项目，不改变“{PROJECT_A}”这一项目名称。")
    _body(doc, "REV_SLOT")
    doc.save(path)
    _inject_revision_and_comment(path)


def _contract(path: Path) -> None:
    doc = Document()
    _prepare(doc)
    _heading(doc, "合同专用条款")
    _body(doc, f"项目名称为{PROJECT_B}。")
    _body(doc, "本项目总工期为150日历天。")
    _body(doc, "本项目接受联合体投标。")
    _body(doc, "若招标人另行书面允许，联合体成员不得超过2家。")
    _body(doc, "投标人须具备电子与智能化工程专业承包二级及以上资质。")
    _body(doc, "服务期为360日历天。")
    doc.save(path)


def _technical(path: Path) -> None:
    doc = Document()
    _prepare(doc)
    _heading(doc, "技术标准和要求")
    for text in (
        "设备供货期为30日历天。",
        "服务期为12个月。",
        "UPS容量不低于30kVA。",
        "UPS容量不低于20kVA。",
        "UPS容量推荐采用40kVA。",
        "交换机交换容量约2Tbps。",
        "精密空调制冷量不低于20kW。",
        "精密空调制冷量为25kW。",
        "光缆长度为2千米。",
    ):
        _body(doc, text)
    table = doc.add_table(rows=4, cols=4)
    for index, text in enumerate(["序号", "名称", "单位", "数量"]):
        table.rows[0].cells[index].text = text
    data = [("1", "机柜", "台", "10"), ("2", "光缆", "千米", "2"), ("3", "备用机柜", "台", "2")]
    for row_index, row in enumerate(data, start=1):
        for col_index, text in enumerate(row):
            table.rows[row_index].cells[col_index].text = text
    doc.save(path)


def _budget(path: Path) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "采购清单及预算"
    sheet.append(["序号", "名称", "单位", "数量", "单价（元）", "合价（元）"])
    sheet.append([1, "机柜", "台", 12, 2000, 24000])
    sheet.append([2, "六类网线", "卷", 500, 10, 5000])
    sheet.append([3, "光缆", "米", 2000, 3, 6000])
    sheet.append([4, "备用机柜", "台", 2, 2000, 4000])
    sheet.append([5, "暂列金额", "项", 1, 500000, 500000])
    sheet.append(["合计", "", "", "", "", 12500000])
    book.save(path)


def _pdf(path: Path, pages: list[list[str]]) -> None:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    writer = canvas.Canvas(str(path), pagesize=(595, 842))
    for lines in pages:
        writer.setFont("STSong-Light", 12)
        y = 800
        for line in lines:
            writer.drawString(72, y, line)
            y -= 22
        writer.showPage()
    writer.save()


def build_corpus(dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    _template(dest / "00_投标文件格式模板.docx")
    _tender(dest / "01_招标文件.docx")
    _response(dest / "02_投标文件格式响应.docx")
    _budget(dest / "03_采购清单及预算.xlsx")
    _contract(dest / "04_合同条款.docx")
    _technical(dest / "05_技术标准和要求.docx")
    _pdf(
        dest / "06_技术标准和要求摘录.pdf",
        [
            ["技术标准和要求", "本页为封面，不设总工期。"],
            ["本项目总工期为90日历天。", "交换机交换容量为1.8Tbps。"],
        ],
    )
    _pdf(dest / "07_附件_营业执照.pdf", [["营业执照", "本页为测试样本，不代表真实证照。"]])
    manifest = {
        "template": "00_投标文件格式模板.docx",
        "conforming": ["02_投标文件格式响应.docx"],
        "rules": "rules.json",
        "documents": [
            {"path": "01_招标文件.docx", "role": "tender", "title": "招标文件"},
            {"path": "02_投标文件格式响应.docx", "role": "conforming", "title": "投标文件格式响应"},
            {"path": "03_采购清单及预算.xlsx", "role": "budget", "title": "采购清单及预算"},
            {"path": "04_合同条款.docx", "role": "contract", "title": "合同条款"},
            {"path": "05_技术标准和要求.docx", "role": "technical", "title": "技术标准和要求"},
            {"path": "06_技术标准和要求摘录.pdf", "role": "technical", "title": "技术标准和要求摘录"},
            {"path": "07_附件_营业执照.pdf", "role": "attachment", "title": "营业执照"},
        ],
    }
    (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    rules = {"external_basis": [{"id": "EXT-GBT50314", "title": "GB/T 50314 智能建筑设计标准"}]}
    (dest / "rules.json").write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
    (dest / "ground_truth.json").write_text(
        json.dumps({"positives": EXPECTED, "negatives": NEGATIVES}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return dest
