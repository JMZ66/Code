from __future__ import annotations

from bid_review.parsers import parse_document


def test_docx_index_has_sections_tables(fixture_pack):
    doc = parse_document(fixture_pack / "01_招标正文.docx", role="正文")
    assert doc.file_type == "docx"
    assert doc.sha256
    assert any(s.name == "招标公告" for s in doc.sections)
    assert len(doc.tables) >= 1
    assert "90日历天" in doc.raw_text
    assert doc.revisions  # 含修订痕迹


def test_xlsx_index(fixture_pack):
    doc = parse_document(fixture_pack / "02_预算与采购清单.xlsx", role="预算")
    assert doc.sheets
    assert len(doc.tables) >= 1
    assert any("气相色谱仪" in cell for row in doc.tables[0].rows for cell in row)
