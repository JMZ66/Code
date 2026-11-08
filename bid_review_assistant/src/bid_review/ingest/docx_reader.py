"""只读 DOCX 解析：段落、表格、格式、修订、批注、页眉页脚。"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Pt
from lxml import etree

from bid_review.integrity import sha256_file
from bid_review.models import Block, DocumentIndex, Location, TableInfo

W_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _line_spacing(paragraph) -> float | None:
    pf = paragraph.paragraph_format
    if pf.line_spacing is None:
        return None
    rule = pf.line_spacing_rule
    if rule == WD_LINE_SPACING.MULTIPLE or rule is None:
        try:
            return float(pf.line_spacing)
        except Exception:
            return None
    if rule == WD_LINE_SPACING.EXACTLY and isinstance(pf.line_spacing, Pt):
        return round(pf.line_spacing.pt, 2)
    return None


def _font_name_from_run(run) -> str:
    name = run.font.name
    if name:
        return name
    rPr = run._element.find(qn("w:rPr"))
    if rPr is not None:
        rFonts = rPr.find(qn("w:rFonts"))
        if rFonts is not None:
            return (
                rFonts.get(qn("w:eastAsia"))
                or rFonts.get(qn("w:ascii"))
                or rFonts.get(qn("w:hAnsi"))
                or ""
            )
    return ""


def _current_section(text: str, current: str) -> str:
    t = text.strip()
    if not t:
        return current
    heading_prefixes = (
        "第",
        "一、",
        "二、",
        "三、",
        "四、",
        "五、",
        "六、",
        "七、",
        "八、",
        "九、",
        "十、",
        "附件",
        "附录",
        "目录",
    )
    if any(t.startswith(p) for p in heading_prefixes) and len(t) < 80:
        return t
    return current


def _xml_root(path: Path, part: str = "word/document.xml"):
    with zipfile.ZipFile(path, "r") as zf:
        return etree.fromstring(zf.read(part))


def _has_revisions(path: Path) -> bool:
    try:
        root = _xml_root(path)
        for tag in ("ins", "del", "moveFrom", "moveTo"):
            if root.xpath(f".//w:{tag}", namespaces=W_NS):
                return True
        return False
    except Exception:
        return False


def _has_comments(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path, "r") as zf:
            return "word/comments.xml" in zf.namelist()
    except Exception:
        return False


def _read_comments(path: Path) -> list[str]:
    comments: list[str] = []
    try:
        with zipfile.ZipFile(path, "r") as zf:
            if "word/comments.xml" not in zf.namelist():
                return comments
            root = etree.fromstring(zf.read("word/comments.xml"))
        for c in root.xpath("//w:comment", namespaces=W_NS):
            texts = c.xpath(".//w:t/text()", namespaces=W_NS)
            comments.append("".join(texts).strip())
    except Exception:
        pass
    return comments


def _header_footer_texts(doc: Document) -> tuple[list[str], list[str]]:
    headers: list[str] = []
    footers: list[str] = []
    for section in doc.sections:
        for hdr in (section.header, section.first_page_header, section.even_page_header):
            try:
                t = "\n".join(p.text for p in hdr.paragraphs if p.text.strip())
                if t and t not in headers:
                    headers.append(t)
            except Exception:
                pass
        for ftr in (section.footer, section.first_page_footer, section.even_page_footer):
            try:
                t = "\n".join(p.text for p in ftr.paragraphs if p.text.strip())
                if t and t not in footers:
                    footers.append(t)
            except Exception:
                pass
    return headers, footers


def _margins(doc: Document) -> dict[str, float]:
    if not doc.sections:
        return {}
    s = doc.sections[0]
    out: dict[str, float] = {}
    for key, attr in (
        ("top", "top_margin"),
        ("bottom", "bottom_margin"),
        ("left", "left_margin"),
        ("right", "right_margin"),
    ):
        try:
            val = getattr(s, attr)
            if val is not None:
                out[key] = round(val.cm, 3)
        except Exception:
            pass
    return out


def _numbering(paragraph) -> str:
    try:
        pPr = paragraph._p.pPr
        if pPr is None or pPr.numPr is None:
            return ""
        numId = pPr.numPr.numId
        ilvl = pPr.numPr.ilvl
        nid = numId.val if numId is not None else ""
        lvl = ilvl.val if ilvl is not None else ""
        return f"numId={nid};ilvl={lvl}"
    except Exception:
        return ""


def read_docx(path: str | Path) -> DocumentIndex:
    p = Path(path).resolve()
    doc = Document(str(p))
    filename = p.name
    blocks: list[Block] = []
    tables: list[TableInfo] = []
    sections: list[str] = []
    current_section = "正文"

    # 段落
    for para_idx, para in enumerate(doc.paragraphs):
        text = para.text or ""
        new_section = _current_section(text, current_section)
        if new_section != current_section and text.strip():
            current_section = new_section
            if current_section not in sections:
                sections.append(current_section)

        font_name = ""
        font_size = None
        bold = None
        if para.runs:
            font_name = _font_name_from_run(para.runs[0])
            try:
                if para.runs[0].font.size is not None:
                    font_size = round(para.runs[0].font.size.pt, 2)
            except Exception:
                font_size = None
            bold = para.runs[0].bold

        loc = Location(
            filename=filename,
            file_type="docx",
            section=current_section,
            paragraph_index=para_idx,
            xpath_hint=f"body/p[{para_idx}]",
            excerpt=text[:240],
        )
        blocks.append(
            Block(
                block_id=f"{filename}#p{para_idx}",
                kind="paragraph",
                text=text,
                location=loc,
                style=(para.style.name if para.style else "") or "",
                font_name=font_name or "",
                font_size_pt=font_size,
                bold=bold,
                line_spacing=_line_spacing(para),
                numbering=_numbering(para),
            )
        )

    # 表格
    for table_counter, table in enumerate(doc.tables):
        rows_data: list[list[str]] = []
        for ri, row in enumerate(table.rows):
            row_cells: list[str] = []
            for ci, cell in enumerate(row.cells):
                cell_text = (cell.text or "").strip()
                row_cells.append(cell_text)
                loc = Location(
                    filename=filename,
                    file_type="docx",
                    section=current_section,
                    table_index=table_counter,
                    row_index=ri,
                    cell_index=ci,
                    xpath_hint=f"body/tbl[{table_counter}]/tr[{ri}]/tc[{ci}]",
                    excerpt=cell_text[:240],
                )
                blocks.append(
                    Block(
                        block_id=f"{filename}#t{table_counter}r{ri}c{ci}",
                        kind="table_cell",
                        text=cell_text,
                        location=loc,
                    )
                )
            rows_data.append(row_cells)
        n_cols = max((len(r) for r in rows_data), default=0)
        tables.append(
            TableInfo(
                table_id=f"{filename}#tbl{table_counter}",
                location=Location(
                    filename=filename,
                    file_type="docx",
                    section=current_section,
                    table_index=table_counter,
                    xpath_hint=f"body/tbl[{table_counter}]",
                ),
                rows=rows_data,
                n_rows=len(rows_data),
                n_cols=n_cols,
            )
        )

    headers, footers = _header_footer_texts(doc)
    for hi, h in enumerate(headers):
        blocks.append(
            Block(
                block_id=f"{filename}#hdr{hi}",
                kind="header",
                text=h,
                location=Location(
                    filename=filename,
                    file_type="docx",
                    section="页眉",
                    xpath_hint=f"header[{hi}]",
                    excerpt=h[:240],
                ),
            )
        )
    for fi, f in enumerate(footers):
        blocks.append(
            Block(
                block_id=f"{filename}#ftr{fi}",
                kind="footer",
                text=f,
                location=Location(
                    filename=filename,
                    file_type="docx",
                    section="页脚",
                    xpath_hint=f"footer[{fi}]",
                    excerpt=f[:240],
                ),
            )
        )

    for ci, ctext in enumerate(_read_comments(p)):
        blocks.append(
            Block(
                block_id=f"{filename}#cmt{ci}",
                kind="comment",
                text=ctext,
                location=Location(
                    filename=filename,
                    file_type="docx",
                    section="批注",
                    xpath_hint=f"comment[{ci}]",
                    excerpt=ctext[:240],
                ),
            )
        )

    return DocumentIndex(
        path=str(p),
        filename=filename,
        file_type="docx",
        sha256=sha256_file(p),
        size_bytes=p.stat().st_size,
        sections=sections or ["正文"],
        blocks=blocks,
        tables=tables,
        has_revisions=_has_revisions(p),
        has_comments=_has_comments(p),
        margins_cm=_margins(doc),
        headers=headers,
        footers=footers,
        section_count=len(doc.sections),
        metadata={
            "paragraph_count": len(doc.paragraphs),
            "table_count": len(doc.tables),
        },
    )


def extract_format_profile(path: str | Path) -> dict[str, Any]:
    """从模板 DOCX 抽取可比较的格式画像（只读）。"""
    idx = read_docx(path)
    fonts: dict[str, int] = {}
    sizes: dict[float, int] = {}
    styles: dict[str, int] = {}
    for b in idx.blocks:
        if b.kind != "paragraph" or not b.text.strip():
            continue
        if b.font_name:
            fonts[b.font_name] = fonts.get(b.font_name, 0) + 1
        if b.font_size_pt is not None:
            sizes[b.font_size_pt] = sizes.get(b.font_size_pt, 0) + 1
        if b.style:
            styles[b.style] = styles.get(b.style, 0) + 1
    dominant_font = max(fonts, key=fonts.get) if fonts else ""
    dominant_size = max(sizes, key=sizes.get) if sizes else None
    return {
        "margins_cm": idx.margins_cm,
        "section_count": idx.section_count,
        "dominant_font": dominant_font,
        "dominant_size_pt": dominant_size,
        "fonts": fonts,
        "sizes": sizes,
        "styles": styles,
        "table_shapes": [(t.n_rows, t.n_cols) for t in idx.tables],
        "headers": idx.headers,
        "footers": idx.footers,
    }
