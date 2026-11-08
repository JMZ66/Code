"""Read-only PDF text layer. No OCR and no network."""

from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from bidreview.models import Document, Location, Paragraph, SectionInfo

_CHAPTER = re.compile(r"^第[一二三四五六七八九十百零〇0-9]+[章节篇]")


def read_pdf(path: Path, *, role: str, title: str, sha256: str) -> Document:
    doc = Document(
        path=str(path),
        file_name=path.name,
        role=role,
        title=title or path.stem,
        sha256=sha256,
        kind="pdf",
    )
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            doc.unreadable = "PDF 已加密。本工具不尝试解密，请人工阅读。"
            return doc
        doc.page_count = len(reader.pages)
        current = "（文首）"
        first_used = False
        p_index = 0
        for page_no, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # a single bad page should not abort the file
                doc.paragraphs.append(
                    _para(path, sha256, p_index, page_no, current, f"（第{page_no}页文本提取失败：{exc}）")
                )
                p_index += 1
                continue
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if not lines and text.strip():
                lines = [text.strip()]
            for line in lines:
                level = None
                if not first_used and len(line) <= 40:
                    current = line
                    level = 1
                    first_used = True
                elif _CHAPTER.match(line):
                    current = line
                    level = 1
                paragraph = _para(path, sha256, p_index, page_no, current, line)
                paragraph.heading_level = level
                doc.paragraphs.append(paragraph)
                if level:
                    doc.headings.append((level, line, paragraph.location))
                p_index += 1
        doc.sections.append(SectionInfo(index=0, header_text="", footer_text=""))
        return doc
    except PdfReadError as exc:
        doc.unreadable = f"PDF 无法读取：{exc}"
        return doc
    except Exception as exc:
        doc.unreadable = f"PDF 无法读取：{exc}"
        return doc


def _para(path: Path, sha256: str, index: int, page_no: int, section: str, text: str) -> Paragraph:
    loc = Location(
        file_name=path.name,
        file_path=str(path),
        sha256=sha256,
        kind="pdf",
        part=f"page/{page_no}",
        xml_path=f"page[{page_no}]/line[{index}]",
        section_title=section,
        paragraph_index=index,
        pdf_page=page_no,
    )
    return Paragraph(text=text, accepted_text=text, location=loc, section_title=section, section_index=0)
