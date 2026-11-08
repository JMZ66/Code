"""Deterministic cross-file checks for tender documents.

Every finding cites evidence. ``origin`` is ``source`` here. A semantic
provider may add findings, but those are rewritten to ``origin=inference``
and dropped when they have no location.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from office_kit.models import Document, Evidence, Finding, to_plain
from office_kit.numbers import amounts_close, money_to_yuan, parse_chinese_money, parse_number
from office_kit.semantic import normalize_inference
from office_kit.word import iter_tables

DEFINITE = "确定错误"
SUSPECT = "疑似冲突"
MISSING = "缺少依据"
HUMAN = "需要人工判断"

_LABELS = (
    "投标总价",
    "投标报价",
    "报价合计",
    "合同总价",
    "合同金额",
    "含税总价",
    "不含税总价",
    "清单合计",
    "开标价",
    "暂估价",
    "质保金",
    "保证金",
)
_LABEL_RE = re.compile(
    "(" + "|".join(_LABELS) + r")\s*[:：为]?\s*(?:人民币|RMB|￥|¥)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(亿元|万元|元)?"
)
_NUMBER_RE = re.compile(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(亿元|万元|元)")
_CAPITAL_RE = re.compile(
    r"大写\s*[:：]?\s*([零〇○一二三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟元圆角分整正两]+)"
)
_CLAUSE_RE = re.compile(r"^(第[0-9一二三四五六七八九十百千万两]+条)|(\d+(?:\.\d+)+)")
_COUNT_THRESHOLD = re.compile(
    r"(同类业绩|类似业绩|类似项目业绩|业绩).{0,40}?(?:不少于|不低于|至少|≥|>=)\s*([0-9]+|[一二三四五六七八九十两]+)\s*(?:个|项|份)"
)
_SCORE_EACH = re.compile(
    r"(同类业绩|类似业绩|业绩).{0,60}?每(?:提供|增加|有)?\s*([0-9]+|[一二三四五六七八九十两]+)\s*个.{0,40}?([0-9]+(?:\.[0-9]+)?)\s*分"
)
_ROLE = "项目经理|技术负责人|安全负责人|质量负责人|施工负责人"
_CERT = "一级建造师|二级建造师|注册建造师|高级工程师|中级工程师|助理工程师|注册监理工程师|注册造价工程师|PMP|安全生产考核合格证|A证|B证|C证"
_ROLE_CERT = re.compile(rf"({_ROLE}).{{0,40}}?({_CERT})")
_CERT_ROLE = re.compile(rf"({_CERT}).{{0,40}}?({_ROLE})")
_ROLES = [
    ("requirement", ("招标要求", "技术要求", "规范要求", "采购需求")),
    ("response", ("投标响应", "投标人响应", "响应情况", "响应值", "响应")),
    ("param", ("参数名称", "技术参数", "指标名称", "参数")),
    ("qty", ("工程量", "数量")),
    ("price", ("综合单价", "单价")),
    ("amount", ("合计金额", "合价", "金额")),
    ("cert", ("资格证书", "执业资格", "资格", "证书", "职称")),
    ("role", ("拟任职务", "担任职务", "职务", "岗位", "角色")),
    ("person", ("姓名",)),
    ("name", ("项目名称", "设备名称", "子目名称", "名称")),
]
_UNITS = ("m³/h", "m3/h", "mm", "cm", "km", "mpa", "kpa", "kw", "mw", "m", "%")
_CONSTRAINT = re.compile(
    r"(>=|<=|>|<|不少于|不低于|不小于|不大于|不超过|至少)\s*([0-9]+(?:\.[0-9]+)?)"
)
_RANGE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*[~～至]\s*([0-9]+(?:\.[0-9]+)?)")


@dataclass
class _Report:
    findings: list[Finding] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)

    def add(self, **kwargs) -> None:
        evidence = kwargs.pop("evidence")
        self.findings.append(Finding(id="", evidence=evidence, **kwargs))


def run_checks(documents: list[Document], profile: dict | None = None, semantic=None) -> dict:
    profile = profile or {}
    disabled = set(profile.get("disabled_rules") or [])
    report = _Report()
    usable = []
    for document in documents:
        if document.status != "ok":
            message = "；".join(item.get("message", "") for item in document.warnings) or document.status
            report.add(
                rule_id="input.unparsed",
                severity="info",
                origin="source",
                category=MISSING,
                message=f"{document.source.filename} 未能解析（{document.status}）：{message}",
                evidence=[
                    Evidence(
                        source_path=document.source.path,
                        sha256=document.source.sha256,
                        anchor="",
                        quote=message[:240],
                        part="",
                    )
                ],
                details={"status": document.status},
            )
            continue
        usable.append(document)
    if "amount.capital" not in disabled:
        _capitals(usable, report)
    if "amount.line" not in disabled or "amount.total" not in disabled:
        _amounts(usable, report, disabled)
    if "amount.cross_file" not in disabled:
        _cross_amounts(usable, report, profile.get("compare_labels") or [])
    if "param.compare" not in disabled:
        _params(usable, report)
    if "threshold.vs_scoring" not in disabled:
        _thresholds(usable, report)
    if "personnel.qualification" not in disabled:
        _personnel(usable, report)
    if "clause.consistency" not in disabled:
        _clauses(usable, report, int(profile.get("clause_limit") or 50))
    normalize_inference(semantic, usable, report)
    for index, finding in enumerate(report.findings, start=1):
        finding.id = f"F{index:03d}"
    return {
        "origin_note": "origin=source 的发现来自文件中的文字、表格或单元格；origin=inference 的发现是外部推断，不是源文事实。",
        "documents": [
            {
                "path": document.source.path,
                "filename": document.source.filename,
                "sha256": document.source.sha256,
                "format": document.source.format,
                "status": document.status,
            }
            for document in documents
        ],
        "findings": [to_plain(item) for item in report.findings],
        "warnings": report.warnings,
    }


def _ev(document: Document, anchor: str, quote: str) -> Evidence:
    part = anchor.split("#", 1)[0] if anchor else ""
    text = re.sub(r"\s+", " ", quote or "").strip()
    if len(text) > 240:
        text = text[:240] + "…"
    return Evidence(
        source_path=document.source.path,
        sha256=document.source.sha256,
        anchor=anchor,
        quote=text,
        part=part,
    )


def _canon(label: str, groups: list) -> str:
    for group in groups:
        if label in group and group:
            return group[0]
    return label


def _capitals(documents: list[Document], report: _Report) -> None:
    for document in documents:
        if document.word is None:
            continue
        for paragraph in document.word.paragraphs:
            text = paragraph.text_accepted
            capital = _CAPITAL_RE.search(text)
            if capital is None:
                continue
            expected = parse_chinese_money(capital.group(1))
            numbers = list(_NUMBER_RE.finditer(text[: capital.start()]))
            if expected is None or not numbers:
                continue
            last = numbers[-1]
            actual = money_to_yuan(parse_number(last.group(1)) or 0, last.group(2))
            if actual is None or amounts_close(actual, expected):
                continue
            report.add(
                rule_id="amount.capital",
                severity="error",
                origin="source",
                category=DEFINITE,
                message=f"大写金额 {expected:g} 元与前文数字 {actual:g} 元不一致。",
                evidence=[_ev(document, paragraph.anchor, text)],
                details={"arabic_yuan": actual, "capital_yuan": expected},
            )


def _cross_amounts(documents: list[Document], report: _Report, groups: list) -> None:
    found: dict[str, list[tuple]] = {}
    for document in documents:
        if document.word is not None:
            for paragraph in document.word.paragraphs:
                for match in _LABEL_RE.finditer(paragraph.text_accepted):
                    _store_amount(found, groups, document, paragraph.anchor, paragraph.text_accepted, match)
        if document.excel is None:
            continue
        for sheet in document.excel.sheets:
            by_row: dict[int, list] = {}
            for cell in sheet.cells:
                by_row.setdefault(cell.row, []).append(cell)
            for row in by_row.values():
                ordered = sorted(row, key=lambda item: item.column)
                for cell in ordered:
                    label = _label_only(cell.cached_text)
                    if label is None:
                        continue
                    neighbor = _neighbor_number(ordered, cell)
                    if neighbor is None:
                        continue
                    key = _canon(label, groups)
                    found.setdefault(key, []).append(
                        (
                            document,
                            cell.anchor,
                            f"{cell.cached_text} {neighbor[0]:g}",
                            neighbor[0],
                            neighbor[1],
                        )
                    )
    for label, rows in found.items():
        valued = [row for row in rows if row[3] is not None]
        if len(valued) < 2:
            continue
        explicit = [row for row in valued if not row[4]]
        explicit_conflict = len(explicit) >= 2 and not all(
            amounts_close(explicit[0][3], row[3]) for row in explicit[1:]
        )
        any_conflict = not all(amounts_close(valued[0][3], row[3]) for row in valued[1:])
        if not explicit_conflict and not any_conflict:
            continue
        if explicit_conflict:
            severity, category, suffix = "error", DEFINITE, "。"
        else:
            severity, category, suffix = "warning", SUSPECT, "。其中至少一处没有写明单位，已按元参与比较。"
        report.add(
            rule_id="amount.cross_file",
            severity=severity,
            origin="source",
            category=category,
            message=f"“{label}”在不同位置的金额不一致："
            + "、".join(f"{row[3]:g}元" for row in valued)
            + suffix,
            evidence=[_ev(row[0], row[1], row[2]) for row in valued],
            details={"label": label, "yuan": [row[3] for row in valued], "unit_assumed": [row[4] for row in valued]},
        )


def _store_amount(found, groups, document, anchor, quote, match) -> None:
    label = match.group(1)
    number = parse_number(match.group(2))
    unit = match.group(3)
    if number is None:
        return
    assumed = unit is None
    yuan = number if assumed else money_to_yuan(number, unit)
    if yuan is None:
        return
    found.setdefault(_canon(label, groups), []).append((document, anchor, quote, yuan, assumed))


def _label_only(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text or "")
    compact = re.sub(r"[:：为]+$", "", compact)
    for label in _LABELS:
        if compact == label:
            return label
    return None


def _neighbor_number(row: list, cell) -> tuple[float, bool] | None:
    for other in row:
        if other.column <= cell.column:
            continue
        number = parse_number(other.cached_text.replace("元", "").replace("万元", "").replace("亿元", ""))
        if number is None:
            continue
        if "万元" in other.cached_text:
            return money_to_yuan(number, "万元"), False
        if "亿元" in other.cached_text:
            return money_to_yuan(number, "亿元"), False
        return number, "元" not in other.cached_text
    return None


def _amounts(documents: list[Document], report: _Report, disabled: set[str]) -> None:
    for document in documents:
        for matrix in _matrices(document):
            header_index = None
            mapping = None
            for index, row in enumerate(matrix[:15]):
                roles = _header_roles([text for text, _anchor in row])
                if {"qty", "price", "amount"} <= set(roles):
                    header_index = index
                    mapping = roles
                    break
            if header_index is None or mapping is None:
                continue
            lines = []
            for row in matrix[header_index + 1 :]:
                texts = [text for text, _anchor in row]
                if not any(texts):
                    continue
                if _is_total(texts):
                    if "amount.total" in disabled:
                        continue
                    amount = _num(texts[mapping["amount"]]) if mapping["amount"] < len(texts) else None
                    if amount is None or not lines:
                        continue
                    total = sum(lines)
                    if not amounts_close(total, amount):
                        anchor = row[mapping["amount"]][1]
                        report.add(
                            rule_id="amount.total",
                            severity="error",
                            origin="source",
                            category=DEFINITE,
                            message=f"合计 {amount:g} 与明细合价之和 {total:g} 不一致。",
                            evidence=[_ev(document, anchor, " ".join(texts))],
                            details={"total": amount, "sum": total},
                        )
                    continue
                qty = _num(texts[mapping["qty"]]) if mapping["qty"] < len(texts) else None
                price = _num(texts[mapping["price"]]) if mapping["price"] < len(texts) else None
                amount = _num(texts[mapping["amount"]]) if mapping["amount"] < len(texts) else None
                if qty is None or price is None or amount is None:
                    continue
                lines.append(amount)
                expected = qty * price
                if "amount.line" in disabled or amounts_close(expected, amount):
                    continue
                anchor = row[mapping["amount"]][1]
                report.add(
                    rule_id="amount.line",
                    severity="error",
                    origin="source",
                    category=DEFINITE,
                    message=f"数量 {qty:g} × 单价 {price:g} = {expected:g}，合价为 {amount:g}。",
                    evidence=[_ev(document, anchor, " ".join(texts))],
                    details={"qty": qty, "price": price, "expected": expected, "amount": amount},
                )


def _params(documents: list[Document], report: _Report) -> None:
    for document in documents:
        for matrix in _matrices(document):
            header_index, mapping = _find_header(matrix, {"param", "requirement"})
            if mapping is None or "response" not in mapping:
                continue
            for row in matrix[header_index + 1 :]:
                texts = [text for text, _anchor in row]
                if mapping["param"] >= len(texts):
                    continue
                name = texts[mapping["param"]].strip()
                if not name or name in {"参数", "参数名称"}:
                    continue
                requirement = texts[mapping["requirement"]] if mapping["requirement"] < len(texts) else ""
                response = texts[mapping["response"]] if mapping["response"] < len(texts) else ""
                if not requirement.strip() or not response.strip():
                    continue
                constraint = _constraint(requirement)
                if constraint is None:
                    continue
                actual, actual_unit = _first_number(response)
                if actual is None:
                    continue
                op, expected, req_unit = constraint
                if req_unit and actual_unit and req_unit.casefold() != actual_unit.casefold():
                    report.add(
                        rule_id="param.compare",
                        severity="info",
                        origin="source",
                        category=HUMAN,
                        message=f"参数“{name}”的单位不一致（要求 {req_unit}，响应 {actual_unit}），未自动判断合格。",
                        evidence=[
                            _ev(document, row[mapping["requirement"]][1], requirement),
                            _ev(document, row[mapping["response"]][1], response),
                        ],
                        details={"name": name},
                    )
                    continue
                if _satisfies(op, actual, expected):
                    continue
                report.add(
                    rule_id="param.compare",
                    severity="error",
                    origin="source",
                    category=DEFINITE,
                    message=f"参数“{name}”的响应 {actual:g} 不满足要求 {requirement.strip()}。",
                    evidence=[
                        _ev(document, row[mapping["requirement"]][1], requirement),
                        _ev(document, row[mapping["response"]][1], response),
                    ],
                    details={"name": name, "actual": actual, "expected": expected, "op": op},
                )


def _thresholds(documents: list[Document], report: _Report) -> None:
    thresholds = []
    scores = []
    for document in documents:
        paragraphs = document.word.paragraphs if document.word else []
        for paragraph in paragraphs:
            text = paragraph.text_accepted
            for match in _COUNT_THRESHOLD.finditer(text):
                number = parse_number(match.group(2))
                if number is None:
                    continue
                thresholds.append((document, paragraph.anchor, text, number))
            for match in _SCORE_EACH.finditer(text):
                step = parse_number(match.group(2))
                points = parse_number(match.group(3))
                if step is None or points is None:
                    continue
                scores.append((document, paragraph.anchor, text, step, points))
    if not thresholds or not scores:
        return
    minimum = min(item[3] for item in thresholds)
    for score in scores:
        if score[3] >= minimum:
            continue
        threshold = min(thresholds, key=lambda item: item[3])
        report.add(
            rule_id="threshold.vs_scoring",
            severity="warning",
            origin="source",
            category=SUSPECT,
            message=(
                f"业绩门槛为不少于 {minimum:g} 个，评分从每 {score[3]:g} 个起计分。"
                "计分起点低于资格门槛，可能使未达门槛的业绩仍得分。这是规则匹配，不是法律结论。"
            ),
            evidence=[
                _ev(threshold[0], threshold[1], threshold[2]),
                _ev(score[0], score[1], score[2]),
            ],
            details={"threshold": minimum, "score_step": score[3], "points": score[4]},
        )
        return


def _personnel(documents: list[Document], report: _Report) -> None:
    requirements = []
    seen = set()
    for document in documents:
        paragraphs = document.word.paragraphs if document.word else []
        for paragraph in paragraphs:
            text = paragraph.text_accepted
            pairs = [(m.group(1), m.group(2)) for m in _ROLE_CERT.finditer(text)]
            pairs += [(m.group(2), m.group(1)) for m in _CERT_ROLE.finditer(text)]
            for role, cert in pairs:
                if (role, cert) in seen:
                    continue
                seen.add((role, cert))
                requirements.append((document, paragraph.anchor, text, role, cert))
    if not requirements:
        return
    rows = []
    for document in documents:
        for matrix in _matrices(document):
            header_index, mapping = _find_header(matrix, {"role", "cert"})
            if mapping is None:
                continue
            for row in matrix[header_index + 1 :]:
                texts = [text for text, _anchor in row]
                role_text = texts[mapping["role"]] if mapping["role"] < len(texts) else ""
                cert_text = texts[mapping["cert"]] if mapping["cert"] < len(texts) else ""
                if not role_text.strip():
                    continue
                anchor = row[mapping["cert"]][1] if mapping["cert"] < len(row) else row[0][1]
                rows.append((document, anchor, role_text, cert_text, " ".join(texts)))
    for document, anchor, quote, role, cert in requirements:
        matched = [row for row in rows if role in row[2]]
        if not rows:
            report.add(
                rule_id="personnel.qualification",
                severity="info",
                origin="source",
                category=MISSING,
                message=f"要求{role}具备{cert}，但文件中没有人员资格表，无法核对。",
                evidence=[_ev(document, anchor, quote)],
                details={"role": role, "cert": cert},
            )
            continue
        if not matched:
            report.add(
                rule_id="personnel.qualification",
                severity="error",
                origin="source",
                category=DEFINITE,
                message=f"要求{role}具备{cert}，人员表中没有该岗位。",
                evidence=[_ev(document, anchor, quote)] + [_ev(row[0], row[1], row[4]) for row in rows[:3]],
                details={"role": role, "cert": cert},
            )
            continue
        if any(cert in row[3] or cert in row[4] for row in matched):
            continue
        report.add(
            rule_id="personnel.qualification",
            severity="error",
            origin="source",
            category=DEFINITE,
            message=f"{role}的资格要求是{cert}，人员表对应行未出现该资格。",
            evidence=[_ev(document, anchor, quote)] + [_ev(row[0], row[1], row[4]) for row in matched],
            details={"role": role, "cert": cert},
        )


def _clauses(documents: list[Document], report: _Report, limit: int) -> None:
    grouped: dict[tuple[str, str], list] = {}
    for document in documents:
        if document.word is None:
            continue
        for paragraph in document.word.paragraphs:
            if paragraph.in_table or paragraph.heading_level:
                continue
            parsed = _clause(paragraph.text_accepted)
            if parsed is None:
                continue
            label, body = parsed
            if len(_norm(body)) < 8:
                continue
            h1 = ""
            for item in paragraph.heading_path:
                if item.get("level") == 1:
                    h1 = _norm(item.get("text") or "")
                    break
            grouped.setdefault((h1, label), []).append((document, paragraph.anchor, paragraph.text_accepted, _norm(body)))
    emitted = 0
    for (h1, label), rows in grouped.items():
        bodies = {row[3] for row in rows}
        if len(rows) < 2 or len(bodies) < 2:
            continue
        report.add(
            rule_id="clause.consistency",
            severity="warning",
            origin="source",
            category=SUSPECT,
            message=f"条款 {label} 在同一级标题下的正文不一致。",
            evidence=[_ev(row[0], row[1], row[2]) for row in rows],
            details={"label": label, "heading": h1},
        )
        emitted += 1
        if emitted >= limit:
            report.warnings.append({"code": "clause_limit", "message": f"条款比对已达到上限 {limit} 条。"})
            return


def _clause(text: str) -> tuple[str, str] | None:
    normalized = text.strip().replace("．", ".")
    match = _CLAUSE_RE.match(normalized)
    if match is None:
        return None
    label = match.group(0)
    body = normalized[match.end() :].lstrip(" .、:：")
    return label, body


def _norm(text: str) -> str:
    text = re.sub(r"\s+", "", text or "")
    return text.translate(str.maketrans({"，": ",", "。": ".", "：": ":", "；": ";", "（": "(", "）": ")", "、": ","}))


def _matrices(document: Document):
    if document.word is not None:
        for table in iter_tables(document.word.tables):
            matrix = []
            for row in table.rows:
                matrix.append([(cell.text, cell.anchor) for cell in row])
            if matrix:
                yield matrix
    if document.excel is None:
        return
    for sheet in document.excel.sheets:
        matrix = _sheet_matrix(sheet)
        if matrix:
            yield matrix


def _sheet_matrix(sheet) -> list[list[tuple[str, str]]]:
    if not sheet.cells:
        return []
    by_row: dict[int, dict[int, object]] = {}
    width = 1
    for cell in sheet.cells:
        by_row.setdefault(cell.row, {})[cell.column] = cell
        width = max(width, cell.column)
    matrix = []
    for row_index in range(1, max(by_row) + 1):
        row = []
        for column in range(1, width + 1):
            cell = by_row.get(row_index, {}).get(column)
            if cell is None:
                row.append(("", f"{sheet.part}#cell:{_coord(column, row_index)}"))
            else:
                row.append((cell.cached_text, cell.anchor))
        matrix.append(row)
    return matrix


def _coord(column: int, row: int) -> str:
    letters = []
    value = column
    while value:
        value, remainder = divmod(value - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters)) + str(row)


def _header_roles(texts: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, text in enumerate(texts):
        compact = re.sub(r"\s+", "", text or "")
        if not compact:
            continue
        for role, synonyms in _ROLES:
            if role in mapping:
                continue
            if any(synonym in compact for synonym in synonyms):
                mapping[role] = index
                break
    return mapping


def _find_header(matrix, required: set[str]):
    for index, row in enumerate(matrix[:15]):
        mapping = _header_roles([text for text, _anchor in row])
        if required <= set(mapping):
            return index, mapping
    return None, None


def _is_total(texts: list[str]) -> bool:
    head = "".join(texts[:2])
    return "合计" in head or "小计" in head


def _num(text: str) -> float | None:
    if text is None:
        return None
    match = re.search(r"-?[0-9][0-9,]*(?:\.[0-9]+)?", text.replace("，", ","))
    if match is None:
        return None
    return parse_number(match.group(0))


def _constraint(text: str):
    compact = (
        text.replace(" ", "")
        .replace("＞", ">")
        .replace("＜", "<")
        .replace("≥", ">=")
        .replace("≤", "<=")
    )
    match = _CONSTRAINT.search(compact)
    if match:
        op = match.group(1)
        if op in {"不少于", "不低于", "不小于", "至少"}:
            op = ">="
        elif op in {"不大于", "不超过"}:
            op = "<="
        return op, float(match.group(2)), _unit(text)
    ranged = _RANGE.search(compact)
    if ranged:
        return "range", (float(ranged.group(1)), float(ranged.group(2))), _unit(text)
    return None


def _unit(text: str) -> str | None:
    compact = (text or "").replace(" ", "").casefold()
    for unit in sorted(_UNITS, key=len, reverse=True):
        if unit.casefold() in compact:
            return unit
    return None


def _first_number(text: str) -> tuple[float | None, str | None]:
    match = re.search(r"[0-9]+(?:\.[0-9]+)?", text.replace(",", "").replace("，", ""))
    if match is None:
        return None, None
    return float(match.group(0)), _unit(text)


def _satisfies(op, actual, expected) -> bool:
    if op == "range":
        low, high = expected
        return low - 1e-9 <= actual <= high + 1e-9
    if op == ">=":
        return actual + 1e-9 >= expected
    if op == "<=":
        return actual - 1e-9 <= expected
    if op == ">":
        return actual > expected
    if op == "<":
        return actual < expected
    return False
