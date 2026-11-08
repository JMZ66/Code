"""Extract comparable facts from accepted text and tables.

Patterns are evidence extractors, not a catalogue of legal requirements.
A number is stored only when a label and a unit sit in the same clause.
Tracked deletions and uncommitted insertions are not read as effective facts.
"""

from __future__ import annotations

import re

from bidreview.models import Document, Fact, Location, Paragraph, Precedence, Table
from bidreview.numbers import duration_family, measure, money_yuan, norm_space, parse_number

_NUM = r"(?:\d[\d,，]*(?:\.\d+)?|[零〇○一二三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟两]+)"
_DURATION_LABELS = (
    "竣工验收及资料移交",
    "主体施工工期",
    "计划总工期",
    "计划工期",
    "考核工期",
    "安装工期",
    "供货期",
    "交货期",
    "服务期",
    "总工期",
)
_DURATION_UNITS = ("日历天", "工作日", "个月", "天", "月", "年")
_DURATION_RE = re.compile(
    rf"(?P<label>{'|'.join(_DURATION_LABELS)})"
    rf"[^。\n]{{0,24}}?"
    rf"(?P<num>{_NUM})"
    rf"\s*(?P<unit>{'|'.join(_DURATION_UNITS)})"
)
_AMOUNT_LABELS = (
    "预算合计金额",
    "最高投标限价",
    "预算合计",
    "合同估算价",
    "暂列金额",
    "投标保证金",
    "履约保证金",
    "暂列金",
)
_AMOUNT_RE = re.compile(
    rf"(?P<label>{'|'.join(_AMOUNT_LABELS)})"
    rf"[^。\n]{{0,40}}?"
    rf"(?:人民币)?"
    rf"\s*(?P<num>{_NUM})"
    rf"\s*(?P<unit>亿元|万元|元)"
)
_NAME_RE = re.compile(r"项目名称\s*[为：:]\s*[“\"「『]?(.+?)[”\"」』]?\s*$")
_QUAL_RE = re.compile(r"须具备(?P<body>.+?)(?:资质|资格)")
_LEVEL_RE = re.compile(r"(特级|一级|二级|三级|四级)(及以上|以上|及以下|以下)?$")
_QTY_RE = re.compile(
    rf"(?P<name>[\u4e00-\u9fffA-Za-z0-9]{{2,30}}?)"
    rf"(?:采购数量为|长度为|数量为)\s*(?P<num>{_NUM})\s*"
    rf"(?P<unit>千米|公里|毫米|厘米|米|台|套|卷|个|项|根|只|张|块|组)"
)
_SPEC_RE = re.compile(
    r"(?P<name>[\u4e00-\u9fffA-Za-z0-9（）()\-]{2,30}?)"
    r"(?P<op>不低于|不小于|不少于|不高于|不大于|不超过|推荐采用|推荐|约为|约|为)"
    r"\s*(?P<num>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>kVA|kW|Tbps|Gbps|Mbps|MHz|GHz|mm|cm|dB|%)"
)
_REJECT = re.compile(r"不接受联合体|不允许联合体|不得组成联合体")
_ALLOW = re.compile(r"接受联合体|允许联合体")
_COND = re.compile(r"若|如果|如遇|假如|另行")
_CLAUSE_SEPS = "。；;\n，,"

_BUILTIN_ALIASES = {
    "duration": {
        "计划总工期": "总工期",
        "计划工期": "总工期",
        "总工期": "总工期",
    },
    "amount": {
        "预算合计金额": "预算合计",
        "预算合计": "预算合计",
        "暂列金": "暂列金额",
        "暂列金额": "暂列金额",
    },
}


def clause_around(text: str, start: int, end: int) -> str:
    left = -1
    for sep in _CLAUSE_SEPS:
        pos = text.rfind(sep, 0, start)
        if pos > left:
            left = pos
    right = len(text)
    for sep in _CLAUSE_SEPS:
        pos = text.find(sep, end)
        if pos != -1 and pos < right:
            right = pos
    return text[left + 1 : right].strip()


def split_clauses(text: str) -> list[str]:
    parts = re.split(r"[。；;\n，,]", text)
    return [part.strip() for part in parts if part.strip()]


def _loc_for(paragraph: Paragraph) -> Location:
    return paragraph.location


def apply_alias(family: str, label: str, rules: dict | None) -> str:
    merged = dict(_BUILTIN_ALIASES.get(family, {}))
    for item in (rules or {}).get("subject_aliases") or []:
        if item.get("family") == family:
            canonical = str(item.get("canonical") or "").strip()
            for raw in item.get("labels") or []:
                if canonical:
                    merged[str(raw)] = canonical
    return merged.get(label, label)


