"""跨文件一致性检查：结合上下文、条件与效力顺序，避免单纯数值差异误判。"""

from __future__ import annotations

import re
from collections import defaultdict

from bid_review.models import (
    DocumentIndex,
    ExtractedField,
    Issue,
    IssueCategory,
    Location,
    Severity,
)

# 条件关键词：出现则视为不同适用场景，不宜直接判矛盾
CONDITION_MARKERS = (
    "若",
    "如",
    "情况下",
    "不含",
    "含税",
    "不含税",
    "暂估价",
    "可选",
    "备选",
    "调试期",
    "质保期",
    "交货期",
    "服务期",
    "施工期",
    "联合体",
    "单一来源",
    "分项",
    "专项",
    "备品",
    "备件",
    "安装",
    "运输",
)


def _condition_signature(field: ExtractedField) -> str:
    parts = list(field.conditions)
    ctx = field.context or ""
    for m in CONDITION_MARKERS:
        if m in ctx:
            # 截取附近片段
            idx = ctx.find(m)
            parts.append(ctx[max(0, idx - 2) : idx + 12])
    # 工期相关特殊：交货期 vs 工期 vs 质保
    for label in ("交货期", "工期", "质保期", "服务期限", "供货期", "建设工期"):
        if label in ctx:
            parts.append(label)
    return "|".join(sorted(set(parts)))


def _compatible_conditions(a: ExtractedField, b: ExtractedField) -> bool:
    """True = 条件可视为同一事项，可比较；False = 不同条件，不应直接判矛盾。"""
    sa, sb = _condition_signature(a), _condition_signature(b)
    if not sa and not sb:
        return True
    if sa == sb:
        return True
    # 一方无条件、一方有条件 → 可能是一般与例外，转人工
    if bool(sa) != bool(sb):
        return False
    # 双方条件都存在但不相同 → 不直接判冲突
    return False


