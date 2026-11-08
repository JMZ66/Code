"""只读 PDF 解析：按页抽取文本并保留页码。"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from bid_review.integrity import sha256_file
from bid_review.models import Block, DocumentIndex, Location


def _section_from_line(line: str, current: str) -> str:
    t = line.strip()
    if not t or len(t) > 80:
        return current
    prefixes = ("第", "一、", "二、", "三、", "四、", "五、", "附件", "附录")
    if any(t.startswith(p) for p in prefixes):
        return t
    return current


def read_pdf(path: str | Path) -> DocumentIndex:
    p = Path(path).resolve()
    reader = PdfReader(str(p))
    filename = p.name
    blocks: list[Block] = []
    sections: list[str] = []
    current = "正文"
    para_idx = 0

    for page_i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            new_sec = _section_from_line(line, current)
            if new_sec != current:
                current = new_sec
                if current not in sections:
                    sections.append(current)
            loc = Location(
                filename=filename,
                file_type="pdf",
                section=current,
                paragraph_index=para_idx,
                page=page_i,
                xpath_hint=f"page[{page_i}]/line[{para_idx}]",
                excerpt=line[:240],
            )
            blocks.append(
                Block(
                    block_id=f"{filename}#pg{page_i}p{para_idx}",
                    kind="paragraph",
                    text=line,
                    location=loc,
                )
            )
            para_idx += 1

    return DocumentIndex(
        path=str(p),
        filename=filename,
        file_type="pdf",
        sha256=sha256_file(p),
        size_bytes=p.stat().st_size,
        sections=sections or ["正文"],
        blocks=blocks,
        page_count=len(reader.pages),
        metadata={"encrypted": bool(reader.is_encrypted)},
    )
