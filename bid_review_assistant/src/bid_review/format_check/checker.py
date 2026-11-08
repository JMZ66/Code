"""对照官方 Word 模板做格式与占位检查（只读，不改原文件）。"""

from __future__ import annotations

import re
from pathlib import Path

from bid_review.ingest.docx_reader import extract_format_profile, read_docx
from bid_review.models import DocumentIndex, Issue, IssueCategory, Location, Severity

PLACEHOLDER_PATTERNS = [
    (r"_{3,}", "下划线占位未填写"),
    (r"□+|☐+|\[\s*\]|【\s*】", "勾选/方括号占位未填写"),
    (r"待填写|待补充|请填写|此处填写|XXX+|ＴＢＤ|TBD|TODO|占位", "残留待填占位文本"),
    (r"￥\s*元|人民币\s*元", "金额占位可疑"),
    (r"年月日|年\s*月\s*日", "日期占位未填写"),
]


def check_placeholders(docs: list[DocumentIndex], start_id: int = 1) -> list[Issue]:
    issues: list[Issue] = []
    n = start_id
    seen_texts: dict[str, list[Location]] = {}

    for doc in docs:
        for block in doc.blocks:
            text = block.text.strip()
            if not text:
                continue
            for pattern, title in PLACEHOLDER_PATTERNS:
                if re.search(pattern, text, flags=re.IGNORECASE):
                    issues.append(
                        Issue(
                            issue_id=f"PH-{n:04d}",
                            category=IssueCategory.PLACEHOLDER,
                            severity=Severity.CONFIRMED_ERROR
                            if "待" in title or "占位" in title
                            else Severity.SUSPECTED_CONFLICT,
                            title=title,
                            description=f"在「{doc.filename}」发现疑似未填写内容。",
                            evidence=[block.location],
                            rationale=f"匹配模式: /{pattern}/",
                            suggestion="请按模板要求填写完整，或删除残留占位符。",
                        )
                    )
                    n += 1
            # 重复段落（较长文本）
            if len(text) >= 20 and block.kind in {"paragraph", "table_cell"}:
                key = re.sub(r"\s+", "", text)
                seen_texts.setdefault(key, []).append(block.location)

        if doc.file_type == "docx" and doc.has_revisions:
            issues.append(
                Issue(
                    issue_id=f"PH-{n:04d}",
                    category=IssueCategory.STRUCTURE,
                    severity=Severity.NEEDS_HUMAN,
                    title="文档含修订痕迹",
                    description=f"「{doc.filename}」仍保留修订标记，可能影响正式发布。",
                    evidence=[
                        Location(
                            filename=doc.filename,
                            file_type="docx",
                            section="文档属性",
                            excerpt="检测到 w:ins/w:del 等修订节点",
                        )
                    ],
                    rationale="OOXML 中存在修订相关节点。",
                    suggestion="人工确认是否应接受全部修订并清除痕迹后再发布。",
                )
            )
            n += 1
        if doc.file_type == "docx" and doc.has_comments:
            issues.append(
                Issue(
                    issue_id=f"PH-{n:04d}",
                    category=IssueCategory.STRUCTURE,
                    severity=Severity.NEEDS_HUMAN,
                    title="文档含批注",
                    description=f"「{doc.filename}」含批注，正式招标文件通常应清除。",
                    evidence=[
                        Location(
                            filename=doc.filename,
                            file_type="docx",
                            section="批注",
                            excerpt="检测到 word/comments.xml",
                        )
                    ],
                    rationale="存在 comments.xml。",
                    suggestion="确认批注处理完毕后删除批注再发布。",
                )
            )
            n += 1

    for key, locs in seen_texts.items():
        if len(locs) >= 2 and len({(l.filename, l.section) for l in locs}) >= 2:
            issues.append(
                Issue(
                    issue_id=f"PH-{n:04d}",
                    category=IssueCategory.PLACEHOLDER,
                    severity=Severity.SUSPECTED_CONFLICT,
                    title="跨位置重复段落",
                    description="相同或高度相同的段落出现在多处，请确认是否为粘贴残留。",
                    evidence=locs[:5],
                    rationale="规范化后文本完全一致且出现在不同章节/文件。",
                    suggestion="核对是否应为引用复述；若为误粘贴请删除多余处。",
                )
            )
            n += 1

    return issues


