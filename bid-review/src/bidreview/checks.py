"""Deterministic checks. Every finding cites text that was actually read."""

from __future__ import annotations

import re
from collections import defaultdict

from bidreview.models import (
    DEFINITE,
    HUMAN,
    NO_BASIS,
    SUSPECTED,
    Document,
    EffectiveFormat,
    Fact,
    Finding,
    Precedence,
    file_token,
)
from bidreview.numbers import norm_space

_MARGIN_TOLERANCE = 40
_BRACKET = re.compile(r"【\s*(?:待填写|请填写|项目名称|XXX|×××)?\s*】")
_UNDERLINE = re.compile(r"_{3,}|＿{3,}")
_RESIDUE = re.compile(r"模板说明|请删除本段|正式投标时删除|（此处由[^）]{0,30}填写）")
_ATTACHMENT = re.compile(r"附件\s*[0-9一二三四五六七八九十百]+\s*[《〈]([^》〉]{2,40})[》〉]")
_STANDARD_ID = re.compile(r"GB\s*/?\s*T?\s*\d+(?:\.\d+)?(?:-\d+)?", re.I)

_KEEP = "请人工处理。本工具只读，不会修改原文件，也不会补写空缺。"


def _fmt_size(half: int | None) -> str:
    if half is None:
        return "（未取得）"
    value = half / 2
    if value.is_integer():
        return f"{int(value)}磅"
    return f"{value:.1f}磅"


def _fmt_line(line: int | None, rule: str | None) -> str:
    if line is None:
        return "（未取得）"
    if (rule or "auto") == "auto":
        multiple = line / 240
        text = f"{multiple:.2f}".rstrip("0").rstrip(".")
        return f"{text}倍"
    return f"{line} twip ({rule or 'exact'})"


def _style_format(doc: Document, style_id: str | None) -> EffectiveFormat:
    style = None
    if style_id and style_id in doc.styles:
        style = doc.styles[style_id]
    elif "Normal" in doc.styles:
        style = doc.styles["Normal"]
    if style is None:
        return EffectiveFormat()
    return EffectiveFormat(
        east_asia=style.east_asia,
        size_half=style.size_half,
        line=style.line,
        line_rule=style.line_rule or ("auto" if style.line else None),
        align=style.align,
    )


def _diffs(actual: EffectiveFormat, required: EffectiveFormat) -> list[str]:
    items: list[str] = []
    if required.east_asia and actual.east_asia != required.east_asia:
        items.append(f"中文字体为{actual.east_asia or '（未取得）'}，模板要求{required.east_asia}")
    if required.size_half and actual.size_half != required.size_half:
        items.append(f"字号为{_fmt_size(actual.size_half)}，模板要求{_fmt_size(required.size_half)}")
    if required.line and actual.line != required.line:
        items.append(
            f"行距为{_fmt_line(actual.line, actual.line_rule)}，模板要求{_fmt_line(required.line, required.line_rule)}"
        )
    return items


def _twips_cm(value: int | None) -> str:
    if value is None:
        return "（未设置）"
    return f"{value * 2.54 / 1440:.2f}cm"


