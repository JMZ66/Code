"""关键字段抽取：项目名称、工期、金额、数量、单位、技术指标、资质、联合体等。"""

from __future__ import annotations

import re
from dataclasses import replace

from bid_review.models import DocumentIndex, ExtractedField, SourceLoc

# 模式：(字段键, 中文名, 正则, 组)
FIELD_PATTERNS: list[tuple[str, str, str]] = [
    ("project_name", "项目名称", r"(?:项目名称|工程名称)[:：\s]*([^\n，。；;]{2,80})"),
    ("duration", "工期", r"(?:工期|建设工期|服务期|交货期)[:：\s]*([^\n，。；;]{1,40})"),
    (
        "duration",
        "工期",
        r"(?:合同签订后|签订合同后|供货安装|完成(?:供货|安装|交付))[^\n]{0,20}?(\d+\s*(?:个)?(?:日历)?天|\d+\s*个?月)",
    ),
    (
        "duration",
        "工期",
        r"(\d+\s*(?:个)?(?:日历)?天|\d+\s*个?月|\d+\s*个?工作日)(?=[^\n]{0,12}(?:完成|供货|安装|交付|工期))",
    ),
    (
        "amount",
        "金额",
        r"(?:合同金额|预算金额|最高限价|控制价|投标总价|预算金额|预算)[:：\s]*"
        r"(?:人民币)?\s*([¥￥]?\s*[\d,，.]+(?:\s*万元|\s*元)?|\d+(?:\.\d+)?\s*万元)",
    ),
    (
        "amount",
        "金额",
        r"(?:最高限价|合同金额)(?:[:：\s]*|为|人民币)*([¥￥]?\s*[\d,，.]+(?:\s*万元|\s*元)?|\d+(?:\.\d+)?\s*万元)",
    ),
    (
        "amount",
        "金额",
        r"最高限价(?:[:：\s]|人民币)*([¥￥]?\s*[\d,，.]+(?:\s*万元|\s*元)?|\d+(?:\.\d+)?\s*万元)",
    ),
    ("quantity", "数量", r"(?:数量|采购数量|工程量)[:：\s]*([\d,，.]+\s*[A-Za-z\u4e00-\u9fff%]*)"),
    ("unit", "计量单位", r"(?:计量单位|单位)[:：\s]*([^\n，。；;]{1,10})"),
    ("tech_spec", "技术指标", r"(?:技术指标|性能指标|规格要求)[:：\s]*([^\n]{2,120})"),
    ("qualification", "资质要求", r"(?:资质要求|资格要求|投标人资格)[:：\s]*([^\n]{2,160})"),
    ("consortium", "联合体限制", r"(?:联合体)([^\n]{0,40}(?:不接受|接受|不允许|允许)[^\n]{0,40})"),
    ("consortium", "联合体限制", r"((?:不)?(?:接受|允许)联合体投标[^\n]{0,40})"),
    ("delivery", "交货地点", r"(?:交货地点|服务地点|实施地点)[:：\s]*([^\n，。；;]{2,80})"),
    ("bid_bond", "保证金", r"(?:投标保证金|履约保证金)[:：\s]*([¥￥]?[\d,，.]+(?:\s*万元)?|\d+\s*万元|[^\n，。]{2,40})"),
]


CONDITION_HINTS = (
    "若",
    "如遇",
    "如果",
    "如经",
    "特殊情况",
    "不可抗力",
    "经批准",
    "经采购人批准",
    "延期",
    "试运行",
    "质保期",
    "质保内",
    "可选包",
    "备选方案",
    "分期",
    "阶段验收",
)


