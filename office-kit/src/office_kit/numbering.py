"""Resolve Word list labels from ``word/numbering.xml``.

Counters follow the usual Word rules: a level restarts the deeper levels,
``startOverride`` replaces the level start, and ``w:isLgl`` prints every
placeholder in that label as a decimal. Omitted ``w:start`` is 0, matching
ECMA-376 (Word almost always writes the start explicitly).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

from office_kit.numbers import chinese_int
from office_kit.ooxml import attr, child, children_named, on_off

_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_PLACEHOLDER = re.compile(r"%(%|\d)")


def _letters(number: int, upper: bool) -> str:
    if number <= 0:
        return str(number)
    chars: list[str] = []
    value = number
    while value > 0:
        value -= 1
        chars.append(chr(ord("A") + value % 26))
        value //= 26
    text = "".join(reversed(chars))
    return text if upper else text.lower()


def _roman(number: int) -> str:
    if number <= 0 or number >= 4000:
        return str(number)
    pairs = (
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    )
    parts: list[str] = []
    value = number
    for weight, glyph in pairs:
        while value >= weight:
            parts.append(glyph)
            value -= weight
    return "".join(parts)


def format_number(number: int, num_fmt: str) -> tuple[str, bool]:
    """Return the formatted counter and whether the format was unrecognized."""

    fmt = num_fmt or "decimal"
    if fmt == "decimal":
        return str(number), False
    if fmt in {"chineseCounting", "chineseCountingThousand", "ideographDigital", "taiwaneseCounting"}:
        return chinese_int(number, legal=False), False
    if fmt in {"chineseLegalSimplified", "taiwaneseCountingThousand"}:
        return chinese_int(number, legal=True), False
    if fmt == "decimalEnclosedParen":
        return f"({number})", False
    if fmt == "decimalEnclosedFullstop":
        return f"{number}.", False
    if fmt == "decimalEnclosedCircle":
        if 1 <= number <= len(_CIRCLED):
            return _CIRCLED[number - 1], False
        return f"({number})", False
    if fmt == "upperRoman":
        return _roman(number), False
    if fmt == "lowerRoman":
        return _roman(number).lower(), False
    if fmt == "upperLetter":
        return _letters(number, True), False
    if fmt == "lowerLetter":
        return _letters(number, False), False
    if fmt in {"bullet", "none"}:
        return "", False
    return str(number), True


@dataclass
class LevelDef:
    ilvl: int
    start: int = 0
    num_fmt: str = "decimal"
    lvl_text: str = ""
    is_lgl: bool = False
    suffix: str = "tab"


def _read_level(node: etree._Element, ilvl: int) -> LevelDef:
    start_el = child(node, "start")
    start = int(attr(start_el, "val") or "0") if start_el is not None else 0
    fmt_el = child(node, "numFmt")
    text_el = child(node, "lvlText")
    suff_el = child(node, "suff")
    return LevelDef(
        ilvl=ilvl,
        start=start,
        num_fmt=attr(fmt_el, "val") or "decimal",
        lvl_text=attr(text_el, "val") or f"%{ilvl + 1}",
        is_lgl=bool(on_off(child(node, "isLgl"))),
        suffix=attr(suff_el, "val") or "tab",
    )


@dataclass
class Numbering:
    levels: dict[str, dict[int, LevelDef]] = field(default_factory=dict)
    counters: dict[str, dict[int, int]] = field(default_factory=dict)
    warnings: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def from_xml(cls, root: etree._Element | None) -> "Numbering":
        engine = cls()
        if root is None:
            return engine
        abstracts: dict[str, dict[int, LevelDef]] = {}
        for abstract in children_named(root, "abstractNum"):
            abstract_id = attr(abstract, "abstractNumId")
            if abstract_id is None:
                continue
            levels: dict[int, LevelDef] = {}
            for lvl in children_named(abstract, "lvl"):
                ilvl = int(attr(lvl, "ilvl") or "0")
                levels[ilvl] = _read_level(lvl, ilvl)
            abstracts[abstract_id] = levels
        for num in children_named(root, "num"):
            num_id = attr(num, "numId")
            abstract_id = attr(child(num, "abstractNumId"), "val")
            if num_id is None or abstract_id is None:
                continue
            levels = {ilvl: LevelDef(**vars(level)) for ilvl, level in abstracts.get(abstract_id, {}).items()}
            for override in children_named(num, "lvlOverride"):
                ilvl = int(attr(override, "ilvl") or "0")
                replacement = child(override, "lvl")
                if replacement is not None:
                    levels[ilvl] = _read_level(replacement, ilvl)
                start_override = child(override, "startOverride")
                if start_override is not None:
                    base = levels.get(ilvl) or LevelDef(ilvl=ilvl)
                    base.start = int(attr(start_override, "val") or "0")
                    levels[ilvl] = base
            engine.levels[num_id] = levels
        return engine

    def level(self, num_id: str, ilvl: int) -> LevelDef:
        defined = self.levels.get(num_id, {}).get(ilvl)
        if defined is not None:
            return defined
        return LevelDef(ilvl=ilvl, start=0, lvl_text=f"%{ilvl + 1}")

    def next_label(self, num_id: str, ilvl: int) -> str | None:
        if num_id in {None, "", "0"}:
            return None
        if num_id not in self.levels:
            self.warnings.append(
                {
                    "code": "missing_num",
                    "message": f"numbering.xml 中没有 numId={num_id}",
                }
            )
            return None
        state = self.counters.setdefault(num_id, {})
        for deeper in list(state):
            if deeper > ilvl:
                state[deeper] = self.level(num_id, deeper).start - 1
        current = self.level(num_id, ilvl)
        state[ilvl] = state.get(ilvl, current.start - 1) + 1
        for deeper in range(ilvl + 1, 9):
            state[deeper] = self.level(num_id, deeper).start - 1
        return self._render(num_id, ilvl)

    def suffix(self, num_id: str, ilvl: int) -> str:
        return self.level(num_id, ilvl).suffix

    def _render(self, num_id: str, ilvl: int) -> str:
        level = self.level(num_id, ilvl)
        if level.num_fmt == "bullet":
            return level.lvl_text
        if level.num_fmt == "none":
            return ""
        state = self.counters.get(num_id, {})

        def replace(match: re.Match[str]) -> str:
            token = match.group(1)
            if token == "%":
                return "%"
            index = int(token) - 1
            value = state.get(index)
            if value is None:
                value = self.level(num_id, index).start
            fmt = "decimal" if level.is_lgl else self.level(num_id, index).num_fmt
            rendered, unknown = format_number(value, fmt)
            if unknown:
                self.warnings.append(
                    {
                        "code": "numfmt_fallback",
                        "message": f"编号格式 {fmt} 未单独实现，已按十进制显示",
                    }
                )
            return rendered

        return _PLACEHOLDER.sub(replace, level.lvl_text)


def paragraph_numpr(p: etree._Element, style_chain: list) -> tuple[str, str] | None:
    """Direct ``numPr`` wins. ``numId`` 0 removes numbering inherited from a style."""

    p_pr = child(p, "pPr")
    direct = _read_numpr(p_pr)
    if direct is not None:
        if direct[0] == "0":
            return None
        return direct
    for style in style_chain:
        if style.num_id == "0":
            return None
        if style.num_id:
            return style.num_id, style.ilvl or "0"
    return None


def _read_numpr(p_pr: etree._Element | None) -> tuple[str, str] | None:
    num_pr = child(p_pr, "numPr")
    if num_pr is None:
        return None
    num_id = attr(child(num_pr, "numId"), "val")
    ilvl = attr(child(num_pr, "ilvl"), "val") or "0"
    if num_id is None:
        return None
    return num_id, ilvl
