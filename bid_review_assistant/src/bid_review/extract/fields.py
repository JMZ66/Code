"""从招标材料中抽取关键字段（规则 + 上下文，不编造）。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bid_review.models import DocumentIndex, ExtractedField, Location

# 文件名暗示的效力顺序（越高越权威）
AUTHORITY_HINTS = (
    ("合同", 90),
    ("招标文件", 85),
    ("招标公告", 80),
    ("技术", 70),
    ("规格", 70),
    ("预算", 65),
    ("清单", 65),
    ("答疑", 60),
    ("附件", 55),
)


def _authority(filename: str, section: str) -> int:
    score = 50
    blob = filename + " " + section
    for key, val in AUTHORITY_HINTS:
        if key in blob:
            score = max(score, val)
    return score


def _normalize_amount(raw: str) -> str:
    s = raw.replace(",", "").replace("，", "").replace(" ", "")
    s = s.replace("人民币", "").replace("元整", "").replace("元", "")
    s = s.replace("万元", "*10000")
    # 中文数字简单处理留给人工；此处仅规范化阿拉伯数字
    m = re.search(r"(\d+(?:\.\d+)?)(?:\*10000)?", s)
    if not m:
        return s
    val = float(m.group(1))
    if "*10000" in s:
        val *= 10000
    if val.is_integer():
        return str(int(val))
    return f"{val:.2f}"


def _normalize_duration(raw: str) -> str:
    s = raw.replace(" ", "")
    # 统一为天
    m = re.search(r"(\d+(?:\.\d+)?)\s*个?月", s)
    if m:
        days = float(m.group(1)) * 30
        return f"{int(days)}天"
    m = re.search(r"(\d+)\s*天", s)
    if m:
        return f"{int(m.group(1))}天"
    m = re.search(r"(\d+)\s*日", s)
    if m:
        return f"{int(m.group(1))}天"
    m = re.search(r"(\d+)\s*日历天", s)
    if m:
        return f"{int(m.group(1))}天"
    return s


def _normalize_qty_unit(raw: str) -> tuple[str, str]:
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*(台|套|个|件|项|米|m|㎡|平方米|吨|kg|千克|升|L|套件)",
        raw,
        re.I,
    )
    if not m:
        return raw, ""
    qty, unit = m.group(1), m.group(2)
    unit_map = {
        "平方米": "㎡",
        "m": "米",
        "千克": "kg",
        "L": "升",
        "l": "升",
    }
    unit = unit_map.get(unit, unit)
    if "." in qty:
        qty = str(float(qty))
    else:
        qty = str(int(qty))
    return qty, unit


def _detect_conditions(text: str) -> list[str]:
    conditions: list[str] = []
    patterns = [
        r"若[^，。；]{2,40}",
        r"如[^，。；]{2,40}",
        r"在[^，。；]{2,30}情况下",
        r"不含[^，。；]{1,20}",
        r"含[^，。；]{1,20}",
        r"联合体[^，。；]{0,30}",
        r"单一来源[^，。；]{0,20}",
        r"暂估价[^，。；]{0,20}",
        r"可选[^，。；]{0,20}",
        r"备选[^，。；]{0,20}",
        r"调试期[^，。；]{0,20}",
        r"质保期[^，。；]{0,20}",
        r"交货期[^，。；]{0,20}",
        r"工期[^，。；]{0,30}",
    ]
    for p in patterns:
        for m in re.finditer(p, text):
            conditions.append(m.group(0))
    return conditions[:5]


@dataclass
class FieldRule:
    key: str
    label: str
    pattern: str
    group: int = 1
    normalize: str = "text"  # text | amount | duration | qty


FIELD_RULES: list[FieldRule] = [
    FieldRule("project_name", "项目名称", r"(?:项目名称|工程名称)[:：\s]*([^\n，。；]{2,80})"),
    FieldRule("project_name", "项目名称", r"关于(.+?)的招标"),
    FieldRule(
        "duration",
        "工期",
        r"(?:工期|建设工期|施工工期|交货期|供货期|服务期限)[:：为是]?\s*"
        r"([^\n，。；]{0,10}?(?:\d+(?:\.\d+)?)\s*(?:个?月|天|日|日历天)[^\n，。；]{0,20})",
        normalize="duration",
    ),
    FieldRule(
        "duration",
        "工期",
        r"(?:工期|交货期)[^。\n]{0,20}?(\d+)\s*(?:天|日历天|日)",
        normalize="duration",
    ),
    FieldRule(
        "amount",
        "金额",
        r"(?:预算金额|最高限价|招标控制价|合同金额|总价|金额)[:：为是]?\s*"
        r"(人民币)?\s*([0-9,，]+(?:\.\d+)?)\s*(万元|元)?",
        group=2,
        normalize="amount",
    ),
    FieldRule(
        "amount",
        "金额",
        r"(人民币)\s*([0-9,，]+(?:\.\d+)?)\s*(万元|元)",
        group=2,
        normalize="amount",
    ),
    FieldRule(
        "quantity",
        "数量",
        r"(?:数量|采购数量|工程量)[:：为是]?\s*(\d+(?:\.\d+)?\s*(?:台|套|个|件|项|米|㎡|平方米|吨|kg|千克)?)",
        normalize="qty",
    ),
    FieldRule(
        "unit",
        "计量单位",
        r"(?:计量单位|单位)[:：为是]?\s*([台套个件项米㎡吨kg升]+)",
    ),
    FieldRule(
        "tech_spec",
        "技术指标",
        r"(?:技术指标|技术要求|性能指标)[:：为是]?\s*([^\n]{4,120})",
    ),
    FieldRule(
        "qualification",
        "资质要求",
        r"(?:资质要求|投标人资格|资格条件)[:：为是]?\s*([^\n]{4,160})",
    ),
    FieldRule(
        "consortium",
        "联合体限制",
        r"(本项目(不)?接受联合体投标[^\n。；]*)",
        group=1,
    ),
    FieldRule(
        "consortium",
        "联合体限制",
        r"((?:允许|禁止|不接受|接受)联合体[^\n。；]*)",
        group=1,
    ),
]


def _normalize_value(rule: FieldRule, raw: str, full_match: str) -> str:
    if rule.normalize == "amount":
        # 带上单位上下文
        unit = ""
        if "万元" in full_match:
            unit = "万元"
        blob = raw + unit
        return _normalize_amount(blob)
    if rule.normalize == "duration":
        return _normalize_duration(raw)
    if rule.normalize == "qty":
        qty, unit = _normalize_qty_unit(raw)
        return f"{qty}{unit}" if unit else qty
    return raw.strip()


def extract_fields(docs: list[DocumentIndex]) -> list[ExtractedField]:
    fields: list[ExtractedField] = []
    for doc in docs:
        for block in doc.blocks:
            text = block.text.strip()
            if not text:
                continue
            for rule in FIELD_RULES:
                for m in re.finditer(rule.pattern, text):
                    try:
                        raw = m.group(rule.group)
                    except IndexError:
                        raw = m.group(0)
                    raw = raw.strip().strip("：:。；;")
                    if not raw:
                        continue
                    norm = _normalize_value(rule, raw, m.group(0))
                    conf = 0.7
                    if rule.key in text[:20] or any(
                        k in text for k in ("项目名称", "工期", "预算", "资质", "联合体")
                    ):
                        conf = 0.85
                    fields.append(
                        ExtractedField(
                            key=rule.key,
                            label=rule.label,
                            value=raw,
                            normalized=norm,
                            location=Location(
                                filename=block.location.filename,
                                file_type=block.location.file_type,
                                section=block.location.section,
                                paragraph_index=block.location.paragraph_index,
                                table_index=block.location.table_index,
                                row_index=block.location.row_index,
                                cell_index=block.location.cell_index,
                                page=block.location.page,
                                xpath_hint=block.location.xpath_hint,
                                sheet=block.location.sheet,
                                excerpt=text[:240],
                            ),
                            confidence=conf,
                            context=text[:300],
                            conditions=_detect_conditions(text),
                            source_authority=_authority(
                                block.location.filename, block.location.section
                            ),
                        )
                    )
    return fields
