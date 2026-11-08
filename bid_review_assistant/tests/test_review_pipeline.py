"""端到端验收：漏报/误报核心场景。"""

from __future__ import annotations

from pathlib import Path

import pytest

from bid_review.integrity import sha256_file
from bid_review.pipeline import run_review

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "testdata" / "generated"


@pytest.fixture(scope="module", autouse=True)
def ensure_fixtures():
    if not (FIXTURES / "01_招标正文.docx").exists():
        import sys

        sys.path.insert(0, str(ROOT))
        from scripts.build_fixtures import main as build

        build()


@pytest.fixture(scope="module")
def review(tmp_path_factory):
    out = tmp_path_factory.mktemp("report")
    inputs = [
        FIXTURES / "01_招标正文.docx",
        FIXTURES / "01b_同文不同格式.docx",
        FIXTURES / "02_合同条款.docx",
        FIXTURES / "03_技术附件.pdf",
        FIXTURES / "04_预算表.xlsx",
    ]
    before = {str(p): sha256_file(p) for p in inputs}
    before[str(FIXTURES / "官方模板.docx")] = sha256_file(FIXTURES / "官方模板.docx")
    result, paths = run_review(
        inputs,
        out,
        template_path=FIXTURES / "官方模板.docx",
    )
    after = {str(p): sha256_file(p) for p in inputs}
    after[str(FIXTURES / "官方模板.docx")] = sha256_file(FIXTURES / "官方模板.docx")
    return result, paths, before, after


def test_original_files_unchanged(review):
    result, paths, before, after = review
    assert before == after
    assert all(i.unchanged for i in result.integrity)
    for key in ("markdown", "html", "excel", "json"):
        assert Path(paths[key]).is_file()


def test_detect_duration_conflict_or_conditioned(review):
    result, *_ = review
    titles = " ".join(i.title + i.description for i in result.issues)
    # 180 天 vs 120 天应被发现（确定错误或疑似/人工）
    assert "工期" in titles or "180" in titles or "120" in titles
    duration_issues = [
        i
        for i in result.issues
        if "工期" in i.title or "duration" in i.related_fields or "工期" in i.description
    ]
    assert duration_issues, "漏报：隐藏工期矛盾未被检出"


def test_amount_inconsistency_budget(review):
    result, *_ = review
    amount_issues = [
        i
        for i in result.issues
        if "金额" in i.title or "amount" in i.related_fields or "1,250,000" in (i.description + i.rationale)
    ]
    # 预算说明 125 万 vs 正文 120 万
    assert amount_issues or any(
        f.key == "amount" and f.normalized in {"1200000", "1250000"} for f in result.fields
    )


def test_conditioned_clauses_not_hard_error(review):
    """质保24个月 vs 调试期30天 — 不得仅因数值不同判确定错误。"""
    result, *_ = review
    false_positives = [
        i
        for i in result.issues
        if i.severity.value == "确定错误"
        and ("24" in i.description and "30" in i.description)
    ]
    assert not false_positives, f"误报：条件不同条款被判确定错误: {false_positives}"


def test_placeholder_and_missing_attachment(review):
    result, *_ = review
    blob = " ".join(i.title + i.description for i in result.issues)
    assert "占位" in blob or "待填写" in blob or "待填" in blob
    assert "附件" in blob or "资格" in blob


def test_format_issues_against_template(review):
    result, *_ = review
    fmt = [i for i in result.issues if i.category.value == "格式"]
    assert fmt, "漏报：格式被修改场景应有格式问题"
    assert any("字体" in i.title or "字号" in i.title or "页边距" in i.title for i in fmt)


def test_severity_taxonomy_present(review):
    result, *_ = review
    sevs = {i.severity.value for i in result.issues}
    # 至少覆盖多种严重程度
    assert "确定错误" in sevs or "疑似冲突" in sevs
    assert "需要人工判断" in sevs or "缺少依据" in sevs


def test_issues_have_locations(review):
    result, *_ = review
    with_evidence = [i for i in result.issues if i.evidence]
    assert len(with_evidence) >= max(1, len(result.issues) // 2)
    for i in with_evidence:
        for loc in i.evidence:
            assert loc.filename