def extract_fields(docs: list[DocumentIndex]) -> list[ExtractedField]:
    fields: list[ExtractedField] = []
    for doc in docs:
        for text, loc in doc.all_text_blocks():
            # 保证金行不进入合同/预算金额
            if re.search(r"(投标保证金|履约保证金|保证金)", text) and not re.search(
                r"(合同金额|预算金额|最高限价|控制价|投标总价)", text
            ):
                patterns = [p for p in FIELD_PATTERNS if p[0] != "amount"]
            else:
                patterns = FIELD_PATTERNS
            condition = _extract_condition(text)
            for key, label, pattern in patterns:
                for m in re.finditer(pattern, text):
                    value = (m.group(1) if m.lastindex else m.group(0)).strip()
                    value = value.strip(" ：:，,。;；")
                    if not value or len(value) > 200:
                        continue
                    if key == "amount" and not _plausible_amount(value):
                        continue
                    # 工期延长/响应类：保留但必须带条件
                    if key == "duration" and any(x in text for x in ("延长", "响应", "调试期")):
                        if not condition:
                            condition = _extract_condition(text) or text[:80]
                    use_loc = loc
                    if doc.file_type == "pdf" and use_loc.pdf_page is None:
                        part = use_loc.ooxml_part or ""
                        if part.startswith("pdf:page:"):
                            try:
                                use_loc = replace(use_loc, pdf_page=int(part.split(":")[-1]))
                            except ValueError:
                                pass
                    fields.append(
                        ExtractedField(
                            key=key,
                            label=label,
                            value=value,
                            normalized=_normalize(key, value),
                            unit=_guess_unit(key, value),
                            condition=condition,
                            loc=use_loc,
                            confidence=0.75 if condition else 0.85,
                        )
                    )
        fields.extend(_extract_from_tables(doc))
    return _dedupe(fields)


def _extract_from_tables(doc: DocumentIndex) -> list[ExtractedField]:
    """从预算/清单表头语义抽取数量与金额。"""
    out: list[ExtractedField] = []
    for table in doc.tables:
        if not table.rows:
            continue
        header = [c.strip() for c in table.rows[0]]

        def col(*names: str) -> int | None:
            for i, h in enumerate(header):
                for n in names:
                    if n in h:
                        return i
            return None

        idx_name = col("名称", "货物", "项目")
        idx_qty = col("数量")
        idx_unit = col("单位")
        idx_sum = col("合价", "合计", "金额", "总价")
        for ri, row in enumerate(table.rows[1:], start=1):
            name = row[idx_name] if idx_name is not None and idx_name < len(row) else ""
            if idx_qty is not None and idx_qty < len(row) and row[idx_qty]:
                unit = row[idx_unit] if idx_unit is not None and idx_unit < len(row) else ""
                value = f"{row[idx_qty]}{unit}".strip()
                loc = SourceLoc(
                    filename=doc.filename,
                    file_type=doc.file_type,
                    sha256=doc.sha256,
                    section=table.section,
                    table_index=table.index,
                    row_index=ri,
                    cell_index=idx_qty,
                    excerpt=f"{name} {value}".strip()[:160],
                    sheet_name=table.section if doc.file_type == "xlsx" else "",
                )
                out.append(
                    ExtractedField(
                        key="quantity",
                        label="数量",
                        value=value,
                        normalized=_normalize("quantity", value),
                        unit=unit,
                        condition=f"清单项:{name}" if name else "",
                        loc=loc,
                        confidence=0.9,
                    )
                )
            if idx_sum is not None and idx_sum < len(row) and row[idx_sum]:
                raw = str(row[idx_sum])
                if re.fullmatch(r"[\d,，.]+", raw.replace(" ", "")):
                    loc = SourceLoc(
                        filename=doc.filename,
                        file_type=doc.file_type,
                        sha256=doc.sha256,
                        section=table.section,
                        table_index=table.index,
                        row_index=ri,
                        cell_index=idx_sum,
                        excerpt=f"{name} 合价:{raw}"[:160],
                        sheet_name=table.section if doc.file_type == "xlsx" else "",
                    )
                    out.append(
                        ExtractedField(
                            key="amount",
                            label="金额",
                            value=raw,
                            normalized=_normalize("amount", raw),
                            unit="元",
                            condition=f"清单项:{name}" if name else "",
                            loc=loc,
                            confidence=0.85,
                        )
                    )
        # 合计行
        for ri, row in enumerate(table.rows):
            if row and any("合计" in c for c in row):
                for ci, c in enumerate(row):
                    if re.fullmatch(r"[\d,，.]+", str(c).replace(" ", "")):
                        loc = SourceLoc(
                            filename=doc.filename,
                            file_type=doc.file_type,
                            sha256=doc.sha256,
                            section=table.section,
                            table_index=table.index,
                            row_index=ri,
                            cell_index=ci,
                            excerpt=f"合计 {c}"[:160],
                            sheet_name=table.section if doc.file_type == "xlsx" else "",
                        )
                        out.append(
                            ExtractedField(
                                key="amount",
                                label="金额",
                                value=str(c),
                                normalized=_normalize("amount", str(c)),
                                unit="元",
                                condition="预算合计",
                                loc=loc,
                                confidence=0.92,
                            )
                        )
    return out


