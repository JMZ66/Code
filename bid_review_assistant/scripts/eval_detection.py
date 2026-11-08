#!/usr/bin/env python3
"""对照金标期望评估漏报率与误报率（基于构造测试集）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bid_review.pipeline import run_review

FIXTURES = ROOT / "testdata" / "generated"
OUT = ROOT / "testdata" / "eval_out"

# 金标：期望必须检出的问题类别（以标题/描述关键词匹配）
EXPECTED_TRUE = [
    {"id": "duration_conflict", "any": ["工期", "120", "180"], "category_hint": "一致性"},
    {"id": "amount_conflict", "any": ["金额", "1250000", "1,250,000", "1200000"], "category_hint": "一致性"},
    {"id": "placeholder", "any": ["待填写", "占位", "待填"]},
    {"id": "missing_attachment", "any": ["附件3", "缺少附件", "资格要求缺少"]},
    {"id": "format_drift", "any": ["字体", "字号", "页边距", "格式不同"]},
    {"id": "revisions_or_comments", "any": ["修订", "批注"]},
]

# 金标：不应被标为「确定错误」的情形
EXPECTED_NOT_CONFIRMED = [
    {"id": "warranty_vs_debug", "all": ["24", "30"], "forbid_severity": "确定错误"},
]


def _match_any(text: str, keys: list[str]) -> bool:
    return any(k in text for k in keys)


def main() -> int:
    if not (FIXTURES / "01_招标正文.docx").exists():
        from scripts.build_fixtures import main as build

        build()

    inputs = [
        FIXTURES / "01_招标正文.docx",
        FIXTURES / "01b_同文不同格式.docx",
        FIXTURES / "02_合同条款.docx",
        FIXTURES / "03_技术附件.pdf",
        FIXTURES / "04_预算表.xlsx",
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    result, _ = run_review(inputs, OUT, FIXTURES / "官方模板.docx")

    hits = []
    misses = []
    for exp in EXPECTED_TRUE:
        found = False
        for issue in result.issues:
            blob = issue.title + issue.description + issue.rationale + issue.suggestion
            if _match_any(blob, exp["any"]):
                found = True
                hits.append(exp["id"])
                break
        if not found:
            misses.append(exp["id"])

    false_confirmed = []
    for exp in EXPECTED_NOT_CONFIRMED:
        for issue in result.issues:
            blob = issue.title + issue.description
            if all(k in blob for k in exp["all"]) and issue.severity.value == exp["forbid_severity"]:
                false_confirmed.append({"id": exp["id"], "issue": issue.issue_id})

    # 粗略：把“确定错误”里无法映射到期望真阳性的记为可疑误报候选（人工复核）
    confirmed = [i for i in result.issues if i.severity.value == "确定错误"]
    tp = len(hits)
    fn = len(misses)
    # 误报：条件条款被确定错误 + 可选统计
    fp = len(false_confirmed)
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    precision = tp / (tp + fp) if (tp + fp) else 1.0

    report = {
        "expected_true": len(EXPECTED_TRUE),
        "true_positives": hits,
        "false_negatives": misses,
        "false_confirmed_errors": false_confirmed,
        "confirmed_error_count": len(confirmed),
        "issue_total": len(result.issues),
        "recall_approx": round(recall, 3),
        "precision_against_forbidden": round(precision, 3),
        "summary": result.summary(),
        "integrity_unchanged": all(i.unchanged for i in result.integrity),
    }
    out_json = OUT / "detection_eval.json"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"wrote {out_json}")
    return 0 if not misses and not false_confirmed else 1


if __name__ == "__main__":
    raise SystemExit(main())
