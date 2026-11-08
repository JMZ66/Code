"""Agent-facing reads. Responses are paged so a model does not receive the whole file."""

from __future__ import annotations

import json
import re
from pathlib import Path

from office_kit.checks import run_checks
from office_kit.diffing import diff_paths
from office_kit.edit import apply_edit, propose_edit
from office_kit.models import Document, to_plain
from office_kit.parse import parse_path
from office_kit.word import iter_tables

DEFAULT_LIMIT = 40
DEFAULT_CHARS = 8000
MAX_LIMIT = 200
MAX_CHARS = 20000


def parse_document(path: str | Path) -> dict:
    return parse_path(path).to_dict()


def document_outline(path: str | Path, *, offset: int = 0, limit: int = DEFAULT_LIMIT, max_chars: int = DEFAULT_CHARS) -> dict:
    document = parse_path(path)
    items = [_outline_row(item) for item in _outline(document)]
    page = _page(items, offset, limit, max_chars)
    return _head(document) | page


def read_paragraphs(
    path: str | Path,
    start: int = 0,
    end: int | None = None,
    *,
    max_chars: int = DEFAULT_CHARS,
) -> dict:
    document = parse_path(path)
    paragraphs = document.word.paragraphs if document.word else []
    stop = len(paragraphs) if end is None else end
    chosen = [to_plain(item) for item in paragraphs if start <= item.index < stop]
    page = _page(chosen, 0, len(chosen) or 1, max_chars)
    page["start"] = start
    page["end"] = stop
    return _head(document) | page


def read_section(
    path: str | Path,
    *,
    anchor: str | None = None,
    index: int = 0,
    max_chars: int = DEFAULT_CHARS,
    max_table_rows: int = 20,
) -> dict:
    document = parse_path(path)
    if document.excel is not None and document.word is None:
        return _excel_section(document, anchor, index, max_chars)
    outline = _outline(document)
    if not outline:
        return _head(document) | {"items": [], "truncated": False}
    if anchor:
        matches = [position for position, item in enumerate(outline) if item.anchor == anchor]
        if not matches:
            return _head(document) | {"error": f"大纲中没有锚点 {anchor}", "items": []}
        index = matches[0]
    if index < 0 or index >= len(outline):
        return _head(document) | {"error": "大纲序号超出范围", "items": []}
    current = outline[index]
    items = _section_items(document, outline, index, max_table_rows)
    page = _page(items, 0, len(items) or 1, max_chars)
    page["section"] = _outline_row(current)
    return _head(document) | page


def read_table(
    path: str | Path,
    *,
    anchor: str | None = None,
    index: int | None = None,
    row_offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    max_chars: int = DEFAULT_CHARS,
) -> dict:
    document = parse_path(path)
    tables = list(iter_tables(document.word.tables)) if document.word else []
    table = None
    if anchor:
        table = next((item for item in tables if item.anchor == anchor), None)
    elif index is not None and document.word is not None:
        table = next((item for item in document.word.tables if item.index == index), None)
    if table is None:
        return _head(document) | {"error": "没有匹配的表格", "items": []}
    rows = []
    for row_index, row in enumerate(table.rows):
        rows.append(
            {
                "row": row_index,
                "cells": [
                    {
                        "anchor": cell.anchor,
                        "text": cell.text,
                        "grid_span": cell.grid_span,
                        "v_merge": cell.v_merge,
                        "cover_origin": cell.cover_origin,
                        "nested_tables": [item.anchor for item in cell.nested_tables],
                    }
                    for cell in row
                ],
            }
        )
    page = _page(rows, row_offset, limit, max_chars)
    page["anchor"] = table.anchor
    page["coverage"] = table.coverage
    page["issues"] = table.issues
    return _head(document) | page


def read_cells(
    path: str | Path,
    sheet: str,
    cell_range: str,
    *,
    limit: int = 200,
    max_chars: int = DEFAULT_CHARS,
) -> dict:
    document = parse_path(path)
    if document.excel is None:
        return _head(document) | {"error": "不是工作簿", "items": []}
    target = next((item for item in document.excel.sheets if item.name == sheet or item.part == sheet), None)
    if target is None:
        return _head(document) | {"error": f"没有工作表 {sheet}", "items": []}
    bounds = _parse_range(cell_range)
    chosen = []
    for cell in target.cells:
        if bounds and not _inside(cell.row, cell.column, bounds):
            continue
        chosen.append(to_plain(cell))
    page = _page(chosen, 0, limit, max_chars)
    page["sheet"] = {"name": target.name, "state": target.state, "part": target.part, "merged_ranges": target.merged_ranges}
    page["range"] = cell_range
    return _head(document) | page