def check_format(template: Document, doc: Document) -> list[Finding]:
    if doc.kind != "docx" or template.kind != "docx" or doc.unreadable or template.unreadable:
        return []
    findings: list[Finding] = []
    token = file_token(doc.file_name)
    used_styles = {p.style_id for p in doc.paragraphs if p.style_id}
    for style_id in sorted(used_styles):
        required = template.styles.get(style_id)
        current = doc.styles.get(style_id)
        if required is None or current is None:
            continue
        if required.has_numbering and (
            not current.has_numbering or current.num_fmt != required.num_fmt or current.lvl_text != required.lvl_text
        ):
            findings.append(
                Finding(
                    rule_id="FORMAT_NUMBERING",
                    category=DEFINITE,
                    title=f"样式“{required.name}”的编号与模板不一致",
                    original_text=f"模板编号：numFmt={required.num_fmt or '（无）'}，lvlText={required.lvl_text or '（无）'}；当前文档：numFmt={current.num_fmt or '（无）'}，lvlText={current.lvl_text or '（无）'}。",
                    basis="编号要求取自模板样式定义中的 numPr / numbering.xml，不是通用公文标准。",
                    suggestion="请按模板恢复该样式的编号定义。" + _KEEP,
                    key=f"FORMAT_NUMBERING:{token}:{style_id}",
                    files=[doc.file_name],
                    sections=["样式"],
                    locations=[f"word/styles.xml / {style_id}"],
                    details={"style_id": style_id},
                )
            )
        style_diffs = _diffs(
            EffectiveFormat(current.east_asia, current.size_half, current.line, current.line_rule, current.align),
            EffectiveFormat(required.east_asia, required.size_half, required.line, required.line_rule, required.align),
        )
        if style_diffs:
            findings.append(
                Finding(
                    rule_id="FORMAT_STYLE",
                    category=DEFINITE,
                    title=f"样式“{required.name}”的字体或行距与模板不一致",
                    original_text="；".join(style_diffs),
                    basis="比较的是双方样式表中已经写明的 eastAsia、sz 和 spacing，未写明的项不猜测。",
                    suggestion="请把该样式改回模板中的定义，不要只改单个段落。" + _KEEP,
                    key=f"FORMAT_STYLE:{token}:{style_id}",
                    files=[doc.file_name],
                    sections=["样式"],
                    locations=[f"word/styles.xml / {style_id}"],
                    details={"style_id": style_id},
                )
            )

    template_by_text: dict[str, EffectiveFormat] = {}
    for paragraph in template.paragraphs:
        if paragraph.in_table:
            continue
        key = norm_space(paragraph.accepted_text)
        if len(key) >= 12:
            template_by_text.setdefault(key, paragraph.effective)

    for paragraph in doc.paragraphs:
        if paragraph.in_table or paragraph.heading_level:
            # Headings are checked through their style. Body paragraphs carry
            # the "same characters, different formatting" comparison.
            if paragraph.heading_level:
                continue
        if paragraph.in_table or not paragraph.accepted_text.strip():
            continue
        required = _style_format(template, paragraph.style_id)
        text_key = norm_space(paragraph.accepted_text)
        if text_key in template_by_text:
            required = template_by_text[text_key]
        diffs = _diffs(paragraph.effective, required)
        if not diffs:
            continue
        snippet = paragraph.accepted_text.strip().replace("\n", "")[:8]
        findings.append(
            Finding(
                rule_id="FORMAT_PARAGRAPH",
                category=DEFINITE,
                title="段落格式与模板明示要求不一致",
                original_text=paragraph.accepted_text.strip(),
                basis="；".join(diffs) + "。相同文字若格式不同，只报告格式差异，不把它当成内容冲突。",
                suggestion="请按模板调整该段的字体、字号或行距。" + _KEEP,
                key=f"FORMAT_PARAGRAPH:{token}:{snippet}",
                files=[doc.file_name],
                sections=[paragraph.section_title],
                locations=[paragraph.location.human()],
                details={"diffs": diffs},
            )
        )

    if len(doc.sections) != len(template.sections):
        findings.append(
            Finding(
                rule_id="FORMAT_SECTION",
                category=DEFINITE,
                title="分节数量与模板不一致",
                original_text=f"模板 {len(template.sections)} 节，当前文档 {len(doc.sections)} 节。",
                basis="分节数来自 document.xml 中的 sectPr，含段末分节符和文末分节符。",
                suggestion="请按模板恢复分节，不要在审查工具里自动拆分或合并。" + _KEEP,
                key=f"FORMAT_SECTION:{token}",
                files=[doc.file_name],
                sections=["分节"],
                locations=["word/document.xml / sectPr"],
            )
        )
    margin_bits: list[str] = []
    header_bits: list[str] = []
    footer_bits: list[str] = []
    for index, (current, required) in enumerate(zip(doc.sections, template.sections)):
        for side, got, want in (
            ("上", current.top, required.top),
            ("下", current.bottom, required.bottom),
            ("左", current.left, required.left),
            ("右", current.right, required.right),
        ):
            if got is None or want is None:
                continue
            if abs(got - want) > _MARGIN_TOLERANCE:
                margin_bits.append(f"第{index + 1}节{side}边距 {_twips_cm(got)}，模板 {_twips_cm(want)}")
        if norm_space(required.header_text) and norm_space(current.header_text) != norm_space(required.header_text):
            header_bits.append(f"第{index + 1}节页眉“{current.header_text or '（空）'}”，模板“{required.header_text}”")
        if required.footer_has_page_field and not current.footer_has_page_field:
            footer_bits.append(f"第{index + 1}节模板页脚含 PAGE 域，当前文档没有")
    if margin_bits:
        findings.append(
            Finding(
                rule_id="FORMAT_MARGIN",
                category=DEFINITE,
                title="页边距与模板不一致",
                original_text="；".join(margin_bits),
                basis="页边距取自 sectPr/pgMar，容差 40 twip，只为吸收厘米换算的取整。",
                suggestion="请按模板恢复页边距。" + _KEEP,
                key=f"FORMAT_MARGIN:{token}",
                files=[doc.file_name],
                sections=["页面设置"],
                locations=["word/document.xml / sectPr/pgMar"],
            )
        )
    if header_bits:
        findings.append(
            Finding(
                rule_id="FORMAT_HEADER",
                category=DEFINITE,
                title="页眉与模板不一致",
                original_text="；".join(header_bits),
                basis="页眉文字来自模板分节所引用的 header 部件。",
                suggestion="请按模板恢复页眉文字。" + _KEEP,
                key=f"FORMAT_HEADER:{token}",
                files=[doc.file_name],
                sections=["页眉"],
                locations=["word/header"],
            )
        )
    if footer_bits:
        findings.append(
            Finding(
                rule_id="FORMAT_FOOTER",
                category=DEFINITE,
                title="页脚页码域与模板不一致",
                original_text="；".join(footer_bits),
                basis="只检查模板已经放入页脚的 PAGE 域是否还在，不计算 DOCX 排版后的页码。",
                suggestion="请按模板恢复页脚页码域。" + _KEEP,
                key=f"FORMAT_FOOTER:{token}",
                files=[doc.file_name],
                sections=["页脚"],
                locations=["word/footer"],
            )
        )

    template_tables: dict[str, list] = defaultdict(list)
    for table in template.tables:
        if table.preceding_heading:
            template_tables[norm_space(table.preceding_heading)].append(table)
    doc_tables: dict[str, list] = defaultdict(list)
    for table in doc.tables:
        if table.preceding_heading:
            doc_tables[norm_space(table.preceding_heading)].append(table)
    for heading, required_tables in template_tables.items():
        current_tables = doc_tables.get(heading) or []
        if not current_tables:
            continue
        for required, current in zip(required_tables, current_tables):
            req_header = [norm_space(cell) for cell in required.header]
            cur_header = [norm_space(cell) for cell in current.header]
            if req_header == cur_header and len(req_header) == len(cur_header):
                continue
            findings.append(
                Finding(
                    rule_id="FORMAT_TABLE",
                    category=DEFINITE,
                    title=f"表格“{required.preceding_heading}”的结构与模板不一致",
                    original_text=f"模板表头：{' | '.join(required.header)}（{len(required.header)}列）；当前表头：{' | '.join(current.header)}（{len(current.header)}列）。",
                    basis="按紧邻的同名标题配对表格，只比较表头文字和列数。多出来的、模板没有的表不删除、也不判错。",
                    suggestion="请按模板补回或改回表头，不要让工具重画表格。" + _KEEP,
                    key=f"FORMAT_TABLE:{token}:{required.preceding_heading}",
                    files=[doc.file_name],
                    sections=[current.section_title],
                    locations=[current.location.human()],
                )
            )
    return findings