def _fact(
    *,
    family: str,
    subject: str,
    kind: str,
    display: str,
    number: float | None,
    unit: str | None,
    unit_family: str | None,
    value_norm: str,
    quote: str,
    paragraph: Paragraph,
    role: str,
    label: str = "",
    operator: str = "",
) -> Fact:
    return Fact(
        family=family,
        subject=subject,
        kind=kind,
        value_norm=value_norm,
        value_display=display,
        number=number,
        unit=unit,
        unit_family=unit_family,
        quote=quote,
        location=paragraph.location,
        section=paragraph.section_title,
        role=role,
        file_name=paragraph.location.file_name,
        label=label,
        operator=operator,
    )


def _duration_kind(window: str) -> str:
    if any(token in window for token in ("最长不超过", "不超过", "不大于", "不得超出", "最长")):
        return "ceiling"
    if any(token in window for token in ("约", "左右", "大约")):
        return "approximate"
    return "assignment"


def extract_text_facts(paragraph: Paragraph, role: str, rules: dict | None = None) -> list[Fact]:
    text = paragraph.accepted_text.strip()
    if not text:
        return []
    found: list[Fact] = []
    occupied: list[tuple[int, int]] = []

    def free(start: int, end: int) -> bool:
        return all(end <= s or start >= e for s, e in occupied)

    for match in _DURATION_RE.finditer(text):
        if not free(match.start(), match.end()):
            continue
        occupied.append((match.start(), match.end()))
        number = parse_number(match.group("num"))
        unit = match.group("unit")
        family = duration_family(unit)
        if number is None or family is None:
            continue
        window = text[max(0, match.start() - 8) : match.end()]
        kind = _duration_kind(window)
        if _COND.search(clause_around(text, match.start(), match.end())) and kind == "assignment":
            kind = "conditional"
        label = match.group("label")
        subject = apply_alias("duration", label, rules)
        display = f"{match.group('num')}{unit}"
        found.append(
            _fact(
                family="duration",
                subject=subject,
                kind=kind,
                display=display,
                number=number,
                unit=unit,
                unit_family=family,
                value_norm=f"{number:.4f}|{family}",
                quote=clause_around(text, match.start(), match.end()),
                paragraph=paragraph,
                role=role,
                label=label,
            )
        )

    for match in _AMOUNT_RE.finditer(text):
        if not free(match.start(), match.end()):
            continue
        occupied.append((match.start(), match.end()))
        number = parse_number(match.group("num"))
        unit = match.group("unit")
        if number is None:
            continue
        yuan = money_yuan(number, unit)
        if yuan is None:
            continue
        label = match.group("label")
        subject = apply_alias("amount", label, rules)
        found.append(
            _fact(
                family="amount",
                subject=subject,
                kind="assignment",
                display=f"{match.group('num')}{unit}",
                number=yuan,
                unit="元",
                unit_family="money",
                value_norm=f"{yuan:.2f}",
                quote=clause_around(text, match.start(), match.end()),
                paragraph=paragraph,
                role=role,
                label=label,
            )
        )

    for clause in split_clauses(text):
        name_match = _NAME_RE.search(clause)
        if name_match:
            raw_name = name_match.group(1).strip(" ：:，,。")
            if len(raw_name) >= 4:
                found.append(
                    _fact(
                        family="project_name",
                        subject="项目名称",
                        kind="assignment",
                        display=raw_name,
                        number=None,
                        unit=None,
                        unit_family=None,
                        value_norm=norm_space(raw_name),
                        quote=clause,
                        paragraph=paragraph,
                        role=role,
                        label="项目名称",
                    )
                )
        qual = _QUAL_RE.search(clause)
        if qual:
            body = qual.group("body").strip(" ，,")
            level = _LEVEL_RE.search(body)
            if level:
                value = level.group(0)
                specialty = body[: level.start()].strip("的")
            else:
                value = "（未分级）"
                specialty = body
            if specialty:
                found.append(
                    _fact(
                        family="qualification",
                        subject=f"资质:{norm_space(specialty)}",
                        kind="conditional" if _COND.search(clause) else "assignment",
                        display=value,
                        number=None,
                        unit=None,
                        unit_family=None,
                        value_norm=value,
                        quote=clause,
                        paragraph=paragraph,
                        role=role,
                        label=specialty,
                    )
                )
        if _REJECT.search(clause):
            found.append(
                _consortium(paragraph, role, clause, "不接受")
            )
        elif _ALLOW.search(clause):
            found.append(
                _consortium(paragraph, role, clause, "接受")
            )
        qty = _QTY_RE.search(clause)
        if qty:
            number = parse_number(qty.group("num"))
            unit = qty.group("unit")
            measured = measure(unit)
            if number is not None and measured:
                dimension, factor = measured
                base = number * factor
                found.append(
                    _fact(
                        family="quantity",
                        subject=f"采购项:{norm_space(qty.group('name'))}",
                        kind="assignment",
                        display=f"{qty.group('num')}{unit}",
                        number=base,
                        unit=unit,
                        unit_family=dimension,
                        value_norm=f"{dimension}:{base:.6f}",
                        quote=clause,
                        paragraph=paragraph,
                        role=role,
                        label=qty.group("name"),
                    )
                )
        spec = _SPEC_RE.search(clause)
        if spec:
            op = spec.group("op")
            if op in {"推荐", "推荐采用"}:
                continue
            number = float(spec.group("num"))
            unit = spec.group("unit")
            if op in {"约", "约为"}:
                kind = "approximate"
            elif op in {"不低于", "不小于", "不少于"}:
                kind = "minimum"
            elif op in {"不高于", "不大于", "不超过"}:
                kind = "maximum"
            else:
                kind = "assignment"
            name = spec.group("name")
            found.append(
                _fact(
                    family="spec",
                    subject=norm_space(name),
                    kind=kind,
                    display=f"{op}{spec.group('num')}{unit}",
                    number=number,
                    unit=unit,
                    unit_family=unit,
                    value_norm=f"{number:.6f}|{unit}",
                    quote=clause,
                    paragraph=paragraph,
                    role=role,
                    label=name,
                    operator=op,
                )
            )
    return found


