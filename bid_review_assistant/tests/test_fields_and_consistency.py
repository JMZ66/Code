from __future__ import annotations

from bid_review.consistency import check_consistency
from bid_review.extract import extract_fields
from bid_review.models import Severity
from bid_review.parsers import parse_document


def test_extract_key_fields(fixture_pack):
    doc = parse_document(fixture_pack / "01_招标正文.docx", role="正文")
    fields = extract_fields([doc])
    keys = {f.key for f in fields}
    assert "project_name" in keys
    assert "duration" in keys
    assert "amount" in keys
    assert "consortium" in keys
    # 条件字段
    assert any(f.condition for f in fields if "不可抗力" in (f.condition or f.value))


def test_context_aware_consistency(fixture_pack):
    main = parse_document(fixture_pack / "01_招标正文.docx", role="正文")
    budget = parse_document(fixture_pack / "02_预算与采购清单.xlsx", role="预算")
    contract = parse_document(fixture_pack / "04_合同条款.docx", role="合同")
    fields = extract_fields([main, budget, contract])
    findings = check_consistency([main, budget, contract], fields)
    titles = [f.title for f in findings]
    assert any("工期" in t for t in titles)
    assert any("金额" in t or "数量" in t for t in titles)

    # 联合体：正文与合同表述不同但归一化同为 forbidden，不应冲突
    consortium = [f for f in findings if "联合体" in f.title and f.severity == Severity.CONFIRMED]
    assert consortium == []