def check_residue(doc: Document) -> list[Finding]:
    if doc.kind != "docx" or doc.unreadable:
        return []
    findings: list[Finding] = []
    token = file_token(doc.file_name)
    seen_residue: set[str] = set()
    for paragraph in doc.paragraphs:
        text = paragraph.accepted_text
        if not text.strip():
            continue
        if _RESIDUE.search(text):
            key = f"RESIDUE_TEMPLATE:{token}"
            if key not in seen_residue:
                seen_residue.add(key)
                findings.append(
                    Finding(
                        rule_id="RESIDUE_TEMPLATE",
                        category=DEFINITE,
                        title="仍残留模板说明",
                        original_text=text.strip(),
                        basis="命中文档里写明应删除的模板说明用语。这不是外部规范。",
                        suggestion="请人工删除残留说明。" + _KEEP,
                        key=key,
                        files=[doc.file_name],
                        sections=[paragraph.section_title],
                        locations=[paragraph.location.human()],
                    )
                )
            continue
        bracket = _BRACKET.search(text)
        if bracket:
            label = "待填写" if "待填写" in bracket.group(0) else "bracket"
            findings.append(
                Finding(
                    rule_id="UNFILLED",
                    category=DEFINITE,
                    title="存在未填写的占位括号",
                    original_text=text.strip(),
                    basis=f"命中占位写法“{bracket.group(0)}”。空括号和“待填写/请填写/XXX”才算，【注】这类标记不算。",
                    suggestion="请人工补上有依据的内容，或删除占位符。工具不会代填。" + _KEEP,
                    key=f"UNFILLED:{token}:bracket:{label}",
                    files=[doc.file_name],
                    sections=[paragraph.section_title],
                    locations=[paragraph.location.human()],
                )
            )
        if _UNDERLINE.search(text):
            findings.append(
                Finding(
                    rule_id="UNFILLED",
                    category=DEFINITE,
                    title="存在未填写的下划线空位",
                    original_text=text.strip(),
                    basis="连续三个及以上下划线视为模板空位。",
                    suggestion="请人工填写或删除该空位。" + _KEEP,
                    key=f"UNFILLED:{token}:underline",
                    files=[doc.file_name],
                    sections=[paragraph.section_title],
                    locations=[paragraph.location.human()],
                )
            )

    for table in doc.tables:
        header = table.header
        for col, name in enumerate(header):
            if "填写" not in name:
                continue
            for row_index, row in enumerate(table.rows[1:], start=2):
                if col >= len(row) or row[col].strip():
                    continue
                row_label = row[0].strip() if row else f"r{row_index}"
                findings.append(
                    Finding(
                        rule_id="UNFILLED",
                        category=DEFINITE,
                        title="填写栏为空",
                        original_text=f"表“{table.preceding_heading or table.section_title}”中“{row_label}”对应的“{name}”为空。",
                        basis="该列标题含“填写”，单元格没有可见文字。空白备注列不按此规则报告。",
                        suggestion="请人工确认是否应当填写。" + _KEEP,
                        key=f"UNFILLED:{token}:empty-cell:{row_label}",
                        files=[doc.file_name],
                        sections=[table.section_title],
                        locations=[table.location.human() + f" / 第{row_index}行第{col + 1}列"],
                    )
                )

    previous = ""
    previous_loc = ""
    previous_section = ""
    emitted: set[str] = set()
    for paragraph in doc.paragraphs:
        if paragraph.in_table or paragraph.heading_level:
            previous = ""
            continue
        text = norm_space(paragraph.accepted_text)
        if len(text) >= 15 and text == previous:
            key = f"DUPLICATE_PARAGRAPH:{token}:{paragraph.accepted_text.strip()[:8]}"
            if key not in emitted:
                emitted.add(key)
                findings.append(
                    Finding(
                        rule_id="DUPLICATE_PARAGRAPH",
                        category=DEFINITE,
                        title="相邻段落文字重复",
                        original_text=paragraph.accepted_text.strip(),
                        basis=f"与上一处正文完全相同。上一处位置：{previous_loc}。标题和短句不按重复处理。",
                        suggestion="请人工确认是否为复制残留。" + _KEEP,
                        key=key,
                        files=[doc.file_name],
                        sections=[paragraph.section_title or previous_section],
                        locations=[previous_loc, paragraph.location.human()],
                    )
                )
        previous = text if len(text) >= 15 else ""
        previous_loc = paragraph.location.human()
        previous_section = paragraph.section_title

    for note in doc.revisions:
        findings.append(
            Finding(
                rule_id="RESIDUE_REVISION",
                category=DEFINITE,
                title="存在未处理的修订痕迹",
                original_text=f"{'插入' if note.kind == 'ins' else '删除'}（{note.author or '未署名'}）：{note.text}",
                basis="修订痕迹来自 w:ins / w:del。其中的数字不当作已生效事实，避免把已删除内容判成现行冲突。",
                suggestion="请人工接受或拒绝修订后再发布。" + _KEEP,
                key=f"RESIDUE_REVISION:{token}:{note.kind}",
                files=[doc.file_name],
                sections=[note.location.section_title],
                locations=[note.location.human()],
                details={"kind": note.kind, "author": note.author},
            )
        )
    for note in doc.comments:
        findings.append(
            Finding(
                rule_id="RESIDUE_COMMENT",
                category=DEFINITE,
                title="存在未清理的批注",
                original_text=f"{note.author or '未署名'}：{note.text}",
                basis="批注来自 word/comments.xml，不参与跨文件数值比对。",
                suggestion="请人工处理批注。" + _KEEP,
                key=f"RESIDUE_COMMENT:{token}",
                files=[doc.file_name],
                sections=[note.location.section_title],
                locations=[note.location.human()],
            )
        )
    return findings


