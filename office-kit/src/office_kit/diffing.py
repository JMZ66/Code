"""Part hashes plus anchored text differences. This is not a Word redline."""

from __future__ import annotations

import zipfile
from pathlib import Path

from office_kit.models import to_plain
from office_kit.ooxml import part_hashes
from office_kit.parse import parse_path


def diff_paths(left: str | Path, right: str | Path, limit: int = 100) -> dict:
    left_path = Path(left)
    right_path = Path(right)
    left_doc = parse_path(left_path)
    right_doc = parse_path(right_path)
    changes = _text_changes(left_doc, right_doc)
    truncated = len(changes) > limit
    return {
        "left": to_plain(left_doc.source) | {"status": left_doc.status},
        "right": to_plain(right_doc.source) | {"status": right_doc.status},
        "parts": _part_diff(left_path, right_path),
        "changes": changes[:limit],
        "total_changes": len(changes),
        "truncated": truncated,
        "note": "按锚点对齐。若插入或删除了段落，后续锚点会整段显示为新增或删除，而不是按句子重新配对。",
    }


def _part_diff(left: Path, right: Path) -> dict:
    try:
        left_parts = part_hashes(left)
        right_parts = part_hashes(right)
    except zipfile.BadZipFile:
        return {"available": False, "reason": "至少有一侧不是 OOXML 压缩包，未做部件哈希比对。"}
    added = sorted(set(right_parts) - set(left_parts))
    removed = sorted(set(left_parts) - set(right_parts))
    modified = sorted(name for name in left_parts.keys() & right_parts.keys() if left_parts[name] != right_parts[name])
    return {
        "available": True,
        "added": added,
        "removed": removed,
        "modified": modified,
        "unchanged": len(left_parts) - len(removed) - len(modified),
    }


def _text_changes(left, right) -> list[dict]:
    changes = []
    if left.word is not None and right.word is not None:
        changes.extend(_by_anchor(
            {item.anchor: item.text_accepted for item in left.word.paragraphs},
            {item.anchor: item.text_accepted for item in right.word.paragraphs},
            "paragraph",
        ))
    if left.excel is not None and right.excel is not None:
        left_cells = {cell.anchor: _cell_label(cell) for sheet in left.excel.sheets for cell in sheet.cells}
        right_cells = {cell.anchor: _cell_label(cell) for sheet in right.excel.sheets for cell in sheet.cells}
        changes.extend(_by_anchor(left_cells, right_cells, "cell"))
    return changes


def _cell_label(cell) -> str:
    formula = cell.formula or ""
    return f"{formula}=>{cell.cached_text}" if formula else cell.cached_text


def _by_anchor(left: dict[str, str], right: dict[str, str], kind: str) -> list[dict]:
    changes = []
    for anchor in left:
        if anchor not in right:
            changes.append({"op": "removed", "kind": kind, "anchor": anchor, "left": left[anchor], "right": None})
        elif left[anchor] != right[anchor]:
            changes.append({"op": "modified", "kind": kind, "anchor": anchor, "left": left[anchor], "right": right[anchor]})
    for anchor in right:
        if anchor not in left:
            changes.append({"op": "added", "kind": kind, "anchor": anchor, "left": None, "right": right[anchor]})
    return changes
