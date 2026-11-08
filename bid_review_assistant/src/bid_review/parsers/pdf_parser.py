"""PDF 只读解析：按页抽取文本并保留页码。"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from bid_review.models import DocumentIndex, ParagraphNode, SectionNode


def parse_pdf(path: str | Path, sha256: str) -> DocumentIndex:
    path = Path(path)
    reader = PdfReader(str(path))
    pages: list[str] = []
    paragraphs: list[ParagraphNode] = []
    sections: list[SectionNode] = []
    para_idx = 0
    current_section = ""

    for page_no, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(text)
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            # 简单章节：以“第X章/节”或全大写短行作为章节
            if _looks_like_heading(stripped):
                current_section = stripped[:80]
                sections.append(
                    SectionNode(
                        name=current_section,
                        level=1,
                        start_paragraph=para_idx,
                    )
                )
            paragraphs.append(
                ParagraphNode(
                    index=para_idx,
                    text=stripped,
                    section=current_section or f"第{page_no}页",
                    ooxml_part=f"pdf:page:{page_no}",
                )
            )
            para_idx += 1

    raw_text = "\n".join(pages)
    return DocumentIndex(
        path=str(path.resolve()),
        filename=path.name,
        file_type="pdf",
        sha256=sha256,
        paragraphs=paragraphs,
        sections=sections,
        pdf_pages=pages,
        raw_text=raw_text,
    )


def _looks_like_heading(text: str) -> bool:
    if len(text) > 40:
        return False
    markers = ("第", "章", "节", "附件", "合同", "技术", "招标")
    return any(m in text for m in markers) and len(text) < 30