def search_document(
    path: str | Path,
    query: str,
    *,
    regex: bool = False,
    limit: int = 20,
    max_chars: int = DEFAULT_CHARS,
) -> dict:
    document = parse_path(path)
    if not query or len(query) > 200:
        return _head(document) | {"error": "查询需要 1 到 200 个字符", "items": []}
    try:
        matcher = re.compile(query) if regex else None
    except re.error as exc:
        return _head(document) | {"error": f"正则无法编译：{exc}", "items": []}
    hits = []
    for kind, anchor, text, extra in _search_corpus(document):
        span = _span(text, query, matcher)
        if span is None:
            continue
        hits.append({"kind": kind, "anchor": anchor, "snippet": _snippet(text, span), **extra})
        if len(hits) >= limit:
            break
    page = _page(hits, 0, limit, max_chars)
    page["query"] = query
    return _head(document) | page


def check_files(paths: list[str | Path], profile: dict | None = None, semantic=None) -> dict:
    documents = [parse_path(path) for path in paths]
    return run_checks(documents, profile=profile, semantic=semantic)


def diff_files(left: str | Path, right: str | Path, limit: int = 100) -> dict:
    return diff_paths(left, right, limit=limit)


def _outline(document: Document):
    if document.word is not None:
        return document.word.outline
    if document.excel is not None:
        from office_kit.models import OutlineItem

        return [
            OutlineItem(level=1, text=sheet.name, display=sheet.name, anchor=sheet.part, kind="sheet", state=sheet.state, paragraph_index=sheet.index)
            for sheet in document.excel.sheets
        ]
    return []


def _outline_row(item) -> dict:
    return to_plain(item)


def _section_items(document: Document, outline, index: int, max_table_rows: int) -> list[dict]:
    current = outline[index]
    paragraphs = {item.anchor: item for item in document.word.paragraphs}
    tables = {item.anchor: item for item in document.word.tables}
    start = None
    for position, block in enumerate(document.word.blocks):
        if block.get("anchor") == current.anchor:
            start = position
            break
    if start is None:
        return []
    items = []
    for block in document.word.blocks[start:]:
        if block.get("anchor") != current.anchor and block.get("type") == "paragraph":
            paragraph = paragraphs.get(block["anchor"])
            if paragraph and paragraph.heading_level and paragraph.heading_level <= current.level:
                break
        if block.get("type") == "paragraph":
            paragraph = paragraphs.get(block["anchor"])
            if paragraph is not None:
                items.append({"type": "paragraph", **_brief_paragraph(paragraph)})
        elif block.get("type") == "table":
            table = tables.get(block["anchor"])
            if table is not None:
                items.append(_brief_table(table, max_table_rows))
    return items


def _brief_paragraph(paragraph) -> dict:
    return {
        "anchor": paragraph.anchor,
        "index": paragraph.index,
        "number_label": paragraph.number_label,
        "heading_level": paragraph.heading_level,
        "text": paragraph.text_accepted,
        "text_original": paragraph.text_original,
        "style_id": paragraph.style_id,
        "section_index": paragraph.section_index,
    }


def _brief_table(table, max_rows: int) -> dict:
    rows = []
    for row in table.rows[:max_rows]:
        rows.append([{"anchor": cell.anchor, "text": cell.text, "grid_span": cell.grid_span, "v_merge": cell.v_merge} for cell in row])
    return {
        "type": "table",
        "anchor": table.anchor,
        "rows": rows,
        "row_count": len(table.rows),
        "truncated_rows": len(table.rows) > max_rows,
    }


