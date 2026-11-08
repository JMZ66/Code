"""文档解析器：DOCX / PDF / XLSX，只读。"""

from .docx_parser import parse_docx
from .pdf_parser import parse_pdf
from .xlsx_parser import parse_xlsx
from .dispatch import parse_document

__all__ = ["parse_docx", "parse_pdf", "parse_xlsx", "parse_document"]