def check_missing_sections(template: Document, doc: Document) -> list[Finding]:
    if doc.kind != "docx" or doc.unreadable:
        return []
    required = []
    for level, title, _loc in template.headings:
        if level == 1 and "模板" not in title:
            required.append(title.strip())
    present = {title.strip() for level, title, _loc in doc.headings if level == 1}
    findings = []
    for title in required:
        if title not in present:
            findings.append(
                Finding(
                    rule_id="MISSING_SECTION",
                    category=DEFINITE,
                    title=f"缺少模板章节“{title}”",
                    original_text=title,
                    basis="模板中的一级标题视为应出现的章节。未在其他文件或通用目录里额外增加必需要求。",
                    suggestion="请人工补上该章节，或确认本次文件确实不使用该模板章节。" + _KEEP,
                    key=f"MISSING_SECTION:{title}",
                    files=[doc.file_name],
                    sections=[title],
                    locations=["（未找到该一级标题）"],
                )
            )
    return findings


def check_missing_attachments(docs: list[Document]) -> list[Finding]:
    haystacks = []
    for doc in docs:
        heading_text = " ".join(title for _level, title, _loc in doc.headings)
        haystacks.append(norm_space(f"{doc.file_name} {doc.title} {heading_text}"))
    seen: set[str] = set()
    findings: list[Finding] = []
    for doc in docs:
        for paragraph in doc.paragraphs:
            for match in _ATTACHMENT.finditer(paragraph.accepted_text):
                name = match.group(1).strip()
                key_name = norm_space(name)
                if not key_name or key_name in seen:
                    continue
                seen.add(key_name)
                if any(key_name in hay or hay in key_name and len(hay) >= 4 for hay in haystacks):
                    # "营业执照" inside a file name satisfies; the referencing
                    # sentence itself is not part of the haystack.
                    continue
                findings.append(
                    Finding(
                        rule_id="MISSING_ATTACHMENT",
                        category=DEFINITE,
                        title=f"引用了附件《{name}》，包内没有对应文件",
                        original_text=paragraph.accepted_text.strip(),
                        basis="只根据正文中的《附件名》查找已导入文件的文件名、标题和标题文字。不把引用句本身算作附件已提供。",
                        suggestion="请补交该附件，或改正引用。工具不会生成附件。" + _KEEP,
                        key=f"MISSING_ATTACHMENT:{name}",
                        files=[doc.file_name],
                        sections=[paragraph.section_title],
                        locations=[paragraph.location.human()],
                    )
                )
    return findings


