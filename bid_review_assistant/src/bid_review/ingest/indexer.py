"""多文件导入与语料索引。"""

from __future__ import annotations

from pathlib import Path

from bid_review.ingest.docx_reader import read_docx
from bid_review.ingest.pdf_reader import read_pdf
from bid_review.ingest.xlsx_reader import read_xlsx
from bid_review.models import DocumentIndex

SUPPORTED = {".docx", ".pdf", ".xlsx"}


def ingest_file(path: str | Path) -> DocumentIndex:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".docx":
        return read_docx(p)
    if suffix == ".pdf":
        return read_pdf(p)
    if suffix == ".xlsx":
        return read_xlsx(p)
    raise ValueError(f"不支持的文件类型: {suffix}（支持 {sorted(SUPPORTED)}）")


def build_corpus(paths: list[str | Path]) -> list[DocumentIndex]:
    docs: list[DocumentIndex] = []
    for path in paths:
        docs.append(ingest_file(path))
    return docs
