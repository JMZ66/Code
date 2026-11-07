"""Strict numeric parsing. Blank, NaN, infinity and thousands separators are rejected."""

from __future__ import annotations

import math
import re

from labuv.errors import LabError

_FLOAT = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


def parse_float(value, *, row=None, column=None, what="数值"):
    """Return a finite float without changing the caller's stored raw text.

    Integers and finite floats already parsed by Excel are accepted.
    Booleans, blanks, commas, percent signs and non-finite values are not.
    """
    if isinstance(value, bool) or value is None:
        raise LabError(f"{what}为空白或无效类型", row=row, column=column, code="blank")
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise LabError(f"{what}不是有限数", row=row, column=column, code="nonfinite")
        return number
    text = str(value).strip()
    if text == "":
        raise LabError(f"{what}为空白", row=row, column=column, code="blank")
    if not _FLOAT.fullmatch(text):
        raise LabError(
            f"{what}“{text}”无法作为十进制数读取。不接受千分位逗号、百分号或中文数字；"
            "百分数请把单位设为 %，数值仍写 99.5 这种形式。",
            row=row,
            column=column,
            code="invalid_number",
        )
    number = float(text)
    if not math.isfinite(number):
        raise LabError(f"{what}不是有限数", row=row, column=column, code="nonfinite")
    return number


def fmt(value, digits=8) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(number):
        return "NaN"
    if math.isinf(number):
        return "∞" if number > 0 else "-∞"
    return format(number, f".{digits}g")