def check_read_errors(docs: list[Document]) -> list[Finding]:
    findings: list[Finding] = []
    for doc in docs:
        token = file_token(doc.file_name)
        if doc.unreadable:
            findings.append(
                Finding(
                    rule_id="FILE_READ_ERROR",
                    category=HUMAN,
                    title="文件未能读取",
                    original_text=doc.unreadable,
                    basis="读取失败时不能判断内容，也不能把它写成符合或不符合。",
                    suggestion="请人工打开原文件确认。" + _KEEP,
                    key=f"FILE_READ_ERROR:{token}",
                    files=[doc.file_name],
                    sections=["（文件）"],
                    locations=[doc.path],
                )
            )
            continue
        if doc.kind == "pdf" and not any(p.accepted_text.strip() for p in doc.paragraphs):
            findings.append(
                Finding(
                    rule_id="NO_TEXT_LAYER",
                    category=HUMAN,
                    title="PDF 没有可用文本层",
                    original_text=doc.file_name,
                    basis="本工具不做 OCR，也不能从扫描件猜测正文。",
                    suggestion="请人工阅读该 PDF，或提供带文本层的版本。" + _KEEP,
                    key=f"NO_TEXT_LAYER:{token}",
                    files=[doc.file_name],
                    sections=["（全文）"],
                    locations=[doc.path],
                    pdf_pages=[1] if doc.page_count else [],
                )
            )
    return findings


