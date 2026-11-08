"""DOCX 只读解析：章节、段落、表格、页边距、页眉页脚、批注、修订。"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt

from bid_review.models import (
    DocumentIndex,
    HeaderFooterNode,
    ParagraphNode,
    SectionNode,
    TableNode,
)

W_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def parse_docx(path: str | Path, sha256: str) -> DocumentIndex:
    path = Path(path)
    document = Document(str(path))
    paragraphs: list[ParagraphNode] = []
    tables: list[TableNode] = []
    sections: list[SectionNode] = []
    current_section = ""
    section_stack: list[SectionNode] = []

    # 段落
    for idx, para in enumerate(document.paragraphs):
        text = para.text or ""
        style_name = para.style.name if para.style is not None else ""
        is_heading = style_name.startswith("Heading") or style_name.startswith("标题")
        font_name, font_size, bold = _run_font_info(para)
        line_spacing = _line_spacing(para)
        alignment = _alignment_label(para.alignment)
        numbering_id = _numbering_id(para)

        if is_heading and text.strip():
            level = _heading_level(style_name)
            node = SectionNode(name=text.strip(), level=level, start_paragraph=idx)
            if section_stack and section_stack[-1].end_paragraph is None:
                if section_stack[-1].level >= level:
                    section_stack[-1].end_paragraph = idx - 1
                    section_stack.pop()
            sections.append(node)
            section_stack.append(node)
            current_section = text.strip()

        has_revision = _para_has_revision(para)
        paragraphs.append(
            ParagraphNode(
                index=idx,
                text=text,
                style=style_name,
                section=current_section,
                font_name=font_name,
                font_size_pt=font_size,
                bold=bold,
                line_spacing=line_spacing,
                alignment=alignment,
                is_heading=is_heading,
                numbering_id=numbering_id,
                has_revision=has_revision,
            )
        )

    for s in section_stack:
        if s.end_paragraph is None:
            s.end_paragraph = max((p.index for p in paragraphs), default=0)

    # 表格（python-docx 表格与段落交错，这里按文档顺序索引）
    for t_idx, table in enumerate(document.tables):
        rows: list[list[str]] = []
        for row in table.rows:
            rows.append([cell.text.strip() for cell in row.cells])
        # 用首行/邻近段落猜测所属章节
        section_name = _guess_table_section(paragraphs, t_idx)
        tables.append(
            TableNode(
                index=t_idx,
                rows=rows,
                section=section_name,
            )
        )

    headers_footers = _extract_headers_footers(document)
    page_margins, section_count = _extract_margins(document)
    comments, revisions = _extract_comments_and_revisions(path)

    raw_parts = [p.text for p in paragraphs if p.text.strip()]
    for t in tables:
        for row in t.rows:
            raw_parts.extend(c for c in row if c)
    raw_text = "\n".join(raw_parts)

    return DocumentIndex(
        path=str(path.resolve()),
        filename=path.name,
        file_type="docx",
        sha256=sha256,
        paragraphs=paragraphs,
        tables=tables,
        sections=sections,
        headers_footers=headers_footers,
        page_margins=page_margins,
        section_count=section_count,
        comments=comments,
        revisions=revisions,
        raw_text=raw_text,
    )


def _run_font_info(para) -> tuple[str, float | None, bool | None]:
    names: list[str] = []
    sizes: list[float] = []
    bolds: list[bool] = []
    for run in para.runs:
        # 东亚字体优先
        rPr = run._element.rPr
        if rPr is not None:
            rFonts = rPr.rFonts
            if rFonts is not None:
                east = rFonts.get(qn("w:eastAsia"))
                ascii_f = rFonts.get(qn("w:ascii"))
                if east:
                    names.append(east)
                elif ascii_f:
                    names.append(ascii_f)
                elif run.font.name:
                    names.append(run.font.name)
            elif run.font.name:
                names.append(run.font.name)
        elif run.font.name:
            names.append(run.font.name)
        if run.font.size is not None:
            sizes.append(round(run.font.size.pt, 2))
        if run.font.bold is not None:
            bolds.append(bool(run.font.bold))
    font_name = names[0] if names else ""
    font_size = sizes[0] if sizes else None
    bold = bolds[0] if bolds else None
    return font_name, font_size, bold


def _line_spacing(para) -> float | None:
    pf = para.paragraph_format
    if pf.line_spacing is None:
        return None
    # 可能是浮点倍数或长度
    value = pf.line_spacing
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value.pt)  # type: ignore[attr-defined]
    except Exception:
        return None


def _alignment_label(alignment) -> str:
    mapping = {
        WD_ALIGN_PARAGRAPH.LEFT: "left",
        WD_ALIGN_PARAGRAPH.CENTER: "center",
        WD_ALIGN_PARAGRAPH.RIGHT: "right",
        WD_ALIGN_PARAGRAPH.JUSTIFY: "justify",
    }
    return mapping.get(alignment, "")


def _numbering_id(para) -> str:
    pPr = para._element.pPr
    if pPr is None:
        return ""
    numPr = pPr.numPr
    if numPr is None:
        return ""
    numId = numPr.numId
    ilvl = numPr.ilvl
    nid = numId.val if numId is not None else ""
    level = ilvl.val if ilvl is not None else ""
    return f"{nid}:{level}"


def _heading_level(style_name: str) -> int:
    # 优先匹配末尾数字，避免误伤
    import re

    m = re.search(r"(\d+)\s*$", style_name) or re.search(r"(\d+)", style_name)
    if m:
        return int(m.group(1))
    return 1


def _para_has_revision(para) -> bool:
    xml = para._element.xml
    return any(tag in xml for tag in ("w:ins", "w:del", "w:rPrChange", "w:pPrChange"))


def _guess_table_section(paragraphs: list[ParagraphNode], table_index: int) -> str:
    # 简单启发式：取最后一个有章节名的段落
    for p in reversed(paragraphs):
        if p.section:
            return p.section
    return f"表格区域#{table_index}"


def _extract_headers_footers(document: Document) -> list[HeaderFooterNode]:
    nodes: list[HeaderFooterNode] = []
    for s_idx, section in enumerate(document.sections):
        try:
            nodes.append(
                HeaderFooterNode(
                    kind="header",
                    section_index=s_idx,
                    text=(section.header.paragraphs[0].text if section.header.paragraphs else ""),
                )
            )
        except Exception:
            pass
        try:
            nodes.append(
                HeaderFooterNode(
                    kind="footer",
                    section_index=s_idx,
                    text=(section.footer.paragraphs[0].text if section.footer.paragraphs else ""),
                )
            )
        except Exception:
            pass
    return nodes


def _extract_margins(document: Document) -> tuple[list[dict], int]:
    margins: list[dict] = []
    for s_idx, section in enumerate(document.sections):
        def cm(length) -> float | None:
            if length is None:
                return None
            return round(length.cm, 3)

        margins.append(
            {
                "section_index": s_idx,
                "top_cm": cm(section.top_margin),
                "bottom_cm": cm(section.bottom_margin),
                "left_cm": cm(section.left_margin),
                "right_cm": cm(section.right_margin),
                "page_width_cm": cm(section.page_width),
                "page_height_cm": cm(section.page_height),
            }
        )
    return margins, len(document.sections)


def _extract_comments_and_revisions(path: Path) -> tuple[list[str], list[str]]:
    comments: list[str] = []
    revisions: list[str] = []
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = set(zf.namelist())
            if "word/comments.xml" in names:
                root = ET.fromstring(zf.read("word/comments.xml"))
                for c in root.findall(".//w:comment", W_NS):
                    texts = [t.text or "" for t in c.findall(".//w:t", W_NS)]
                    comments.append("".join(texts).strip())
            if "word/document.xml" in names:
                xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
                if "<w:ins" in xml or "<w:del" in xml:
                    # 抽取部分修订文本
                    root = ET.fromstring(xml.encode("utf-8"))
                    for ins in root.findall(".//w:ins", W_NS):
                        texts = [t.text or "" for t in ins.findall(".//w:t", W_NS)]
                        joined = "".join(texts).strip()
                        if joined:
                            revisions.append(f"插入:{joined[:120]}")
                    for dele in root.findall(".//w:del", W_NS):
                        texts = [t.text or "" for t in dele.findall(".//w:delText", W_NS)]
                        if not texts:
                            texts = [t.text or "" for t in dele.findall(".//w:t", W_NS)]
                        joined = "".join(texts).strip()
                        if joined:
                            revisions.append(f"删除:{joined[:120]}")
    except Exception:
        pass
    return comments, revisions
