"""对照模板配置检查字体、字号、行距、页边距、分节、页眉页脚、表格结构。"""

from __future__ import annotations

from typing import Any

from bid_review.models import (
    DocumentIndex,
    Finding,
    IssueCategory,
    Severity,
    SourceLoc,
)


def check_format(docs: list[DocumentIndex], profile: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    fid = 1
    for doc in docs:
        if doc.file_type != "docx":
            continue
        if doc.role == "模板":
            continue
        for f in _check_body_fonts(doc, profile, fid):
            findings.append(f)
            fid += 1
        for f in _check_margins(doc, profile, fid):
            findings.append(f)
            fid += 1
        for f in _check_sections(doc, profile, fid):
            findings.append(f)
            fid += 1
        for f in _check_headers_footers(doc, profile, fid):
            findings.append(f)
            fid += 1
        for f in _check_tables(doc, profile, fid):
            findings.append(f)
            fid += 1
        for f in _check_revisions_comments(doc, fid):
            findings.append(f)
            fid += 1
    return findings


def _loc(doc: DocumentIndex, **kwargs) -> SourceLoc:
    return SourceLoc(
        filename=doc.filename,
        file_type=doc.file_type,
        sha256=doc.sha256,
        **kwargs,
    )


def _check_body_fonts(doc: DocumentIndex, profile: dict, start_id: int) -> list[Finding]:
    body = profile.get("body", {})
    h1 = profile.get("heading1", {})
    h2 = profile.get("heading2", {})
    expect_font = body.get("font_name")
    expect_size = body.get("font_size_pt")
    expect_spacing = body.get("line_spacing")
    out: list[Finding] = []
    n = start_id

    for p in doc.paragraphs:
        if not p.text.strip() or len(p.text.strip()) < 2:
            continue
        target = body
        label = "正文"
        if p.is_heading:
            if p.style and "2" in p.style:
                target = h2
                label = "二级标题"
            else:
                target = h1
                label = "一级标题"
            expect_font = target.get("font_name")
            expect_size = target.get("font_size_pt")
            expect_spacing = None
        else:
            expect_font = body.get("font_name")
            expect_size = body.get("font_size_pt")
            expect_spacing = body.get("line_spacing")

        if expect_font and p.font_name and p.font_name != expect_font:
            # 文字相同但格式被改：标为确定错误（格式）
            out.append(
                Finding(
                    finding_id=f"F{n:04d}",
                    category=IssueCategory.FORMAT,
                    severity=Severity.CONFIRMED,
                    title=f"{label}字体不符合模板",
                    detail=f"实际字体「{p.font_name}」，模板要求「{expect_font}」。",
                    evidence=[_loc(doc, section=p.section, paragraph_index=p.index, excerpt=p.text[:160])],
                    rationale="对照模板/配置中的字体要求逐段检查。",
                    suggestion="按官方模板恢复字体；本工具不自动改写原文件。",
                    rule_id="FMT-FONT",
                )
            )
            n += 1
        if expect_size and p.font_size_pt and abs(p.font_size_pt - float(expect_size)) > 0.2:
            out.append(
                Finding(
                    finding_id=f"F{n:04d}",
                    category=IssueCategory.FORMAT,
                    severity=Severity.CONFIRMED,
                    title=f"{label}字号不符合模板",
                    detail=f"实际字号 {p.font_size_pt}pt，模板要求 {expect_size}pt。",
                    evidence=[_loc(doc, section=p.section, paragraph_index=p.index, excerpt=p.text[:160])],
                    rationale="对照模板/配置中的字号要求。",
                    suggestion="按官方模板恢复字号。",
                    rule_id="FMT-SIZE",
                )
            )
            n += 1
        if expect_spacing and p.line_spacing and abs(p.line_spacing - float(expect_spacing)) > 0.05:
            out.append(
                Finding(
                    finding_id=f"F{n:04d}",
                    category=IssueCategory.FORMAT,
                    severity=Severity.CONFIRMED,
                    title="行距不符合模板",
                    detail=f"实际行距 {p.line_spacing}，模板要求 {expect_spacing}。",
                    evidence=[_loc(doc, section=p.section, paragraph_index=p.index, excerpt=p.text[:160])],
                    rationale="对照模板/配置中的行距要求。",
                    suggestion="按官方模板恢复行距。",
                    rule_id="FMT-SPACING",
                )
            )
            n += 1
    return out


def _check_margins(doc: DocumentIndex, profile: dict, start_id: int) -> list[Finding]:
    mcfg = profile.get("margins_cm", {})
    tol = float(mcfg.get("tolerance", 0.15))
    out: list[Finding] = []
    n = start_id
    for margin in doc.page_margins:
        for side in ("top", "bottom", "left", "right"):
            expect = mcfg.get(side)
            actual = margin.get(f"{side}_cm")
            if expect is None or actual is None:
                continue
            if abs(float(actual) - float(expect)) > tol:
                out.append(
                    Finding(
                        finding_id=f"F{n:04d}",
                        category=IssueCategory.FORMAT,
                        severity=Severity.CONFIRMED,
                        title=f"页边距({side})不符合模板",
                        detail=f"分节#{margin.get('section_index')} {side}={actual}cm，模板要求 {expect}cm（容差 {tol}cm）。",
                        evidence=[
                            _loc(
                                doc,
                                section=f"分节#{margin.get('section_index')}",
                                ooxml_part="word/document.xml#sectPr",
                                excerpt=f"{side}={actual}cm",
                            )
                        ],
                        rationale="对照模板页边距配置。",
                        suggestion="按官方模板调整页边距。",
                        rule_id="FMT-MARGIN",
                    )
                )
                n += 1
    if profile.get("require_single_section") and doc.section_count > 1:
        out.append(
            Finding(
                finding_id=f"F{n:04d}",
                category=IssueCategory.FORMAT,
                severity=Severity.SUSPECTED,
                title="存在多分节",
                detail=f"文档包含 {doc.section_count} 个分节，请确认是否符合模板要求。",
                evidence=[_loc(doc, excerpt=f"section_count={doc.section_count}")],
                rationale="模板可要求单一分节；多分节需人工确认页眉页脚是否正确。",
                suggestion="核对分节符与页眉页脚链接设置。",
                rule_id="FMT-SECTION-COUNT",
            )
        )
    return out


def _check_sections(doc: DocumentIndex, profile: dict, start_id: int) -> list[Finding]:
    required = profile.get("required_sections") or []
    if not required:
        return []
    # 必需章节仅对招标正文强制；合同/附件/预算不套用同一目录结构
    if doc.role not in {"正文", "未知"}:
        return []
    names = " ".join(s.name for s in doc.sections) + " " + doc.raw_text[:5000]
    out: list[Finding] = []
    n = start_id
    for req in required:
        if req not in names:
            out.append(
                Finding(
                    finding_id=f"F{n:04d}",
                    category=IssueCategory.STRUCTURE,
                    severity=Severity.MISSING_EVIDENCE,
                    title=f"缺少要求章节：{req}",
                    detail=f"在文档章节索引与正文抽样中未找到「{req}」。",
                    evidence=[_loc(doc, excerpt="（未找到对应章节）")],
                    rationale="模板/配置列出的必需章节未出现。",
                    suggestion="确认章节标题是否更名，或附件中是否另有说明。",
                    rule_id="STR-SECTION",
                )
            )
            n += 1
    return out


def _check_headers_footers(doc: DocumentIndex, profile: dict, start_id: int) -> list[Finding]:
    out: list[Finding] = []
    n = start_id
    for kind, key in (("header", "header_must_contain"), ("footer", "footer_must_contain")):
        must = profile.get(key) or []
        if not must:
            continue
        texts = [hf.text for hf in doc.headers_footers if hf.kind == kind]
        blob = " ".join(texts)
        for token in must:
            if token not in blob:
                out.append(
                    Finding(
                        finding_id=f"F{n:04d}",
                        category=IssueCategory.FORMAT,
                        severity=Severity.CONFIRMED,
                        title=f"{'页眉' if kind == 'header' else '页脚'}缺少要求内容",
                        detail=f"未找到「{token}」。",
                        evidence=[_loc(doc, excerpt=blob[:160] or "（空）")],
                        rationale="对照模板页眉/页脚要求。",
                        suggestion="按模板补齐页眉页脚固定文字。",
                        rule_id="FMT-HF",
                    )
                )
                n += 1
    return out


def _check_tables(doc: DocumentIndex, profile: dict, start_id: int) -> list[Finding]:
    tcfg = profile.get("table") or {}
    min_cols = int(tcfg.get("min_cols", 1))
    out: list[Finding] = []
    n = start_id
    for t in doc.tables:
        if t.col_count and t.col_count < min_cols:
            out.append(
                Finding(
                    finding_id=f"F{n:04d}",
                    category=IssueCategory.FORMAT,
                    severity=Severity.SUSPECTED,
                    title="表格列数偏少",
                    detail=f"表格#{t.index} 仅 {t.col_count} 列，配置要求至少 {min_cols} 列。",
                    evidence=[
                        _loc(
                            doc,
                            section=t.section,
                            table_index=t.index,
                            excerpt=" | ".join(t.rows[0][:4]) if t.rows else "",
                        )
                    ],
                    rationale="表格结构与模板配置比对。",
                    suggestion="确认是否为示意表或被合并单元格影响。",
                    rule_id="FMT-TABLE",
                )
            )
            n += 1
    return out


def _check_revisions_comments(doc: DocumentIndex, start_id: int) -> list[Finding]:
    out: list[Finding] = []
    n = start_id
    if doc.revisions:
        out.append(
            Finding(
                finding_id=f"F{n:04d}",
                category=IssueCategory.PLACEHOLDER,
                severity=Severity.CONFIRMED,
                title="文档残留修订痕迹",
                detail=f"检测到 {len(doc.revisions)} 处修订痕迹。",
                evidence=[
                    _loc(doc, excerpt=doc.revisions[0][:160], ooxml_part="word/document.xml")
                ],
                rationale="正式招标文件通常不应保留未接受的修订。",
                suggestion="在 Word 中接受/拒绝全部修订后再发布；本工具不修改原文件。",
                rule_id="CNT-REVISION",
            )
        )
        n += 1
    if doc.comments:
        out.append(
            Finding(
                finding_id=f"F{n:04d}",
                category=IssueCategory.PLACEHOLDER,
                severity=Severity.CONFIRMED,
                title="文档残留批注",
                detail=f"检测到 {len(doc.comments)} 条批注。",
                evidence=[
                    _loc(doc, excerpt=doc.comments[0][:160], ooxml_part="word/comments.xml")
                ],
                rationale="正式文件发布前应清除内部批注。",
                suggestion="删除批注后再发布。",
                rule_id="CNT-COMMENT",
            )
        )
    return out
