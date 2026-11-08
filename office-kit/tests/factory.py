"""Synthetic OOXML and workbooks. Nothing here is a real tender."""

from __future__ import annotations

import zipfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_zip(path: Path, parts: dict[str, str | bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in parts.items():
            data = payload if isinstance(payload, bytes) else payload.encode("utf-8")
            archive.writestr(name, data)


def _content_types(parts: dict[str, str]) -> str:
    overrides = []
    defaults = {
        "rels": "application/vnd.openxmlformats-package.relationships+xml",
        "xml": "application/xml",
    }
    types = {
        "word/document.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        "word/styles.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml",
        "word/numbering.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml",
        "word/comments.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml",
        "word/header1.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml",
        "word/header2.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml",
        "word/footer1.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml",
        "word/footer2.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml",
        "word/theme/theme1.xml": "application/vnd.openxmlformats-officedocument.theme+xml",
    }
    for name, content_type in types.items():
        if name in parts:
            overrides.append(f'<Override PartName="/{name}" ContentType="{content_type}"/>')
    body = "".join(f'<Default Extension="{ext}" ContentType="{value}"/>' for ext, value in defaults.items())
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="{CT}">{body}{"".join(overrides)}</Types>'


def complex_docx(path: Path) -> Path:
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W}" xmlns:r="{R}">
  <w:body>
    <w:p><w:r><w:t>封面标题</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>投标人须知</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>项目概况</w:t></w:r></w:p>
    <w:p><w:pPr><w:numPr><w:ilvl w:val="2"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>条款甲</w:t></w:r></w:p>
    <w:p><w:pPr><w:numPr><w:ilvl w:val="2"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>条款乙</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>项目范围</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/><w:numPr><w:ilvl w:val="0"/><w:numId w:val="0"/></w:numPr></w:pPr><w:r><w:t>无编号标题</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>合同条款</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>工期</w:t></w:r></w:p>
    <w:p><w:pPr><w:numPr><w:ilvl w:val="2"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>再次分项</w:t></w:r></w:p>
    <w:p><w:r><w:t>默认字体</w:t></w:r><w:r><w:rPr><w:rFonts w:eastAsia="黑体"/></w:rPr><w:t>黑体字</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Emph"/></w:pPr><w:r><w:t>仿宋强调</w:t></w:r></w:p>
    <w:p><w:pPr><w:rPr><w:rFonts w:eastAsia="楷体"/></w:rPr></w:pPr><w:r><w:t>楷体段</w:t></w:r></w:p>
    <w:p>
      <w:commentRangeStart w:id="1"/>
      <w:r><w:t>被批注的句子</w:t></w:r>
      <w:commentRangeEnd w:id="1"/>
      <w:r><w:commentReference w:id="1"/></w:r>
    </w:p>
    <w:p>
      <w:pPr>
        <w:pPrChange w:id="15" w:author="王五" w:date="2026-05-03T00:00:00Z"><w:pPr><w:jc w:val="center"/></w:pPr></w:pPrChange>
        <w:jc w:val="both"/>
      </w:pPr>
      <w:r><w:t>保留</w:t></w:r>
      <w:ins w:id="10" w:author="王五" w:date="2026-05-01T00:00:00Z"><w:r><w:t>新增文字</w:t></w:r></w:ins>
      <w:del w:id="11" w:author="王五" w:date="2026-05-01T00:00:00Z"><w:r><w:delText>删除文字</w:delText></w:r></w:del>
      <w:moveFrom w:id="12" w:author="王五" w:date="2026-05-02T00:00:00Z"><w:r><w:t>移出</w:t></w:r></w:moveFrom>
      <w:moveTo w:id="13" w:author="王五" w:date="2026-05-02T00:00:00Z"><w:r><w:t>移入</w:t></w:r></w:moveTo>
      <w:r>
        <w:rPr><w:b/><w:rPrChange w:id="14" w:author="王五" w:date="2026-05-03T00:00:00Z"><w:rPr><w:i/></w:rPr></w:rPrChange></w:rPr>
        <w:t>格式变更</w:t>
      </w:r>
    </w:p>
    <w:p>
      <w:r><w:fldChar w:fldCharType="begin"/></w:r>
      <w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>
      <w:r><w:fldChar w:fldCharType="separate"/></w:r>
      <w:r><w:t>3</w:t></w:r>
      <w:r><w:fldChar w:fldCharType="end"/></w:r>
    </w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:tcPr><w:gridSpan w:val="2"/><w:vMerge w:val="restart"/></w:tcPr><w:p><w:r><w:t>合并标题</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>右</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:tcPr><w:gridSpan w:val="2"/><w:vMerge/></w:tcPr><w:p><w:r><w:t></w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>右下</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc>
          <w:tcPr><w:gridSpan w:val="3"/></w:tcPr>
          <w:p><w:r><w:t>外层</w:t></w:r></w:p>
          <w:tbl><w:tr><w:tc><w:p><w:r><w:t>内嵌单元格</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
        </w:tc>
      </w:tr>
    </w:tbl>
    <w:p>
      <w:pPr>
        <w:sectPr>
          <w:headerReference w:type="default" r:id="rId5"/>
          <w:footerReference w:type="default" r:id="rId6"/>
          <w:pgSz w:w="11906" w:h="16838"/>
          <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1800" w:header="720" w:footer="720"/>
        </w:sectPr>
      </w:pPr>
      <w:r><w:t>分节处</w:t></w:r>
    </w:p>
    <w:p><w:r><w:t>第二节正文</w:t></w:r></w:p>
    <w:sectPr>
      <w:headerReference w:type="default" r:id="rId7"/>
      <w:footerReference w:type="default" r:id="rId8"/>
      <w:pgSz w:w="11906" w:h="16838"/>
    </w:sectPr>
  </w:body>
</w:document>
"""
    styles = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W}">
  <w:docDefaults><w:rPrDefault><w:rPr>
    <w:rFonts w:asciiTheme="minorHAnsi" w:hAnsiTheme="minorHAnsi" w:eastAsiaTheme="minorEastAsia"/>
    <w:sz w:val="24"/>
  </w:rPr></w:rPrDefault></w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:outlineLvl w:val="0"/><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>
    <w:rPr><w:b/><w:sz w:val="32"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading2">
    <w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:outlineLvl w:val="1"/><w:numPr><w:ilvl w:val="1"/><w:numId w:val="1"/></w:numPr></w:pPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Emph">
    <w:name w:val="Emphasis"/><w:basedOn w:val="Normal"/>
    <w:rPr><w:rFonts w:eastAsia="仿宋"/></w:rPr>
  </w:style>
</w:styles>
"""
    numbering = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="{W}">
  <w:abstractNum w:abstractNumId="0">
    <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="chineseCounting"/><w:lvlText w:val="第%1章"/><w:suff w:val="space"/></w:lvl>
    <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:isLgl/><w:lvlText w:val="%1.%2"/><w:suff w:val="space"/></w:lvl>
    <w:lvl w:ilvl="2"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="（%3）"/><w:suff w:val="space"/></w:lvl>
  </w:abstractNum>
  <w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
</w:numbering>
"""
    theme = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="{A}" name="Office"><a:themeElements><a:fontScheme name="Office">
  <a:majorFont><a:latin typeface="等线 Light"/><a:ea typeface="等线 Light"/><a:cs typeface=""/></a:majorFont>
  <a:minorFont><a:latin typeface="Calibri"/><a:ea typeface="等线"/><a:cs typeface=""/></a:minorFont>
</a:fontScheme></a:themeElements></a:theme>
"""
    comments = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:w="{W}"><w:comment w:id="1" w:author="李四" w:date="2026-04-01T00:00:00Z" w:initials="李">
  <w:p><w:r><w:t>请确认参数</w:t></w:r></w:p>
</w:comment></w:comments>
"""
    parts = {
        "word/document.xml": document,
        "word/styles.xml": styles,
        "word/numbering.xml": numbering,
        "word/theme/theme1.xml": theme,
        "word/comments.xml": comments,
        "word/header1.xml": _story("hdr", "页眉甲"),
        "word/header2.xml": _story("hdr", "页眉乙"),
        "word/footer1.xml": _story("ftr", "页脚甲"),
        "word/footer2.xml": _story("ftr", "页脚乙"),
        "word/_rels/document.xml.rels": f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{PKG}">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>
  <Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>
  <Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
  <Relationship Id="rId6" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
  <Relationship Id="rId7" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header2.xml"/>
  <Relationship Id="rId8" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer2.xml"/>
</Relationships>
""",
        "_rels/.rels": f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{PKG}">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
""",
    }
    parts["[Content_Types].xml"] = _content_types(parts)
    write_zip(path, parts)
    return path


def _story(tag: str, text: str) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:{tag} xmlns:w="{W}"><w:p><w:r><w:t>{esc(text)}</w:t></w:r></w:p></w:{tag}>'
    )


def simple_docx(path: Path, blocks: list[tuple]) -> Path:
    """blocks are ('p', style_or_None, text) or ('tbl', rows)."""

    body = []
    for block in blocks:
        if block[0] == "p":
            _kind, style, text = block
            ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
            body.append(f"<w:p>{ppr}<w:r><w:t>{esc(text)}</w:t></w:r></w:p>")
        else:
            rows = []
            for row in block[1]:
                cells = "".join(
                    f"<w:tc><w:p><w:r><w:t>{esc(str(value))}</w:t></w:r></w:p></w:tc>" for value in row
                )
                rows.append(f"<w:tr>{cells}</w:tr>")
            body.append(f"<w:tbl>{''.join(rows)}</w:tbl>")
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>{"".join(body)}'
        f'<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>'
    )
    styles = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W}">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>
    <w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>
</w:styles>"""
    parts = {
        "word/document.xml": document,
        "word/styles.xml": styles,
        "word/_rels/document.xml.rels": f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{PKG}">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>""",
        "_rels/.rels": f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{PKG}">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
    }
    parts["[Content_Types].xml"] = _content_types(parts)
    write_zip(path, parts)
    return path


def bill_xlsx(path: Path) -> Path:
    book = Workbook()
    sheet = book.active
    sheet.title = "清单"
    sheet.merge_cells("A1:D1")
    sheet["A1"] = "工程量清单"
    sheet["A1"].font = Font(name="宋体", bold=True, size=14)
    headers = ["名称", "数量", "单价", "合价"]
    for column, value in enumerate(headers, start=1):
        sheet.cell(2, column, value)
    sheet["A3"] = "设备"
    sheet["B3"] = 2
    sheet["C3"] = 100
    sheet["D3"] = 250
    sheet["C3"].number_format = "¥#,##0.00"
    sheet["C3"].font = Font(name="宋体", bold=True)
    sheet["C3"].fill = PatternFill("solid", fgColor="FFFF00")
    sheet["A4"] = "安装"
    sheet["B4"] = 1
    sheet["C4"] = 50
    sheet["D4"] = 50
    sheet["A5"] = "合计"
    sheet["D5"] = 300
    sheet["A7"] = "投标总价"
    sheet["B7"] = 1300000
    sheet["A1"].comment = Comment("请复核合价", "审核人")
    sheet.row_dimensions[4].hidden = True
    sheet.column_dimensions["E"].hidden = True
    sheet["E3"] = "内部备注"
    validation = DataValidation(type="list", formula1='"甲,乙,丙"', allow_blank=True, prompt="选择类别", promptTitle="类别")
    validation.add("F3:F5")
    sheet.add_data_validation(validation)
    sheet["F3"] = "甲"
    sheet["G3"] = "=B3*C3"
    hidden = book.create_sheet("内部测算")
    hidden.sheet_state = "hidden"
    hidden["A1"] = "仅供内部"
    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(path)
    _set_cached_formula(path, "G3", "999")
    _add_threaded_comment(path)
    _add_shared_pair(path)
    return path


def _set_cached_formula(path: Path, coordinate: str, cached: str) -> None:
    import io

    from lxml import etree

    with zipfile.ZipFile(path, "r") as archive:
        names = archive.namelist()
        payload = {name: archive.read(name) for name in names}
    root = etree.fromstring(payload["xl/worksheets/sheet1.xml"])
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    for cell in root.xpath(f'//m:c[@r="{coordinate}"]', namespaces=ns):
        value = cell.find("m:v", ns)
        if value is None:
            value = etree.SubElement(cell, "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
        value.text = cached
    payload["xl/worksheets/sheet1.xml"] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in payload.items():
            archive.writestr(name, data)


def _add_threaded_comment(path: Path) -> None:
    from lxml import etree

    tc = "http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments"
    comment = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<ThreadedComments xmlns="{tc}">'
        f'<threadedComment ref="A3" personId="p1" id="c1">数量待确认</threadedComment>'
        f"</ThreadedComments>"
    )
    people = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<personList xmlns="{tc}"><person displayName="造价员" id="p1"/></personList>'
    )
    with zipfile.ZipFile(path, "r") as archive:
        payload = {name: archive.read(name) for name in archive.namelist()}
    rels_name = "xl/worksheets/_rels/sheet1.xml.rels"
    if rels_name in payload:
        rels = etree.fromstring(payload[rels_name])
    else:
        rels = etree.Element("{http://schemas.openxmlformats.org/package/2006/relationships}Relationships")
    rel = etree.SubElement(rels, "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship")
    rel.set("Id", "rIdThreaded")
    rel.set("Type", "http://schemas.microsoft.com/office/2017/10/relationships/threadedComment")
    rel.set("Target", "../threadedComments/threadedComment1.xml")
    payload["xl/worksheets/_rels/sheet1.xml.rels"] = etree.tostring(rels, xml_declaration=True, encoding="UTF-8", standalone=True)
    payload["xl/threadedComments/threadedComment1.xml"] = comment.encode("utf-8")
    payload["xl/persons/person.xml"] = people.encode("utf-8")
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in payload.items():
            archive.writestr(name, data)


