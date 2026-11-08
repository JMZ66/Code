"""模板配置：JSON 配置，或从官方 Word 模板反推。"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from bid_review.parsers.docx_parser import parse_docx
from bid_review.hashutil import sha256_file


def _default_profile_path() -> Path:
    # 开发树：.../bid_review_assistant/config/...
    candidates = [
        Path(__file__).resolve().parents[3] / "config" / "default_template_profile.json",
        Path(__file__).resolve().parents[2] / "config" / "default_template_profile.json",
    ]
    # PyInstaller onedir
    import sys

    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates.insert(0, meipass / "config" / "default_template_profile.json")
        candidates.insert(1, Path(sys.executable).resolve().parent / "config" / "default_template_profile.json")
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def load_profile(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        path = _default_profile_path()
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def profile_from_template_docx(template_path: str | Path) -> dict[str, Any]:
    """从官方 Word 模板抽样反推格式要求（只读）。"""
    digest = sha256_file(template_path)
    doc = parse_docx(template_path, digest)

    body_fonts = Counter()
    body_sizes = Counter()
    body_spacing = Counter()
    h1_fonts = Counter()
    h1_sizes = Counter()
    h2_fonts = Counter()
    h2_sizes = Counter()

    for p in doc.paragraphs:
        if not p.text.strip():
            continue
        if p.is_heading and p.style:
            level = 1
            if "2" in p.style:
                level = 2
            if level == 1:
                if p.font_name:
                    h1_fonts[p.font_name] += 1
                if p.font_size_pt:
                    h1_sizes[p.font_size_pt] += 1
            else:
                if p.font_name:
                    h2_fonts[p.font_name] += 1
                if p.font_size_pt:
                    h2_sizes[p.font_size_pt] += 1
        else:
            if p.font_name:
                body_fonts[p.font_name] += 1
            if p.font_size_pt:
                body_sizes[p.font_size_pt] += 1
            if p.line_spacing:
                body_spacing[p.line_spacing] += 1

    margins = doc.page_margins[0] if doc.page_margins else {}
    required_sections = [s.name for s in doc.sections if s.level == 1][:12]

    return {
        "version": 1,
        "name": f"自模板反推:{Path(template_path).name}",
        "source_template": str(Path(template_path).resolve()),
        "source_sha256": digest,
        "body": {
            "font_name": _top(body_fonts, "宋体"),
            "font_size_pt": float(_top(body_sizes, 12.0)),
            "line_spacing": float(_top(body_spacing, 1.5)),
            "alignment": "justify",
        },
        "heading1": {
            "font_name": _top(h1_fonts, "黑体"),
            "font_size_pt": float(_top(h1_sizes, 16.0)),
            "bold": True,
        },
        "heading2": {
            "font_name": _top(h2_fonts, "黑体"),
            "font_size_pt": float(_top(h2_sizes, 14.0)),
            "bold": True,
        },
        "margins_cm": {
            "top": margins.get("top_cm", 2.54),
            "bottom": margins.get("bottom_cm", 2.54),
            "left": margins.get("left_cm", 3.17),
            "right": margins.get("right_cm", 3.17),
            "tolerance": 0.15,
        },
        "table": {"min_cols": 2, "require_header_row": True},
        "header_must_contain": [],
        "footer_must_contain": [],
        "required_sections": required_sections,
        "required_attachments": [],
        "placeholders": [
            "____",
            "待填写",
            "待补充",
            "XXX",
            "×××",
            "【请填写】",
            "TODO",
            "TBD",
            "占位",
            "此处填写",
        ],
    }


def _top(counter: Counter, default):
    if not counter:
        return default
    return counter.most_common(1)[0][0]
