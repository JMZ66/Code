"""Office document parsing and verification for downstream agents."""

from office_kit.api import (
    apply_edit,
    check_files,
    diff_files,
    document_outline,
    parse_document,
    propose_edit,
    read_cells,
    read_paragraphs,
    read_section,
    read_table,
    search_document,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "parse_document",
    "document_outline",
    "read_paragraphs",
    "read_section",
    "read_table",
    "read_cells",
    "search_document",
    "check_files",
    "diff_files",
    "propose_edit",
    "apply_edit",
]
