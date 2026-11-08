from __future__ import annotations

from pathlib import Path

from bid_review.hashutil import sha256_file
from bid_review.models import DocumentIndex
from bid_review.parsers.docx_parser import parse_docx
from bid_review.parsers.pdf_parser import parse_pdf
from bid_review.parsers.xlsx_parser import parse_xlsx
from bid_review.roles import infer_role


def parse_document(path: str | Path, role: str | None = None) -> DocumentIndex:
    path = Path(path)
    suffix = path.suffix.lower()
    digest = sha256_file(path)
    if suffix == ".docx":
        doc = parse_docx(path, digest)
    elif suffix == ".pdf":
        doc = parse_pdf(path, digest)
    elif suffix in {".xlsx", ".xlsm"}:
        doc = parse_xlsx(path, digest)
    else:
        raise ValueError(f"不支持的文件类型: {suffix}（仅支持 DOCX/PDF/XLSX）")
    doc.role = role or infer_role(doc.filename, doc.raw_text)
    doc.authority_rank = _authority_rank(doc.role)
    return doc


def _authority_rank(role: str) -> int:
    ranks = {
        "模板": 5,
        "正文": 10,
        "合同": 20,
        "技术": 30,
        "预算": 40,
        "附件": 60,
        "未知": 80,
    }
    return ranks.get(role, 80)