def check_external_basis(docs: list[Document], rules: dict | None) -> list[Finding]:
    findings: list[Finding] = []
    blob = "\n".join(doc.all_text() for doc in docs)
    compact = norm_space(blob).upper().replace("／", "/")
    for item in (rules or {}).get("external_basis") or []:
        title = str(item.get("title") or item.get("id") or "").strip()
        if not title:
            continue
        match = _STANDARD_ID.search(title)
        token = match.group(0) if match else title
        needle = norm_space(token).upper().replace("／", "/")
        if needle and needle in compact:
            continue
        findings.append(
            Finding(
                rule_id="MISSING_BASIS",
                category=NO_BASIS,
                title=f"缺少用户点名的依据：{title}",
                original_text=title,
                basis="用户规则要求包内出现该依据编号或标题。全文检索没有命中。工具没有内置该标准的条文，因此不能判断技术内容是否满足。",
                suggestion="请把该依据文件纳入审查包，或取消这条规则。在此之前不能下符合性结论。" + _KEEP,
                key=f"MISSING_BASIS:{needle or title}",
                files=[doc.file_name for doc in docs],
                sections=["（全包检索）"],
                locations=["（未命中）"],
                details={"title": title},
            )
        )
    return findings


def _rank(fact: Fact, precedence: Precedence | None) -> int | None:
    if precedence is None:
        return None
    scope = norm_space(f"{fact.section} {fact.file_name} {fact.role}")
    best: tuple[int, int] | None = None
    for index, label in enumerate(precedence.labels):
        lab = norm_space(label)
        if lab and lab in scope:
            candidate = (len(lab), -index)
            if best is None or candidate > best:
                best = candidate
                chosen = index
    return None if best is None else chosen


def _locations(facts: list[Fact]) -> tuple[list[str], list[str], list[str], list[int]]:
    files: list[str] = []
    sections: list[str] = []
    locations: list[str] = []
    pages: list[int] = []
    for fact in facts:
        if fact.file_name not in files:
            files.append(fact.file_name)
        if fact.section not in sections:
            sections.append(fact.section)
        human = fact.location.human()
        if human not in locations:
            locations.append(human)
        if fact.location.pdf_page and fact.location.pdf_page not in pages:
            pages.append(fact.location.pdf_page)
    return files, sections, locations, pages


def _quote_block(facts: list[Fact]) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for fact in facts:
        line = f"[{fact.file_name} / {fact.section}] {fact.quote}"
        if line not in seen:
            seen.add(line)
            lines.append(line)
    return "\n".join(lines)


def _precedence_sentence(facts: list[Fact], precedence: Precedence | None) -> str:
    if precedence is None:
        return "审查包没有写出效力顺序，用户规则也没有指定。不能指出哪一份优先。"
    ranks = []
    for fact in facts:
        rank = _rank(fact, precedence)
        if rank is None:
            ranks.append(f"“{fact.quote}”未能对应到效力顺序中的某一级")
        else:
            ranks.append(f"“{fact.value_display}”位于“{precedence.labels[rank]}”（第{rank + 1}位）")
    where = ""
    if precedence.location is not None:
        where = f"效力顺序原文见 {precedence.location.file_name} / {precedence.location.human()}。"
    return f"效力顺序（{precedence.source}）：{' > '.join(precedence.labels)}。{'；'.join(ranks)}。{where}"


def _emit_conflict(
    subject: str,
    rule_id: str,
    category: str,
    title: str,
    facts: list[Fact],
    precedence: Precedence | None,
    basis_extra: str,
) -> Finding:
    files, sections, locations, pages = _locations(facts)
    values = []
    for fact in facts:
        if fact.value_display not in values:
            values.append(fact.value_display)
    return Finding(
        rule_id=rule_id,
        category=category,
        title=title,
        original_text=_quote_block(facts),
        basis=_precedence_sentence(facts, precedence) + basis_extra,
        suggestion="请人工选定应保留的表述，并同步其余位置。不同条件、不同事项不会仅因数字不同而报冲突。" + _KEEP,
        key=f"{rule_id}:{subject}",
        files=files,
        sections=sections,
        locations=locations,
        pdf_pages=pages,
        details={"subject": subject, "values": values, "family": facts[0].family if facts else ""},
    )


def _close(number: float, other: float, tolerance: float) -> bool:
    return abs(number - other) <= tolerance