def _consortium(paragraph: Paragraph, role: str, clause: str, value: str) -> Fact:
    kind = "conditional" if _COND.search(clause) else "assignment"
    return _fact(
        family="consortium",
        subject="联合体",
        kind=kind,
        display=value,
        number=None,
        unit=None,
        unit_family=None,
        value_norm=value,
        quote=clause,
        paragraph=paragraph,
        role=role,
        label="联合体",
    )


def _header_map(header: list[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for index, cell in enumerate(header):
        text = norm_space(cell).replace("（", "(").replace("）", ")")
        if not text:
            continue
        if ("名称" in text or text in {"项目", "货物", "设备"}) and "单价" not in text and "合价" not in text:
            found.setdefault("name", index)
        elif "数量" in text:
            found.setdefault("qty", index)
        elif text == "单位" or text.startswith("单位"):
            found.setdefault("unit", index)
        elif "合价" in text or "合计金额" in text:
            found.setdefault("amount", index)
    return found


def _blank_paragraph(table: Table, row_index: int, col_index: int, text: str) -> Paragraph:
    loc = Location(
        file_name=table.location.file_name,
        file_path=table.location.file_path,
        sha256=table.location.sha256,
        kind=table.location.kind,
        part=table.location.part,
        xml_path=f"{table.location.xml_path}/r[{row_index}]/c[{col_index}]",
        section_title=table.section_title,
        section_index=table.section_index,
        table_index=table.location.table_index,
        row=row_index,
        col=col_index,
        pdf_page=None,
    )
    return Paragraph(text=text, accepted_text=text, location=loc, in_table=True, section_title=table.section_title, section_index=table.section_index)


def extract_table_facts(table: Table, role: str, file_name: str) -> list[Fact]:
    if not table.rows:
        return []
    columns = _header_map(table.header)
    if "name" not in columns:
        return []
    context = f"{file_name} {table.preceding_heading} {table.section_title}"
    budget_context = "预算" in context or "报价" in context
    facts: list[Fact] = []
    name_i = columns["name"]
    for row_number, row in enumerate(table.rows[1:], start=2):
        if name_i >= len(row):
            continue
        name = row[name_i].strip()
        first = row[0].strip() if row else ""
        total_labels = {"合计", "总计", "预算合计", "小计"}
        if first in total_labels or name in total_labels:
            label = first if first in total_labels else name
        else:
            label = name
        if not label:
            continue
        paragraph = _blank_paragraph(table, row_number, name_i + 1, " ".join(row))
        paragraph.location.file_name = file_name
        if label in total_labels and "amount" in columns:
            amount_i = columns["amount"]
            if amount_i < len(row) and row[amount_i].strip():
                number = parse_number(row[amount_i])
                if number is not None:
                    subject = "预算合计" if budget_context or label == "预算合计" else f"表格合计:{table.section_title}"
                    facts.append(
                        _fact(
                            family="amount",
                            subject=subject,
                            kind="assignment",
                            display=f"{row[amount_i]}元",
                            number=number,
                            unit="元",
                            unit_family="money",
                            value_norm=f"{number:.2f}",
                            quote=f"{table.section_title} 第{row_number}行 {label} 合价 {row[amount_i]}元",
                            paragraph=paragraph,
                            role=role,
                            label=label,
                        )
                    )
            continue
        if "qty" not in columns or "unit" not in columns:
            continue
        qty_i = columns["qty"]
        unit_i = columns["unit"]
        if qty_i >= len(row) or unit_i >= len(row):
            continue
        qty_raw = row[qty_i].strip()
        unit = row[unit_i].strip()
        if not qty_raw or not unit:
            continue
        number = parse_number(qty_raw)
        measured = measure(unit)
        if number is None or measured is None:
            continue
        dimension, factor = measured
        base = number * factor
        facts.append(
            _fact(
                family="quantity",
                subject=f"采购项:{norm_space(name)}",
                kind="assignment",
                display=f"{qty_raw}{unit}",
                number=base,
                unit=unit,
                unit_family=dimension,
                value_norm=f"{dimension}:{base:.6f}",
                quote=f"{table.section_title} 第{row_number}行 {name} {qty_raw}{unit}",
                paragraph=paragraph,
                role=role,
                label=name,
            )
        )
    return facts


def extract_document_facts(doc: Document, rules: dict | None = None) -> list[Fact]:
    if doc.unreadable:
        return []
    facts: list[Fact] = []
    for paragraph in doc.paragraphs:
        if paragraph.in_table and doc.kind == "docx":
            # Row-oriented extraction handles table facts. Cell prose still
            # matters when a requirement is written inside a cell.
            text = paragraph.accepted_text.strip()
            if len(text) >= 8 and any(token in text for token in ("工期", "资质", "联合体", "项目名称", "万元", "不低于")):
                facts.extend(extract_text_facts(paragraph, doc.role, rules))
            continue
        facts.extend(extract_text_facts(paragraph, doc.role, rules))
    for table in doc.tables:
        facts.extend(extract_table_facts(table, doc.role, doc.file_name))
    return facts


def extract_precedence(docs: list[Document], rules: dict | None = None) -> Precedence | None:
    configured = [str(item).strip() for item in (rules or {}).get("precedence") or [] if str(item).strip()]
    if configured:
        return Precedence(labels=configured, quote="（用户规则指定的效力顺序）", location=None, source="用户规则")
    number_re = re.compile(r"^\s*(\d+|[一二三四五六七八九十]+)[\.、．]\s*(.+?)\s*$")
    for doc in docs:
        paragraphs = [p for p in doc.paragraphs if not p.in_table]
        for index, paragraph in enumerate(paragraphs):
            if "效力顺序" not in paragraph.accepted_text and "优先顺序" not in paragraph.accepted_text:
                continue
            labels: list[str] = []
            quotes = [paragraph.accepted_text.strip()]
            for follow in paragraphs[index : index + 12]:
                for line in follow.accepted_text.splitlines():
                    line = line.strip()
                    match = number_re.match(line)
                    if match:
                        labels.append(match.group(2).strip())
                        quotes.append(line)
                    elif labels and line and "效力顺序" not in line and "优先顺序" not in line:
                        # also accept a numbered item sharing the anchor paragraph
                        continue
            # Items may live in the same paragraph separated by newlines or
            # already be separate paragraphs. Also scan the anchor text.
            if len(labels) < 2:
                labels = []
                for line in paragraph.accepted_text.splitlines():
                    match = number_re.match(line.strip())
                    if match:
                        labels.append(match.group(2).strip())
                for follow in paragraphs[index + 1 : index + 12]:
                    matched_any = False
                    for line in follow.accepted_text.splitlines() or [follow.accepted_text]:
                        match = number_re.match(line.strip())
                        if match:
                            labels.append(match.group(2).strip())
                            matched_any = True
                    if not matched_any and labels:
                        break
            if len(labels) >= 2:
                return Precedence(
                    labels=labels,
                    quote="\n".join(quotes[:8]),
                    location=paragraph.location,
                    source=doc.file_name,
                )
    return None