def _add_shared_pair(path: Path) -> None:
    """Two cells share one string so an edit must not rewrite the shared table."""

    from lxml import etree

    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    with zipfile.ZipFile(path, "r") as archive:
        payload = {name: archive.read(name) for name in archive.namelist()}
    sheet = etree.fromstring(payload["xl/worksheets/sheet1.xml"])
    row = sheet.find(f"{{{ns}}}sheetData/{{{ns}}}row[@r='3']")
    for ref in ("H3", "I3"):
        cell = etree.SubElement(row, f"{{{ns}}}c")
        cell.set("r", ref)
        cell.set("t", "s")
        value = etree.SubElement(cell, f"{{{ns}}}v")
        value.text = "0"
    payload["xl/worksheets/sheet1.xml"] = etree.tostring(sheet, xml_declaration=True, encoding="UTF-8", standalone=True)
    payload["xl/sharedStrings.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="{ns}" count="2" uniqueCount="1"><si><t>共用标签</t></si></sst>'
    ).encode("utf-8")
    rels = etree.fromstring(payload["xl/_rels/workbook.xml.rels"])
    rel = etree.SubElement(rels, f"{{{rel_ns}}}Relationship")
    rel.set("Id", "rIdSharedStrings")
    rel.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings")
    rel.set("Target", "sharedStrings.xml")
    payload["xl/_rels/workbook.xml.rels"] = etree.tostring(rels, xml_declaration=True, encoding="UTF-8", standalone=True)
    types = payload["[Content_Types].xml"].decode("utf-8")
    override = '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
    if override not in types:
        types = types.replace("</Types>", override + "</Types>")
    payload["[Content_Types].xml"] = types.encode("utf-8")
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in payload.items():
            archive.writestr(name, data)
