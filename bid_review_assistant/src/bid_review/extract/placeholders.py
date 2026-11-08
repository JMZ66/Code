"""检查未填写、缺失占位符、重复占位与残留内容。"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from bid_review.models import (
    DocumentIndex,
    Finding,
    IssueCategory,
    Severity,
)


def check_placeholders(docs: list[DocumentIndex], profile: dict[str, Any]) -> list[Finding]:
    tokens = profile.get("placeholders") or []
    findings: list[Finding] = []
    n = 1
    seen_excerpts: Counter[str] = Counter()

    for doc in docs:
        for text, loc in doc.all_text_blocks():
            for token in tokens:
                if token and token in text:
                    key = f"{doc.filename}:{token}:{text[:80]}"
                    seen_excerpts[key] += 1
                    findings.append(
                        Finding(
                            finding_id=f"P{n:04d}",
                            category=IssueCategory.PLACEHOLDER,
                            severity=Severity.CONFIRMED,
                            title=f"发现未填占位符：{token}",
                            detail=f"文本中仍包含占位标记「{token}」。",
                            evidence=[loc],
                            rationale="占位符通常表示模板项未填写。",
                            suggestion="人工补全对应内容；不得由工具擅自填写。",
                            rule_id="PH-TOKEN",
                        )
                    )
                    n += 1

            # 连续下划线 / 空白填空
            if re.search(r"_{3,}", text) or re.search(r"（\s*）|\(\s*\)", text):
                findings.append(
                    Finding(
                        finding_id=f"P{n:04d}",
                        category=IssueCategory.PLACEHOLDER,
                        severity=Severity.CONFIRMED,
                        title="发现空白填空痕迹",
                        detail="文本含连续下划线或空括号，可能尚未填写。",
                        evidence=[loc],
                        rationale="空白填空是常见未完成标记。",
                        suggestion="核对是否应填写具体数值或名称。",
                        rule_id="PH-BLANK",
                    )
                )
                n += 1

    # 重复占位内容（同一占位句多次出现）
    for key, count in seen_excerpts.items():
        if count >= 3:
            findings.append(
                Finding(
                    finding_id=f"P{n:04d}",
                    category=IssueCategory.PLACEHOLDER,
                    severity=Severity.SUSPECTED,
                    title="占位内容多次重复",
                    detail=f"相似占位摘录出现 {count} 次：{key[:120]}",
                    evidence=[],
                    rationale="同一占位反复出现可能是复制残留。",
                    suggestion="人工核对是否漏改。",
                    rule_id="PH-DUP",
                )
            )
            n += 1

    # 必需附件
    required_attachments = profile.get("required_attachments") or []
    if required_attachments:
        all_names = " ".join(d.filename for d in docs)
        all_text = " ".join(d.raw_text[:3000] for d in docs)
        for att in required_attachments:
            if att not in all_names and att not in all_text:
                findings.append(
                    Finding(
                        finding_id=f"P{n:04d}",
                        category=IssueCategory.STRUCTURE,
                        severity=Severity.MISSING_EVIDENCE,
                        title=f"缺少附件/材料依据：{att}",
                        detail=f"文件名与正文抽样中均未找到「{att}」。",
                        evidence=[],
                        rationale="配置要求的附件未在导入文件集合中出现。",
                        suggestion="确认是否未导入，或命名不一致。",
                        rule_id="STR-ATTACH",
                    )
                )
                n += 1
    return findings