def _clusters(facts: list[Fact], tolerance: float) -> list[list[Fact]]:
    groups: list[list[Fact]] = []
    for fact in facts:
        placed = False
        for group in groups:
            anchor = group[0].number
            if anchor is not None and fact.number is not None and _close(anchor, fact.number, tolerance):
                group.append(fact)
                placed = True
                break
            if fact.number is None and fact.value_norm == group[0].value_norm:
                group.append(fact)
                placed = True
                break
        if not placed:
            groups.append([fact])
    return groups


def check_consistency(facts: list[Fact], precedence: Precedence | None) -> list[Finding]:
    grouped: dict[tuple[str, str], list[Fact]] = defaultdict(list)
    for fact in facts:
        if fact.kind == "conditional":
            continue
        grouped[(fact.family, fact.subject)].append(fact)
    findings: list[Finding] = []
    for (_family, subject), items in grouped.items():
        findings.extend(_compare_group(subject, items, precedence))
    return findings


def _compare_group(subject: str, items: list[Fact], precedence: Precedence | None) -> list[Finding]:
    family = items[0].family
    if family == "project_name":
        return _compare_names(subject, items, precedence)
    if family in {"consortium", "qualification"}:
        assignments = [fact for fact in items if fact.kind == "assignment"]
        norms = []
        for fact in assignments:
            if fact.value_norm not in norms:
                norms.append(fact.value_norm)
        if len(norms) <= 1:
            return []
        return [
            _emit_conflict(
                subject,
                "VALUE_CONFLICT",
                DEFINITE,
                f"“{subject}”的无条件表述不一致",
                assignments,
                precedence,
                "双方都是无条件要求，文本本身不同，会改变谁能投标或合同如何签署。",
            )
        ]
    if family == "quantity":
        return _compare_quantities(subject, items, precedence)
    if family == "spec":
        return _compare_specs(subject, items, precedence)
    return _compare_measures(subject, items, precedence)


def _compare_names(subject: str, items: list[Fact], precedence: Precedence | None) -> list[Finding]:
    assignments = [fact for fact in items if fact.kind == "assignment"]
    groups: list[list[Fact]] = []
    for fact in assignments:
        placed = False
        for group in groups:
            if fact.value_norm == group[0].value_norm:
                group.append(fact)
                placed = True
                break
        if not placed:
            groups.append([fact])
    kept: list[list[Fact]] = []
    for group in groups:
        norm = group[0].value_norm
        if any(norm != other[0].value_norm and norm in other[0].value_norm for other in groups):
            continue
        kept.append(group)
    if len(kept) <= 1:
        return []
    flat = [fact for group in kept for fact in group]
    return [
        _emit_conflict(
            subject,
            "VALUE_CONFLICT",
            DEFINITE,
            "项目名称不一致",
            flat,
            precedence,
            "一个名称完整包含另一个名称时，视为简称，不报冲突。这里互不包含。",
        )
    ]


def _compare_quantities(subject: str, items: list[Fact], precedence: Precedence | None) -> list[Finding]:
    assignments = [fact for fact in items if fact.kind == "assignment"]
    dimensions = {fact.unit_family for fact in assignments if fact.unit_family}
    if len(dimensions) > 1:
        return [
            _emit_conflict(
                subject,
                "UNIT_CONFLICT",
                DEFINITE,
                f"“{subject}”的计量单位不能换算",
                assignments,
                precedence,
                "同一货物名称下的单位不属于同一量纲。工具不会把“米”和“卷”强行折算。",
            )
        ]
    return _numeric_conflict(subject, assignments, precedence, tolerance=1e-3, family_label="数量")