def _extract_condition(text: str) -> str:
    for hint in CONDITION_HINTS:
        if hint in text:
            # 截取含条件的短句
            for part in re.split(r"[。；;]", text):
                if hint in part:
                    return part.strip()[:80]
    return ""


def _plausible_amount(value: str) -> bool:
    """拒绝明显误切的金额片段。"""
    v = value.replace(",", "").replace("，", "").replace(" ", "").replace("¥", "").replace("￥", "")
    if re.fullmatch(r"0+", v.replace("元", "").replace("万", "")):
        return False
    num = re.search(r"[\d.]+", v)
    if not num:
        return False
    raw = num.group()
    if raw.startswith("0") and raw != "0" and "." not in raw:
        return False
    try:
        amount = float(raw)
    except ValueError:
        return False
    if "万" in value:
        amount *= 10000
    # 招投标金额过小且无“万”多半是误抽（如从 120 里切出 20）
    if amount < 100 and "万" not in value and "元" not in value:
        return False
    return True


def _normalize(key: str, value: str) -> str:
    v = value.replace(",", "").replace("，", "").replace(" ", "")
    v = v.replace("￥", "").replace("¥", "").replace("元", "")
    if key == "amount":
        if "万" in value:
            num = re.search(r"[\d.]+", v)
            if num:
                try:
                    return str(float(num.group()) * 10000)
                except ValueError:
                    return v
        num = re.search(r"[\d.]+", v)
        if not num:
            return v
        # 过滤明显截断噪声（如从 1200000 误切出的 000）
        raw = num.group()
        if raw.startswith("0") and raw != "0" and "." not in raw:
            return v  # 交给上层去重；一致性侧再过滤
        return raw
    if key == "duration":
        # 统一到天
        m_month = re.search(r"(\d+(?:\.\d+)?)\s*个?月", value)
        if m_month:
            try:
                return str(int(float(m_month.group(1)) * 30))
            except ValueError:
                pass
        m_day = re.search(r"(\d+)\s*(?:个)?(?:日历)?天", value)
        if m_day:
            return m_day.group(1)
        m_work = re.search(r"(\d+)\s*个?工作日", value)
        if m_work:
            return f"workday:{m_work.group(1)}"
        return v
    if key == "quantity":
        num = re.search(r"[\d.]+", v)
        return num.group() if num else v
    if key == "consortium":
        if any(x in value for x in ("不接受", "不允许", "禁止")):
            return "forbidden"
        if any(x in value for x in ("接受", "允许")):
            return "allowed"
        return v
    return v


def _guess_unit(key: str, value: str) -> str:
    if key == "amount":
        if "万" in value:
            return "万元"
        if "元" in value or "¥" in value or "￥" in value:
            return "元"
    if key == "duration":
        if "月" in value:
            return "月"
        if "工作日" in value:
            return "工作日"
        if "天" in value:
            return "天"
    if key == "quantity":
        m = re.search(r"[\d.]+\s*([A-Za-z%\u4e00-\u9fff]{1,8})", value)
        if m:
            return m.group(1)
    return ""


def _dedupe(fields: list[ExtractedField]) -> list[ExtractedField]:
    seen: set[tuple] = set()
    out: list[ExtractedField] = []
    for f in fields:
        sig = (f.key, f.normalized, f.condition, f.loc.filename if f.loc else "", f.value)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(f)
    return out
