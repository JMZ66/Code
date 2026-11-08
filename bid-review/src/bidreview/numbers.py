"""Number and unit normalization used by field comparison.

Months are not converted to days. That guess is left to a person.
"""

from __future__ import annotations

import re

_DIGITS = {
    "零": 0,
    "〇": 0,
    "○": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "壹": 1,
    "贰": 2,
    "叁": 3,
    "肆": 4,
    "伍": 5,
    "陆": 6,
    "柒": 7,
    "捌": 8,
    "玖": 9,
}
_SMALL = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
_BIG = {"万": 10_000, "亿": 100_000_000}
_CN_RE = re.compile(r"[零〇○一二三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟两]+")


def parse_chinese_number(text: str) -> int | None:
    if not text or not _CN_RE.fullmatch(text):
        return None
    total = 0
    section = 0
    number = 0
    used = False
    for ch in text:
        if ch in _DIGITS:
            number = _DIGITS[ch]
            used = True
        elif ch in _SMALL:
            if number == 0:
                number = 1
            section += number * _SMALL[ch]
            number = 0
            used = True
        elif ch in _BIG:
            section += number
            if section == 0:
                section = 1
            total += section * _BIG[ch]
            section = 0
            number = 0
            used = True
        else:
            return None
    if not used:
        return None
    return total + section + number


def parse_number(raw: str) -> float | None:
    text = raw.strip().replace(",", "").replace("，", "").replace(" ", "")
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)
    parsed = parse_chinese_number(text)
    if parsed is None:
        return None
    return float(parsed)


# dimension, multiplier into the base unit
_MEASURES: dict[str, tuple[str, float]] = {
    "毫米": ("length", 0.001),
    "厘米": ("length", 0.01),
    "米": ("length", 1.0),
    "千米": ("length", 1000.0),
    "公里": ("length", 1000.0),
    "台": ("count:台", 1.0),
    "套": ("count:套", 1.0),
    "卷": ("count:卷", 1.0),
    "个": ("count:个", 1.0),
    "项": ("count:项", 1.0),
    "根": ("count:根", 1.0),
    "只": ("count:只", 1.0),
    "张": ("count:张", 1.0),
    "块": ("count:块", 1.0),
    "组": ("count:组", 1.0),
}

_DURATION = {
    "日历天": "day",
    "天": "day",
    "工作日": "workday",
    "个月": "month",
    "月": "month",
    "年": "year",
}

_MONEY = {"元": 1.0, "万元": 10000.0, "亿元": 100_000_000.0}


def measure(unit: str) -> tuple[str, float] | None:
    return _MEASURES.get(unit)


def duration_family(unit: str) -> str | None:
    return _DURATION.get(unit)


def money_yuan(number: float, unit: str) -> float | None:
    factor = _MONEY.get(unit)
    if factor is None:
        return None
    return number * factor


def norm_space(text: str) -> str:
    return re.sub(r"\s+", "", text or "")