def _values_conflict(key: str, a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return False
    if key == "amount":
        try:
            return abs(float(a) - float(b)) > 0.01
        except ValueError:
            return a != b
    if key == "duration":
        return a != b
    if key == "quantity":
        return a != b
    if key == "consortium":
        neg_a = any(x in a for x in ("不接受", "禁止", "不允许"))
        neg_b = any(x in b for x in ("不接受", "禁止", "不允许"))
        pos_a = any(x in a for x in ("接受", "允许")) and not neg_a
        pos_b = any(x in b for x in ("接受", "允许")) and not neg_b
        return (neg_a and pos_b) or (neg_b and pos_a)
    return a != b


def _is_citation_only(text: str, title: str, num: str) -> bool:
    """引用句本身不算附件正文命中。"""
    t = text.strip()
    if not t:
        return True
    if re.search(rf"详见?\s*附件\s*{re.escape(num)}", t):
        return True
    if t.startswith("附件") and title in t and len(t) < len(title) + 16:
        # 形如“附件1 技术规格书”的标题行：若仅出现一次可算命中；此处交给调用方
        return False
    return False


def _attachment_present(docs: list[DocumentIndex], num: str, title: str) -> bool:
    # 文件名命中
    for d in docs:
        if title and title in d.filename:
            return True
        if f"附件{num}" in d.filename or f"附件 {num}" in d.filename:
            return True
    # 独立标题/章节命中（排除“详见附件…”引用句）
    for d in docs:
        for sec in d.sections:
            if title and title in sec:
                return True
            if re.match(rf"附件\s*{re.escape(num)}\b", sec):
                return True
        for b in d.blocks:
            text = b.text.strip()
            if not text:
                continue
            if _is_citation_only(text, title, num):
                continue
            if title and title == text:
                return True
            if re.match(rf"附件\s*{re.escape(num)}[：:\s].*{re.escape(title)}", text):
                return True
            # PDF/独立附件文件通常以附件标题开头
            if title and text.startswith(title):
                return True
            if re.match(rf"附件\s*{re.escape(num)}\b", text) and title in text:
                return True
    return False


def _missing_required_attachments(docs: list[DocumentIndex]) -> list[Issue]:
    issues: list[Issue] = []
    corpus = "\n".join(d.all_text() for d in docs)
    mentioned = re.findall(
        r"(?:详见)?附件\s*([一二三四五六七八九十\d]+)[：:、.\s]*([^\n。；]{2,40})",
        corpus,
    )
    n = 1
    seen: set[tuple[str, str]] = set()
    evidence_locs: dict[tuple[str, str], list[Location]] = {}
    for d in docs:
        for b in d.blocks:
            m = re.search(
                r"(?:详见)?附件\s*([一二三四五六七八九十\d]+)[：:、.\s]*([^\n。；]{2,40})",
                b.text,
            )
            if m:
                key = (m.group(1), m.group(2).strip().strip("《》"))
                evidence_locs.setdefault(key, []).append(b.location)

    for num, title in mentioned:
        title = title.strip().strip("《》")
        key = (num, title)
        if key in seen:
            continue
        seen.add(key)
        if _attachment_present(docs, num, title):
            continue
        issues.append(
            Issue(
                issue_id=f"ATT-{n:04d}",
                category=IssueCategory.CONSISTENCY,
                severity=Severity.MISSING_EVIDENCE,
                title=f"缺少附件依据：附件{num}",
                description=f"正文提及「附件{num} {title}」，但语料中未找到对应附件正文或文件。",
                evidence=evidence_locs.get(key, [])[:3]
                or [
                    Location(
                        filename="(语料)",
                        file_type="meta",
                        section="附件引用",
                        excerpt=f"附件{num} {title}",
                    )
                ],
                rationale="排除“详见附件…”引用句后，仍未检索到同名附件标题/文件。",
                suggestion="补齐附件文件，或修正正文引用。",
                related_fields=["attachment"],
            )
        )
        n += 1

    # 资格要求被提及时检查是否有实质内容
    if re.search(r"资质要求|投标人资格|资格要求", corpus):
        qual_blocks = [
            b
            for d in docs
            for b in d.blocks
            if ("资质" in b.text or "资格" in b.text)
            and not re.search(r"详见?\s*附件", b.text)
        ]
        substantive = [
            b
            for b in qual_blocks
            if len(re.sub(r"\s+", "", b.text)) > 18
            and not re.search(r"待填写|_{3,}|占位|资格要求$", b.text.strip())
        ]
        if not substantive:
            issues.append(
                Issue(
                    issue_id=f"ATT-{n:04d}",
                    category=IssueCategory.CONSISTENCY,
                    severity=Severity.MISSING_EVIDENCE,
                    title="资格要求缺少实质内容",
                    description="出现资格/资质字样，但未见可核验的具体要求表述。",
                    evidence=[b.location for b in qual_blocks[:3]],
                    rationale="资格相关段落过短或仅为占位。",
                    suggestion="补充完整资格条件，勿由工具臆造标准。",
                    related_fields=["qualification"],
                )
            )
    return issues


def check_consistency(
    docs: list[DocumentIndex],
    fields: list[ExtractedField],
    start_id: int = 1,
) -> list[Issue]:
    issues: list[Issue] = []
    n = start_id

    by_key: dict[str, list[ExtractedField]] = defaultdict(list)
    for f in fields:
        by_key[f.key].append(f)

    for key, items in by_key.items():
        if key in {"tech_spec"}:
            # 技术指标仅提示差异，默认人工
            norms = {(i.normalized, _condition_signature(i)) for i in items}
            if len(norms) > 1:
                issues.append(
                    Issue(
                        issue_id=f"CON-{n:04d}",
                        category=IssueCategory.CONSISTENCY,
                        severity=Severity.NEEDS_HUMAN,
                        title=f"「{items[0].label}」存在多种表述",
                        description="技术指标在多处表述不同，需结合适用产品/分项人工判断。",
                        evidence=[i.location for i in items[:6]],
                        rationale="技术指标差异默认不自动判定为错误。",
                        suggestion="按分项、型号与效力文件核对。",
                        related_fields=[key],
                    )
                )
                n += 1
            continue

        # 去重同文件同值
        unique_items: list[ExtractedField] = []
        seen = set()
        for it in items:
            sig = (it.normalized, it.location.filename, it.location.section, _condition_signature(it))
            if sig in seen:
                continue
            seen.add(sig)
            unique_items.append(it)

        for i in range(len(unique_items)):
            for j in range(i + 1, len(unique_items)):
                a, b = unique_items[i], unique_items[j]
                if not _values_conflict(key, a.normalized, b.normalized):
                    continue

                same_matter = _compatible_conditions(a, b)
                auth_diff = abs(a.source_authority - b.source_authority)

                if not same_matter:
                    issues.append(
                        Issue(
                            issue_id=f"CON-{n:04d}",
                            category=IssueCategory.CONSISTENCY,
                            severity=Severity.NEEDS_HUMAN,
                            title=f"「{a.label}」数值不同但条件可能不同",
                            description=(
                                f"发现 {a.normalized} 与 {b.normalized}，"
                                "但上下文条件不完全一致，不能仅因数值不同认定矛盾。"
                            ),
                            evidence=[a.location, b.location],
                            rationale=(
                                f"条件签名 A=[{_condition_signature(a) or '无'}] "
                                f"B=[{_condition_signature(b) or '无'}]"
                            ),
                            suggestion="结合条款适用条件、分项范围与文件效力顺序人工判断。",
                            related_fields=[key],
                        )
                    )
                    n += 1
                    continue

                # 同条件不同值
                if auth_diff >= 20:
                    higher = a if a.source_authority >= b.source_authority else b
                    lower = b if higher is a else a
                    issues.append(
                        Issue(
                            issue_id=f"CON-{n:04d}",
                            category=IssueCategory.CONSISTENCY,
                            severity=Severity.SUSPECTED_CONFLICT,
                            title=f"「{a.label}」跨文件不一致（效力不同）",
                            description=(
                                f"同事项出现 {a.normalized} 与 {b.normalized}；"
                                f"相对更权威来源为 {higher.location.filename}。"
                            ),
                            evidence=[a.location, b.location],
                            rationale=(
                                f"条件兼容；效力分 {a.source_authority}/{b.source_authority}；"
                                f"低效力表述: {lower.normalized}"
                            ),
                            suggestion="以合同/招标正文等高效力文件为准，核对是否为笔误。",
                            related_fields=[key],
                        )
                    )
                else:
                    issues.append(
                        Issue(
                            issue_id=f"CON-{n:04d}",
                            category=IssueCategory.CONSISTENCY,
                            severity=Severity.CONFIRMED_ERROR,
                            title=f"「{a.label}」确定不一致",
                            description=(
                                f"在可比条件下出现冲突值：{a.normalized} vs {b.normalized}。"
                            ),
                            evidence=[a.location, b.location],
                            rationale="条件签名兼容且效力接近，规范化后数值/语义冲突。",
                            suggestion="修正错误表述，并同步预算表、技术附件与合同条款。",
                            related_fields=[key],
                        )
                    )
                n += 1

    required_keys = {
        "project_name": "项目名称",
        "duration": "工期",
        "amount": "金额",
        "qualification": "资质要求",
        "consortium": "联合体限制",
    }
    for key, label in required_keys.items():
        if key not in by_key or not by_key[key]:
            issues.append(
                Issue(
                    issue_id=f"CON-{n:04d}",
                    category=IssueCategory.FIELD,
                    severity=Severity.MISSING_EVIDENCE,
                    title=f"未抽取到「{label}」",
                    description="导入文件中未找到可证据化的该字段表述。",
                    evidence=[],
                    rationale="规则引擎未命中；不代表文件一定缺失，禁止自动填补。",
                    suggestion="人工检索或补充明确表述。",
                    related_fields=[key],
                )
            )
            n += 1

    issues.extend(_missing_required_attachments(docs))

    # 格式相同文字：若两份 DOCX 文本相同但格式画像不同
    docx_docs = [d for d in docs if d.file_type == "docx"]
    for i in range(len(docx_docs)):
        for j in range(i + 1, len(docx_docs)):
            a, b = docx_docs[i], docx_docs[j]
            ta = re.sub(r"\s+", "", a.all_text())
            tb = re.sub(r"\s+", "", b.all_text())
            if ta and ta == tb:
                fmt_diff = a.margins_cm != b.margins_cm
                fonts_a = {x.font_name for x in a.blocks if x.font_name}
                fonts_b = {x.font_name for x in b.blocks if x.font_name}
                if fmt_diff or fonts_a != fonts_b:
                    issues.append(
                        Issue(
                            issue_id=f"CON-{n:04d}",
                            category=IssueCategory.FORMAT,
                            severity=Severity.SUSPECTED_CONFLICT,
                            title="文字相同但格式不同",
                            description=(
                                f"「{a.filename}」与「{b.filename}」正文文本一致，"
                                "但页边距或字体集合不同。"
                            ),
                            evidence=[
                                Location(
                                    filename=a.filename,
                                    file_type="docx",
                                    section="全文",
                                    excerpt=f"margins={a.margins_cm}",
                                ),
                                Location(
                                    filename=b.filename,
                                    file_type="docx",
                                    section="全文",
                                    excerpt=f"margins={b.margins_cm}",
                                ),
                            ],
                            rationale="归一化文本相等，格式元数据不等。",
                            suggestion="按官方模板统一格式，勿依赖自动改写。",
                        )
                    )
                    n += 1

    return issues
