"""跨文件一致性检查：结合上下文、条件与文件效力顺序，避免仅因数值不同误判。"""

from __future__ import annotations

from collections import defaultdict

from bid_review.models import (
    DocumentIndex,
    ExtractedField,
    Finding,
    IssueCategory,
    Severity,
    SourceLoc,
)


# 需要跨文件对齐的字段
COMPARE_KEYS = {
    "project_name",
    "duration",
    "amount",
    "quantity",
    "unit",
    "consortium",
    "qualification",
    "tech_spec",
    "bid_bond",
}


def check_consistency(
    docs: list[DocumentIndex],
    fields: list[ExtractedField],
) -> list[Finding]:
    findings: list[Finding] = []
    n = 1
    by_key: dict[str, list[ExtractedField]] = defaultdict(list)
    for f in fields:
        if f.key in COMPARE_KEYS:
            by_key[f.key].append(f)

    doc_rank = {d.filename: d.authority_rank for d in docs}
    doc_role = {d.filename: d.role for d in docs}

    for key, items in by_key.items():
        if len(items) < 2:
            continue
        # 按条件分组：不同条件不直接判冲突
        by_condition: dict[str, list[ExtractedField]] = defaultdict(list)
        for item in items:
            cond_bucket = item.condition or "__general__"
            # 预算合计与正文限价属于同一比对事项
            if key == "amount" and cond_bucket.startswith("预算合计"):
                cond_bucket = "__general__"
            # 同名清单数量与正文“数量”对齐到可比对桶
            if key == "quantity" and cond_bucket.startswith("清单项:"):
                item_name = cond_bucket.split(":", 1)[-1]
                if any(
                    item_name and item_name in (x.value + (x.loc.excerpt if x.loc else ""))
                    for x in items
                    if not x.condition
                ):
                    cond_bucket = "__general__"
            by_condition[cond_bucket].append(item)

        for cond, group in by_condition.items():
            norms = {}
            for item in group:
                norms.setdefault(item.normalized, []).append(item)

            if len(norms) <= 1:
                continue

            # 同条件、不同归一值 → 需要进一步判断效力
            sorted_norms = sorted(norms.items(), key=lambda kv: _best_rank(kv[1], doc_rank))
            primary_norm, primary_items = sorted_norms[0]
            for other_norm, other_items in sorted_norms[1:]:
                if not primary_norm or not other_norm:
                    continue
                if primary_norm == other_norm:
                    continue

                # 单位不一致单独处理
                if key == "quantity":
                    units = {i.unit for i in primary_items + other_items if i.unit}
                    if len(units) > 1:
                        findings.append(
                            _finding(
                                n,
                                "数量单位不一致",
                                f"同一数量事项出现不同计量单位：{', '.join(sorted(units))}。",
                                primary_items + other_items,
                                Severity.SUSPECTED,
                                "数值比较前必须先对齐单位；单位不同不得直接判金额/数量矛盾。",
                                "人工核对是否为换算关系或不同清单项。",
                                "CON-UNIT",
                            )
                        )
                        n += 1

                # 条件不同：在不同桶，这里不会进入；同桶无条件但表述不同
                if cond != "__general__":
                    # 同条件冲突更严重
                    severity = Severity.CONFIRMED
                    rationale = (
                        f"在相同条件「{cond}」下出现不同取值；"
                        f"效力优先文件角色：{_role_desc(primary_items, doc_role)}。"
                    )
                else:
                    # 检查是否一方来自更高效力文件
                    primary_rank = _best_rank(primary_items, doc_rank)
                    other_rank = _best_rank(other_items, doc_rank)
                    roles_involved = {
                        doc_role.get(i.loc.filename if i.loc else "", "未知")
                        for i in primary_items + other_items
                    }
                    # 正文 vs 预算的金额/数量冲突：业务上应高亮为确定错误
                    if key in {"amount", "quantity"} and ("正文" in roles_involved and "预算" in roles_involved):
                        severity = Severity.CONFIRMED
                        rationale = (
                            "招标正文与预算/清单对同一金额或数量事项给出不同取值，"
                            "且未检出可区分的适用条件。"
                        )
                    elif abs(primary_rank - other_rank) >= 20:
                        severity = Severity.SUSPECTED
                        rationale = (
                            "不同文件效力顺序不同：较低效力文件与较高效力文件数值不一致，"
                            "应以上位文件为准，但仍需人工确认是否属于适用条件差异。"
                        )
                    else:
                        # 同级冲突
                        if key in {"duration", "amount", "quantity", "consortium"}:
                            severity = Severity.CONFIRMED
                        else:
                            severity = Severity.NEEDS_HUMAN
                        rationale = (
                            "同效力层级出现不同取值，且未检出可区分的适用条件。"
                            "若存在未抽取到的隐含条件，请人工判断。"
                        )

                # 金额：允许万元/元换算后一致
                if key == "amount" and _amount_equivalent(primary_norm, other_norm):
                    continue

                title = {
                    "project_name": "项目名称表述不一致",
                    "duration": "工期/服务期不一致",
                    "amount": "金额不一致",
                    "quantity": "数量不一致",
                    "unit": "计量单位不一致",
                    "consortium": "联合体限制不一致",
                    "qualification": "资质要求表述不一致",
                    "tech_spec": "技术指标表述不一致",
                    "bid_bond": "保证金不一致",
                }.get(key, f"{key}不一致")

                findings.append(
                    _finding(
                        n,
                        title,
                        f"归一值 A={primary_norm}（{primary_items[0].value}）与 "
                        f"B={other_norm}（{other_items[0].value}）冲突。",
                        primary_items + other_items,
                        severity,
                        rationale,
                        "对照效力更高的文件（通常为招标正文/合同）核实；不要仅因数字不同就改文件。",
                        f"CON-{key.upper()}",
                    )
                )
                n += 1

        # 跨条件：相似字段但条件不同 → 不判冲突，可提示人工
        cond_keys = [c for c in by_condition if c != "__general__"]
        if len(cond_keys) >= 1 and "__general__" in by_condition:
            general_norms = {i.normalized for i in by_condition["__general__"]}
            for ck in cond_keys:
                cond_norms = {i.normalized for i in by_condition[ck]}
                if general_norms and cond_norms and general_norms != cond_norms:
                    findings.append(
                        Finding(
                            finding_id=f"C{n:04d}",
                            category=IssueCategory.CONSISTENCY,
                            severity=Severity.NEEDS_HUMAN,
                            title=f"{items[0].label}存在条件差异表述",
                            detail=(
                                f"一般表述归一值 {sorted(general_norms)}；"
                                f"条件「{ck}」下为 {sorted(cond_norms)}。"
                                "二者可能并不冲突。"
                            ),
                            evidence=_evidence(by_condition["__general__"] + by_condition[ck]),
                            rationale="不同适用条件下的数值差异不自动视为矛盾。",
                            suggestion="人工确认条件是否覆盖同一事项。",
                            rule_id="CON-CONTEXT",
                        )
                    )
                    n += 1

    # 正文提到的附件是否在文件集合中
    findings.extend(_attachment_mentions(docs, n))
    return findings