def _excel_section(document: Document, anchor: str | None, index: int, max_chars: int) -> dict:
    sheets = document.excel.sheets
    if anchor:
        sheet = next((item for item in sheets if item.part == anchor or item.name == anchor), None)
    else:
        sheet = sheets[index] if 0 <= index < len(sheets) else None
    if sheet is None:
        return _head(document) | {"error": "没有匹配的工作表", "items": []}
    items = [to_plain(cell) for cell in sheet.cells]
    page = _page(items, 0, 100, max_chars)
    page["sheet"] = {
        "name": sheet.name,
        "state": sheet.state,
        "part": sheet.part,
        "merged_ranges": sheet.merged_ranges,
        "hidden_rows": sheet.hidden_rows,
        "hidden_columns": sheet.hidden_columns,
        "data_validations": sheet.data_validations,
        "comments": sheet.comments,
    }
    return _head(document) | page


def _search_corpus(document: Document):
    if document.word is not None:
        for paragraph in document.word.paragraphs:
            yield "paragraph", paragraph.anchor, paragraph.text_accepted, {"number_label": paragraph.number_label}
            if paragraph.text_original != paragraph.text_accepted:
                yield "paragraph_original", paragraph.anchor, paragraph.text_original, {"number_label": paragraph.number_label}
        for comment in document.word.comments:
            yield "comment", comment.anchor, comment.text, {"author": comment.author}
        for section in document.word.sections:
            for item in section.headers + section.footers:
                yield item.kind, f"{item.part}#section[{section.index}]", item.text, {"type": item.type}
    if document.excel is not None:
        for sheet in document.excel.sheets:
            for cell in sheet.cells:
                yield "cell", cell.anchor, cell.cached_text, {"sheet": sheet.name, "coordinate": cell.coordinate}
                if cell.formula:
                    yield "formula", cell.anchor, cell.formula, {"sheet": sheet.name, "coordinate": cell.coordinate}
                if cell.comment:
                    yield "comment", cell.anchor, cell.comment.get("text") or "", {"sheet": sheet.name}


def _span(text: str, query: str, matcher):
    if not text:
        return None
    if matcher is not None:
        found = matcher.search(text)
        return found.span() if found else None
    index = text.find(query)
    if index < 0:
        return None
    return index, index + len(query)


def _snippet(text: str, span: tuple[int, int]) -> str:
    start = max(0, span[0] - 40)
    end = min(len(text), span[1] + 40)
    prefix = "…" if start else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end] + suffix


def _parse_range(cell_range: str):
    text = cell_range.replace("$", "").upper()
    if ":" not in text:
        text = f"{text}:{text}"
    left, right = text.split(":", 1)
    try:
        r1, c1 = _split(left)
        r2, c2 = _split(right)
    except ValueError:
        return None
    return min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)


def _split(coordinate: str) -> tuple[int, int]:
    letters = "".join(char for char in coordinate if char.isalpha())
    digits = "".join(char for char in coordinate if char.isdigit())
    if not letters or not digits:
        raise ValueError(coordinate)
    column = 0
    for char in letters:
        column = column * 26 + (ord(char) - 64)
    return int(digits), column


def _inside(row: int, column: int, bounds) -> bool:
    r1, c1, r2, c2 = bounds
    return r1 <= row <= r2 and c1 <= column <= c2


def _head(document: Document) -> dict:
    return {
        "source": to_plain(document.source),
        "status": document.status,
        "kind": document.kind,
        "warnings": document.warnings,
        "features": document.features,
    }


def _page(items: list, offset: int, limit: int, max_chars: int) -> dict:
    offset = max(0, int(offset or 0))
    limit = min(max(1, int(limit or DEFAULT_LIMIT)), MAX_LIMIT)
    max_chars = min(max(500, int(max_chars or DEFAULT_CHARS)), MAX_CHARS)
    chosen = items[offset : offset + limit]
    payload = {
        "items": chosen,
        "offset": offset,
        "next_offset": offset + limit if offset + limit < len(items) else None,
        "total": len(items),
        "truncated": offset + limit < len(items),
    }
    while chosen and len(json.dumps(payload, ensure_ascii=False)) > max_chars:
        chosen = chosen[:-1]
        payload["items"] = chosen
        payload["truncated"] = True
        payload["next_offset"] = offset + len(chosen)
    return payload


__all__ = [
    "parse_document",
    "document_outline",
    "read_paragraphs",
    "read_section",
    "read_table",
    "read_cells",
    "search_document",
    "check_files",
    "diff_files",
    "propose_edit",
    "apply_edit",
]
