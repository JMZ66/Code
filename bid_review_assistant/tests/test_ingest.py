from pathlib import Path

import pytest

from bid_review.ingest.indexer import ingest_file
from bid_review.integrity import sha256_file

FIXTURES = Path(__file__).resolve().parents[1] / "testdata" / "generated"


@pytest.fixture(scope="module", autouse=True)
def ensure_fixtures():
    if not (FIXTURES / "01_招标正文.docx").exists():
        from scripts.build_fixtures import main as build

        build()


def test_docx_index_has_sections_and_tables():
    doc = ingest_file(FIXTURES / "01_招标正文.docx")
    assert doc.file_type == "docx"
    assert doc.blocks
    assert doc.tables
    assert doc.sha256 == sha256_file(FIXTURES / "01_招标正文.docx")
    assert doc.has_comments is True
    assert doc.has_revisions is True


def test_pdf_has_page_numbers():
    doc = ingest_file(FIXTURES / "03_技术附件.pdf")
    assert doc.page_count and doc.page_count >= 2
    assert any(b.location.page == 2 for b in doc.blocks)


def test_xlsx_sheets():
    doc = ingest_file(FIXTURES / "04_预算表.xlsx")
    assert "预算表" in doc.sections
    assert any("1200000" in b.text or "1,250,000" in b.text or "1250000" in b.text for b in doc.blocks)
