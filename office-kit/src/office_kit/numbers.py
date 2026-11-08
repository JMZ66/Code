"""Chinese numerals and money units.

The integer reader follows the same rules as ``bid-review`` in this
repository (MIT, unmerged review assistant): 万/亿 sections, 十/百/千,
and financial numerals. Months are not converted into days.
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

_COUNTING = "零一二三四五六七八九"
_LEGAL = "零壹贰叁肆伍陆柒捌玖"
_COUNTING_UNITS = "千百十"
_LEGAL_UNITS = "仟佰拾"


def parse_chinese_number(text: str) -> int | None:
    if not text or not _CN_RE.fullmatch(text):
        return None
    total = 0
    section = 0
    number = 0
    used = False
    for char in text:
        if char in _DIGITS:
            number = _DIGITS[char]
            used = True
        elif char in _SMALL:
            if number == 0:
                number = 1
            section += number * _SMALL[char]
            number = 0
            used = True
        elif char in _BIG:
            section += number
            if section == 0:
                section = 1
            total += section * _BIG[char]
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


def _four_digits(value: int, digits: str, units: str) -> str:
    parts: list[str] = []
    pending_zero = False
    divisors = (1000, 100, 10, 1)
    for index, divisor in enumerate(divisors):
        digit = value // divisor % 10
        if digit == 0:
            pending_zero = True
            continue
        if pending_zero and parts:
            parts.append(digits[0])
        pending_zero = False
        if index < 3:
            parts.append(digits[digit] + units[index])
        else:
            parts.append(digits[digit])
    return "".join(parts)


def chinese_int(number: int, *, legal: bool = False) -> str:
    """Format a positive integer the way Word ``chineseCounting`` does.

    10 is 十, not 一十. Interior zeros are kept (一百零一, 一万零一).
    """

    if number == 0:
        return "零"
    if number < 0:
        return "负" + chinese_int(-number, legal=legal)
    digits = _LEGAL if legal else _COUNTING
    units = _LEGAL_UNITS if legal else _COUNTING_UNITS
    big = ["", "万", "亿", "万亿"]
    groups: list[int] = []
    remaining = number
    while remaining:
        groups.append(remaining % 10000)
        remaining //= 10000
    parts: list[str] = []
    highest = len(groups) - 1
    for index in range(highest, -1, -1):
        group = groups[index]
        if group == 0:
            if parts and any(groups[:index]) and not parts[-1].endswith("零"):
                parts.append("零")
            continue
        text = _four_digits(group, digits, units)
        if index == highest and text.startswith(digits[1] + units[2]):
            text = text[1:]
        if parts and not parts[-1].endswith("零") and group < 1000 and index < highest:
            parts.append("零")
        unit = big[index] if index < len(big) else ""
        parts.append(text + unit)
    rendered = "".join(parts).replace("零零", "零")
    return rendered.strip("零") or "零"


def parse_chinese_money(text: str) -> float | None:
    """Read 壹佰贰拾伍万元整 / 贰佰元伍角 into yuan."""

    cleaned = text.strip()
    cleaned = cleaned.replace("人民币", "").replace("整", "").replace("正", "")
    cleaned = cleaned.replace("圆", "元").replace(" ", "")
    if not cleaned:
        return None
    if "元" in cleaned:
        left, right = cleaned.split("元", 1)
        amount = parse_chinese_number(left) if left else 0
        if amount is None:
            return None
        fraction = 0.0
        match = re.fullmatch(
            r"(?:([零一二三四五六七八九壹贰叁肆伍陆柒捌玖])角)?(?:([零一二三四五六七八九壹贰叁肆伍陆柒捌玖])分)?",
            right,
        )
        if right and match is None:
            return None
        if match:
            if match.group(1):
                fraction += _DIGITS[match.group(1)] * 0.1
            if match.group(2):
                fraction += _DIGITS[match.group(2)] * 0.01
        return float(amount) + fraction
    parsed = parse_chinese_number(cleaned)
    if parsed is None:
        return None
    return float(parsed)


_MONEY = {"元": 1.0, "万元": 10_000.0, "亿元": 100_000_000.0}


def money_to_yuan(number: float, unit: str | None) -> float | None:
    if unit is None:
        return None
    factor = _MONEY.get(unit)
    if factor is None:
        return None
    return number * factor


def amounts_close(left: float, right: float) -> bool:
    return abs(left - right) <= max(0.02, abs(left) * 1e-6)
