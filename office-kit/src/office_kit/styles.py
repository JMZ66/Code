"""Paragraph and run formatting, including East Asian fonts and themes.

Later layers win. Missing bold/italic become false. An explicit ``w:rFonts``
attribute wins over a theme token on the same axis. Table-style conditional
formatting is not applied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from lxml import etree

from office_kit.ooxml import A, attr, child, children_named, on_off

_FONT_ATTRS = (
    "ascii",
    "hAnsi",
    "eastAsia",
    "cs",
    "asciiTheme",
    "hAnsiTheme",
    "eastAsiaTheme",
    "cstheme",
)
_THEME_TO_SLOT = {
    "majorAscii": ("major", "latin"),
    "majorHAnsi": ("major", "latin"),
    "minorAscii": ("minor", "latin"),
    "minorHAnsi": ("minor", "latin"),
    "majorEastAsia": ("major", "ea"),
    "minorEastAsia": ("minor", "ea"),
    "majorBidi": ("major", "cs"),
    "minorBidi": ("minor", "cs"),
}
_HEADING_NAME = re.compile(r"(?:heading|标题)\s*(\d+)", re.IGNORECASE)


def read_rpr(r_pr: etree._Element | None) -> dict[str, Any]:
    if r_pr is None:
        return {}
    result: dict[str, Any] = {}
    fonts = child(r_pr, "rFonts")
    if fonts is not None:
        collected = {name: attr(fonts, name) for name in _FONT_ATTRS}
        result["fonts"] = {key: value for key, value in collected.items() if value is not None}
    bold = child(r_pr, "b")
    if bold is not None:
        result["bold"] = bool(on_off(bold))
    italic = child(r_pr, "i")
    if italic is not None:
        result["italic"] = bool(on_off(italic))
    size = child(r_pr, "sz")
    if size is not None and attr(size, "val"):
        result["size_pt"] = int(attr(size, "val") or "0") / 2
    underline = child(r_pr, "u")
    if underline is not None:
        result["underline"] = attr(underline, "val") or "single"
    color = child(r_pr, "color")
    if color is not None:
        value = attr(color, "val")
        theme = attr(color, "themeColor")
        result["color"] = value if value else (f"theme:{theme}" if theme else None)
    highlight = child(r_pr, "highlight")
    if highlight is not None:
        result["highlight"] = attr(highlight, "val")
    return result


def merge_format(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if key == "fonts" and isinstance(value, dict):
            fonts = dict(merged.get("fonts") or {})
            fonts.update(value)
            merged["fonts"] = fonts
        else:
            merged[key] = value
    return merged


def load_theme_fonts(root: etree._Element | None) -> dict[str, dict[str, str]]:
    fonts = {"major": {}, "minor": {}}
    if root is None:
        return fonts
    scheme = None
    for node in root.iter(f"{{{A}}}fontScheme"):
        scheme = node
        break
    if scheme is None:
        return fonts
    for kind, tag in (("major", "majorFont"), ("minor", "minorFont")):
        node = scheme.find(f"{{{A}}}{tag}")
        if node is None:
            continue
        for source, dest in (("latin", "latin"), ("ea", "ea"), ("cs", "cs")):
            item = node.find(f"{{{A}}}{source}")
            if item is not None and item.get("typeface"):
                fonts[kind][dest] = item.get("typeface") or ""
    return fonts


def finalize_format(raw: dict[str, Any], theme: dict[str, dict[str, str]]) -> dict[str, Any]:
    fonts = dict(raw.get("fonts") or {})

    def resolve(explicit: str, theme_attr: str) -> str | None:
        if fonts.get(explicit):
            return fonts[explicit]
        token = fonts.get(theme_attr)
        if not token:
            return None
        slot = _THEME_TO_SLOT.get(token)
        if slot is None:
            return None
        return theme.get(slot[0], {}).get(slot[1]) or None

    return {
        "ascii": fonts.get("ascii"),
        "h_ansi": fonts.get("hAnsi"),
        "east_asia": fonts.get("eastAsia"),
        "cs": fonts.get("cs"),
        "ascii_theme": fonts.get("asciiTheme"),
        "h_ansi_theme": fonts.get("hAnsiTheme"),
        "east_asia_theme": fonts.get("eastAsiaTheme"),
        "cs_theme": fonts.get("cstheme"),
        "resolved_ascii": resolve("ascii", "asciiTheme"),
        "resolved_h_ansi": resolve("hAnsi", "hAnsiTheme"),
        "resolved_east_asia": resolve("eastAsia", "eastAsiaTheme"),
        "resolved_cs": resolve("cs", "cstheme"),
        "size_pt": raw.get("size_pt"),
        "bold": bool(raw.get("bold", False)),
        "italic": bool(raw.get("italic", False)),
        "underline": raw.get("underline"),
        "color": raw.get("color"),
        "highlight": raw.get("highlight"),
    }


def effective_formatting(layers: list[dict[str, Any]], theme: dict[str, dict[str, str]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for layer in layers:
        merged = merge_format(merged, layer)
    return finalize_format(merged, theme)


@dataclass
class StyleInfo:
    style_id: str
    name: str
    style_type: str
    based_on: str | None = None
    is_default: bool = False
    outline_lvl: int | None = None
    num_id: str | None = None
    ilvl: str | None = None
    rpr: dict[str, Any] = field(default_factory=dict)


@dataclass
class StyleSet:
    styles: dict[str, StyleInfo] = field(default_factory=dict)
    doc_defaults: dict[str, Any] = field(default_factory=dict)
    default_paragraph_id: str | None = None

    @classmethod
    def from_xml(cls, root: etree._Element | None) -> "StyleSet":
        styleset = cls()
        if root is None:
            return styleset
        defaults = child(root, "docDefaults")
        r_default = child(child(defaults, "rPrDefault"), "rPr")
        styleset.doc_defaults = read_rpr(r_default)
        for node in children_named(root, "style"):
            style_id = attr(node, "styleId")
            if not style_id:
                continue
            info = StyleInfo(
                style_id=style_id,
                name=attr(child(node, "name"), "val") or style_id,
                style_type=attr(node, "type") or "paragraph",
                based_on=attr(child(node, "basedOn"), "val"),
                is_default=attr(node, "default") in {"1", "true", "on"},
                rpr=read_rpr(child(node, "rPr")),
            )
            p_pr = child(node, "pPr")
            outline = child(p_pr, "outlineLvl")
            if outline is not None and attr(outline, "val") is not None:
                info.outline_lvl = int(attr(outline, "val") or "0")
            num_pr = child(p_pr, "numPr")
            if num_pr is not None:
                info.num_id = attr(child(num_pr, "numId"), "val")
                info.ilvl = attr(child(num_pr, "ilvl"), "val") or "0"
            styleset.styles[style_id] = info
            if info.is_default and info.style_type == "paragraph":
                styleset.default_paragraph_id = style_id
        if styleset.default_paragraph_id is None and "Normal" in styleset.styles:
            styleset.default_paragraph_id = "Normal"
        return styleset

    def chain(self, style_id: str | None) -> list[StyleInfo]:
        found: list[StyleInfo] = []
        seen: set[str] = set()
        current = style_id
        while current and current not in seen and current in self.styles:
            seen.add(current)
            info = self.styles[current]
            found.append(info)
            current = info.based_on
        return found

    def public_styles(self) -> list[dict[str, Any]]:
        rows = []
        for info in self.styles.values():
            rows.append(
                {
                    "style_id": info.style_id,
                    "name": info.name,
                    "type": info.style_type,
                    "based_on": info.based_on,
                    "outline_lvl": info.outline_lvl,
                    "num_id": info.num_id,
                    "ilvl": info.ilvl,
                    "formatting": finalize_format(info.rpr, {"major": {}, "minor": {}}),
                }
            )
        return rows


def heading_level(p: etree._Element, chain: list[StyleInfo]) -> int | None:
    p_pr = child(p, "pPr")
    outline = child(p_pr, "outlineLvl")
    if outline is not None and attr(outline, "val") is not None:
        return int(attr(outline, "val") or "0") + 1
    for info in chain:
        if info.outline_lvl is not None:
            return info.outline_lvl + 1
    if chain:
        match = _HEADING_NAME.search(chain[0].name or "")
        if match:
            return int(match.group(1))
    return None