def _attachment_mentions(docs: list[DocumentIndex], start_n: int) -> list[Finding]:
    import re

    findings: list[Finding] = []
    n = start_n
    names = {d.filename for d in docs}
    name_blob = " ".join(names)
    for doc in docs:
        if doc.role not in {"正文", "合同", "未知"}:
            continue
        for text, loc in doc.all_text_blocks():
            for m in re.finditer(r"附件[:：]?\s*([A-Za-z0-9\-一二三四五六七八九十]+)?\s*[《「]?([^》」\n，。；;]{2,40})", text):
                att = m.group(2).strip()
                if not att or att in {"见附件", "详见附件"}:
                    continue
                if att in name_blob or any(att in fn for fn in names):
                    continue
                # 宽松：附件关键词是否出现在其他文件正文
                if any(att in d.raw_text for d in docs if d.filename != doc.filename):
                    continue
                findings.append(
                    Finding(
                        finding_id=f"C{n:04d}",
                        category=IssueCategory.STRUCTURE,
                        severity=Severity.MISSING_EVIDENCE,
                        title=f"提及的附件未见导入：{att}",
                        detail=f"正文提到「{att}」，但导入文件集合中未找到对应材料。",
                        evidence=[loc],
                        rationale="交叉引用附件但缺少文件依据。",
                        suggestion="确认是否未导入，或附件名称不一致。",
                        rule_id="CON-ATTACH-REF",
                    )
                )
                n += 1
    return findings


def _best_rank(items: list[ExtractedField], doc_rank: dict[str, int]) -> int:
    ranks = []
    for i in items:
        fn = i.loc.filename if i.loc else ""
        ranks.append(doc_rank.get(fn, 80))
    return min(ranks) if ranks else 80


def _role_desc(items: list[ExtractedField], doc_role: dict[str, str]) -> str:
    roles = []
    for i in items:
        fn = i.loc.filename if i.loc else ""
        roles.append(f"{fn}({doc_role.get(fn, '未知')})")
    return ", ".join(roles[:3])


def _amount_equivalent(a: str, b: str) -> bool:
    try:
        fa, fb = float(a), float(b)
    except ValueError:
        return False
    if fa == fb:
        return True
    # 100 万 vs 1000000
    ratio = max(fa, fb) / min(fa, fb) if min(fa, fb) else 0
    return abs(ratio - 10000) < 0.01 or abs(ratio - 100) < 0.01


def _evidence(items: list[ExtractedField]) -> list[SourceLoc]:
    out: list[SourceLoc] = []
    for i in items:
        if i.loc:
            loc = i.loc
            if not loc.excerpt:
                loc = SourceLoc(**{**loc.__dict__, "excerpt": i.value[:160]})
            out.append(loc)
    return out


def _finding(
    n: int,
    title: str,
    detail: str,
    items: list[ExtractedField],
    severity: Severity,
    rationale: str,
    suggestion: str,
    rule_id: str,
) -> Finding:
    return Finding(
        finding_id=f"C{n:04d}",
        category=IssueCategory.CONSISTENCY,
        severity=severity,
        title=title,
        detail=detail,
        evidence=_evidence(items),
        rationale=rationale,
        suggestion=suggestion,
        rule_id=rule_id,
    )