def check_against_template(
    docs: list[DocumentIndex],
    template_path: str | Path,
    start_id: int = 1,
) -> list[Issue]:
    """将目标 DOCX 与模板格式画像比对。"""
    issues: list[Issue] = []
    n = start_id
    profile = extract_format_profile(template_path)
    tmpl = read_docx(template_path)

    # 模板中应有而目标缺失的标题/关键小节
    tmpl_headings = {
        b.text.strip()
        for b in tmpl.blocks
        if b.kind == "paragraph" and b.text.strip() and len(b.text.strip()) < 60
    }
    # 仅保留像章节的
    tmpl_required = {
        h
        for h in tmpl_headings
        if any(h.startswith(p) for p in ("第", "一、", "二、", "三、", "附件", "资格", "合同"))
        or "要求" in h
        or "清单" in h
    }

    for doc in docs:
        if doc.file_type != "docx":
            continue

        # 页边距
        for side, expected in profile.get("margins_cm", {}).items():
            actual = doc.margins_cm.get(side)
            if actual is None:
                continue
            if abs(actual - expected) > 0.15:
                issues.append(
                    Issue(
                        issue_id=f"FMT-{n:04d}",
                        category=IssueCategory.FORMAT,
                        severity=Severity.CONFIRMED_ERROR,
                        title=f"页边距不符（{side}）",
                        description=f"{doc.filename} 的 {side} 边距为 {actual} cm，模板为 {expected} cm。",
                        evidence=[
                            Location(
                                filename=doc.filename,
                                file_type="docx",
                                section="页面设置",
                                excerpt=f"{side}={actual}cm",
                            )
                        ],
                        rationale="与官方模板 section 页边距比对，容差 0.15cm。",
                        suggestion="按模板调整页边距，勿由审查工具自动改写。",
                    )
                )
                n += 1

        # 分节数量
        if profile.get("section_count") and doc.section_count != profile["section_count"]:
            issues.append(
                Issue(
                    issue_id=f"FMT-{n:04d}",
                    category=IssueCategory.FORMAT,
                    severity=Severity.SUSPECTED_CONFLICT,
                    title="分节数量与模板不一致",
                    description=(
                        f"{doc.filename} 分节数={doc.section_count}，"
                        f"模板={profile['section_count']}。"
                    ),
                    evidence=[
                        Location(
                            filename=doc.filename,
                            file_type="docx",
                            section="分节",
                            excerpt=f"section_count={doc.section_count}",
                        )
                    ],
                    rationale="模板与目标文档 sections 数量不同。",
                    suggestion="核对是否误删/误增分节符及页眉页脚链接。",
                )
            )
            n += 1

        # 主导字体/字号
        font_counts: dict[str, int] = {}
        size_counts: dict[float, int] = {}
        for b in doc.blocks:
            if b.kind != "paragraph" or not b.text.strip():
                continue
            if b.font_name:
                font_counts[b.font_name] = font_counts.get(b.font_name, 0) + 1
            if b.font_size_pt is not None:
                size_counts[b.font_size_pt] = size_counts.get(b.font_size_pt, 0) + 1

        dom_font = profile.get("dominant_font") or ""
        if dom_font and font_counts:
            actual_font = max(font_counts, key=font_counts.get)
            if actual_font != dom_font:
                # 统计偏离模板字体的段落
                bad = [
                    b
                    for b in doc.blocks
                    if b.kind == "paragraph"
                    and b.text.strip()
                    and b.font_name
                    and b.font_name != dom_font
                ][:3]
                issues.append(
                    Issue(
                        issue_id=f"FMT-{n:04d}",
                        category=IssueCategory.FORMAT,
                        severity=Severity.CONFIRMED_ERROR,
                        title="正文字体与模板不一致",
                        description=f"模板主导字体「{dom_font}」，文档常见字体「{actual_font}」。",
                        evidence=[b.location for b in bad]
                        or [
                            Location(
                                filename=doc.filename,
                                file_type="docx",
                                section="样式",
                                excerpt=actual_font,
                            )
                        ],
                        rationale="按出现频次比较 eastAsia/ascii 字体。",
                        suggestion="按模板统一中文字体，勿自动批量改写。",
                    )
                )
                n += 1

        dom_size = profile.get("dominant_size_pt")
        if dom_size and size_counts:
            actual_size = max(size_counts, key=size_counts.get)
            if abs(actual_size - float(dom_size)) >= 0.5:
                bad = [
                    b
                    for b in doc.blocks
                    if b.kind == "paragraph"
                    and b.text.strip()
                    and b.font_size_pt is not None
                    and abs(b.font_size_pt - float(dom_size)) >= 0.5
                ][:3]
                issues.append(
                    Issue(
                        issue_id=f"FMT-{n:04d}",
                        category=IssueCategory.FORMAT,
                        severity=Severity.CONFIRMED_ERROR,
                        title="正文字号与模板不一致",
                        description=f"模板常见字号 {dom_size} pt，文档常见字号 {actual_size} pt。",
                        evidence=[b.location for b in bad],
                        rationale="字号差异 ≥ 0.5pt。",
                        suggestion="按模板调整字号。",
                    )
                )
                n += 1

        # 表格结构：模板表形状是否在目标中可找到
        tmpl_shapes = profile.get("table_shapes") or []
        doc_shapes = [(t.n_rows, t.n_cols) for t in doc.tables]
        for shape in tmpl_shapes:
            if shape not in doc_shapes and shape[0] > 1:
                issues.append(
                    Issue(
                        issue_id=f"FMT-{n:04d}",
                        category=IssueCategory.FORMAT,
                        severity=Severity.SUSPECTED_CONFLICT,
                        title="未找到与模板匹配的表格结构",
                        description=f"模板存在 {shape[0]}×{shape[1]} 表格，目标文档中未见相同结构。",
                        evidence=[
                            Location(
                                filename=doc.filename,
                                file_type="docx",
                                section="表格",
                                excerpt=f"目标表结构={doc_shapes}",
                            )
                        ],
                        rationale="仅比较行列数，不改表。",
                        suggestion="人工核对表格是否被合并/拆分或删改。",
                    )
                )
                n += 1

        # 页眉页脚
        if profile.get("headers"):
            for h in profile["headers"]:
                if h and all(h not in x for x in doc.headers):
                    issues.append(
                        Issue(
                            issue_id=f"FMT-{n:04d}",
                            category=IssueCategory.FORMAT,
                            severity=Severity.SUSPECTED_CONFLICT,
                            title="页眉内容与模板不一致",
                            description="目标文档未包含模板页眉关键文本。",
                            evidence=[
                                Location(
                                    filename=doc.filename,
                                    file_type="docx",
                                    section="页眉",
                                    excerpt=f"模板页眉片段: {h[:80]}",
                                )
                            ],
                            rationale="页眉文本包含关系检查。",
                            suggestion="核对分节后页眉是否断开或被替换。",
                        )
                    )
                    n += 1

        # 缺失模板要求的章节标题
        doc_texts = {re.sub(r"\s+", "", b.text) for b in doc.blocks}
        for req in sorted(tmpl_required):
            key = re.sub(r"\s+", "", req)
            if key and key not in doc_texts and not any(key in t for t in doc_texts):
                issues.append(
                    Issue(
                        issue_id=f"FMT-{n:04d}",
                        category=IssueCategory.PLACEHOLDER,
                        severity=Severity.MISSING_EVIDENCE,
                        title="疑似缺失模板章节/标题",
                        description=f"模板含「{req}」，目标文档未检索到对应标题。",
                        evidence=[
                            Location(
                                filename=doc.filename,
                                file_type="docx",
                                section="目录/章节",
                                excerpt=req,
                            )
                        ],
                        rationale="基于模板短标题集合做包含检索；可能因改名漏报/误报。",
                        suggestion="人工确认章节是否更名或合并。",
                    )
                )
                n += 1

    return issues
