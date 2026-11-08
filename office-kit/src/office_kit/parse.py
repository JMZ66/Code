"""Dispatch a path to the reader for its suffix."""

from __future__ import annotations

from pathlib import Path

from office_kit.excel import parse_xlsx
from office_kit.legacy import parse_doc
from office_kit.models import Document
from office_kit.ooxml import sha256_file
from office_kit.pdf import parse_pdf
from office_kit.word import parse_docx
from office_kit.xls_reader import parse_xls


class UnsupportedFormat(ValueError):
    pass


def parse_path(path: str | Path) -> Document:
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"文件不存在：{file_path}")
    digest = sha256_file(file_path)
    suffix = file_path.suffix.lower()
    if suffix == ".docx":
        return parse_docx(file_path, digest)
    if suffix == ".doc":
        return parse_doc(file_path, digest)
    if suffix == ".xlsx":
        return parse_xlsx(file_path, digest)
    if suffix == ".xls":
        return parse_xls(file_path, digest)
    if suffix == ".pdf":
        return parse_pdf(file_path, digest)
    raise UnsupportedFormat(f"不支持的扩展名 {suffix or '（无）'}。支持 .doc .docx .xls .xlsx，PDF 仅预留接口。")
