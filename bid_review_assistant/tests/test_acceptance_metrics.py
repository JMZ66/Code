"""验收：关键冲突应检出（降漏报）；条件条款不应误报为确定错误。"""

from __future__ import annotations

from bid_review.models import Severity
from bid_review.pipeline import run_review


def _run(fixture_pack, tmp_path):
    inputs = [
        fixture_pack / "01_招标正文.docx",
        fixture_pack / "02_预算与采购清单.xlsx",
        fixture_pack / "04_合同条款.docx",
        fixture_pack / "05_格式被改但文字相同.docx",
    ]
    tech = fixture_pack / "03_技术附件.pdf"
    if tech.exists() and tech.stat().st_size > 1000:
        inputs.append(tech)
    return run_review(
        inputs,
        tmp_path / "out",
        template_docx=fixture_pack / "00_官方模板.docx",
        profile_json=fixture_pack / "profile.json",
        role_hints={
            "01_招标正文.docx": "正文",
            "02_预算与采购清单.xlsx": "预算",
            "03_技术附件.pdf": "技术",
            "04_合同条款.docx": "合同",
            "05_格式被改但文字相同.docx": "附件",
        },
    )


def test_must_catch_core_issues(fixture_pack, tmp_path):
    result, _ = _run(fixture_pack, tmp_path)
    titles = " ".join(f.title for f in result.findings)
    details = " ".join(f.detail for f in result.findings)
    blob = titles + details

    # 漏报检查：这些必须出现
    assert "工期" in blob
    assert "金额" in blob or "1600000" in blob or "120" in blob
    assert "数量" in blob
    assert any("占位" in f.title or "空白" in f.title for f in result.findings)
    assert any("修订" in f.title for f in result.findings)
    assert any(f.rule_id == "FMT-FONT" for f in result.findings) or "字体" in blob
    assert any("页边距" in f.title for f in result.findings)
    assert any("资格证明材料" in f.title or "技术方案" in f.title or "报价表" in f.title for f in result.findings)

    # 每条问题都要有位置或明确说明缺依据
    for f in result.findings:
        if f.severity != Severity.MISSING_EVIDENCE:
            assert f.evidence or "未找到" in f.detail


def test_conditional_clauses_not_confirmed_false_positive(fixture_pack, tmp_path):
    result, _ = _run(fixture_pack, tmp_path)
    # 不可抗力 / 质保响应 不应被标成“确定错误”的工期冲突唯一依据
    bad = [
        f
        for f in result.findings
        if f.severity == Severity.CONFIRMED
        and f.rule_id.startswith("CON-DURATION")
        and any("不可抗力" in (e.excerpt or "") or "质保" in (e.excerpt or "") for e in f.evidence)
        and not any(
            ("90" in (e.excerpt or "") and "60" in "".join(x.excerpt or "" for x in f.evidence))
            for e in f.evidence
        )
    ]
    # 允许正文90 vs 60被检出；不允许只因质保7工作日/不可抗力30天就确定错误
    for f in result.findings:
        excerpts = " ".join(e.excerpt or "" for e in f.evidence)
        if "质保" in excerpts and "7个工作日" in excerpts and f.severity == Severity.CONFIRMED:
            # 若唯一对比对象是一般工期，应至少降级；此处断言不要把质保响应当成确定工期冲突
            assert "工期" not in f.title or f.severity != Severity.CONFIRMED


def test_findings_have_locations(fixture_pack, tmp_path):
    result, _ = _run(fixture_pack, tmp_path)
    located = [f for f in result.findings if f.evidence]
    assert located, "应至少有带定位的问题"
    for f in located:
        for e in f.evidence:
            assert e.filename
            assert e.excerpt or e.paragraph_index is not None or e.table_index is not None