def _compare_specs(subject: str, items: list[Fact], precedence: Precedence | None) -> list[Finding]:
    units = {fact.unit for fact in items if fact.unit}
    if len(units) > 1:
        return [
            _emit_conflict(
                subject,
                "UNIT_CONFLICT",
                DEFINITE,
                f"“{subject}”的参数单位不一致",
                items,
                precedence,
                "同一参数出现了不同单位，工具不自行换算。",
            )
        ]
    approximates = [fact for fact in items if fact.kind == "approximate"]
    assignments = [fact for fact in items if fact.kind == "assignment"]
    minimums = [fact for fact in items if fact.kind == "minimum"]
    maximums = [fact for fact in items if fact.kind == "maximum"]
    findings: list[Finding] = []
    if approximates:
        others = assignments + minimums + maximums + approximates
        numbers = [fact.number for fact in others if fact.number is not None]
        if numbers and max(numbers) - min(numbers) > 1e-6:
            findings.append(
                _emit_conflict(
                    subject,
                    "APPROXIMATE_CONFLICT",
                    SUSPECTED,
                    f"“{subject}”含约数，且与另一处数值不同",
                    others,
                    precedence,
                    "出现“约/约为/左右”，只能列为疑似冲突，不能定性为错误。",
                )
            )
        return findings
    if len(_clusters(minimums, 1e-6)) > 1:
        findings.append(
            _emit_conflict(
                subject,
                "VALUE_CONFLICT",
                DEFINITE,
                f"“{subject}”的下限阈值不一致",
                minimums,
                precedence,
                "两处都是“不低于/不小于”一类下限，阈值不同会改变是否满足。下限与一个已经高于它的确定值不冲突。",
            )
        )
    if len(_clusters(maximums, 1e-6)) > 1:
        findings.append(
            _emit_conflict(
                subject,
                "VALUE_CONFLICT",
                DEFINITE,
                f"“{subject}”的上限阈值不一致",
                maximums,
                precedence,
                "两处上限阈值不同。",
            )
        )
    if len(_clusters(assignments, 1e-6)) > 1:
        findings.append(
            _emit_conflict(
                subject,
                "VALUE_CONFLICT",
                DEFINITE,
                f"“{subject}”的确定值不一致",
                assignments,
                precedence,
                "两处都是确定表述。",
            )
        )
    for assignment in assignments:
        for minimum in minimums:
            if assignment.number is not None and minimum.number is not None and assignment.number + 1e-6 < minimum.number:
                findings.append(
                    _emit_conflict(
                        subject,
                        "VALUE_CONFLICT",
                        DEFINITE,
                        f"“{subject}”低于已经写明的下限",
                        [assignment, minimum],
                        precedence,
                        "确定值小于“不低于”的阈值，属于直接不满足，而不是单纯数字不同。",
                    )
                )
                break
        for maximum in maximums:
            if assignment.number is not None and maximum.number is not None and assignment.number > maximum.number + 1e-6:
                findings.append(
                    _emit_conflict(
                        subject,
                        "VALUE_CONFLICT",
                        DEFINITE,
                        f"“{subject}”高于已经写明的上限",
                        [assignment, maximum],
                        precedence,
                        "确定值大于上限。",
                    )
                )
                break
    return findings


def _compare_measures(subject: str, items: list[Fact], precedence: Precedence | None) -> list[Finding]:
    assignments = [fact for fact in items if fact.kind == "assignment"]
    ceilings = [fact for fact in items if fact.kind == "ceiling"]
    families = {fact.unit_family for fact in assignments if fact.unit_family}
    findings: list[Finding] = []
    if len(families) > 1:
        findings.append(
            _emit_conflict(
                subject,
                "UNIT_FAMILY",
                HUMAN,
                f"“{subject}”使用了不能直接折算的单位",
                assignments,
                precedence,
                "月、日和其他不能直接换算的口径不会自动折算。请人工判断是否同一事项。",
            )
        )
    for family in families:
        same = [fact for fact in assignments if fact.unit_family == family]
        tolerance = 0.05 if family == "money" else 1e-3
        findings.extend(_numeric_conflict(subject, same, precedence, tolerance, "数值"))
        for ceiling in ceilings:
            if ceiling.unit_family != family or ceiling.number is None:
                continue
            exceeded = [fact for fact in same if fact.number is not None and fact.number > ceiling.number + tolerance]
            if exceeded:
                findings.append(
                    _emit_conflict(
                        subject,
                        "VALUE_CONFLICT",
                        DEFINITE,
                        f"“{subject}”超过了写明的上限",
                        exceeded + [ceiling],
                        precedence,
                        "只有确定值大于“不超过/最长”时才报告。未超过的上限不构成冲突。",
                    )
                )
    return findings


def _numeric_conflict(
    subject: str,
    facts: list[Fact],
    precedence: Precedence | None,
    tolerance: float,
    family_label: str,
) -> list[Finding]:
    usable = [fact for fact in facts if fact.number is not None]
    if len(_clusters(usable, tolerance)) <= 1:
        return []
    return [
        _emit_conflict(
            subject,
            "VALUE_CONFLICT",
            DEFINITE,
            f"“{subject}”的{family_label}不一致",
            usable,
            precedence,
            "主体、条件和单位已经对齐，规范后的数值仍然不同。仅有数字不同但条件不同的句子不会进入这里。",
        )
    ]
