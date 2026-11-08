"""XLSX reader: formulas and cached values, merges, hidden areas, notes, validation.

Formulas are not evaluated. ``cached_value`` is whatever the file stored.
A missing cache stays null instead of being invented.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter, range_boundaries

from office_kit.models import Document, ExcelBody, ExcelCell, Sheet, SourceInfo
from office_kit.ooxml import R, Package, attr, local, package_feature_codes

_TC = "http://schemas.microsoft.com/office/spreadsheetml/2018/threadedcomments"


def parse_xlsx(path: Path, sha256: str, *, size: int | None = None) -> Document:
    source = SourceInfo(
        path=str(path),
        filename=path.name,
        format="xlsx",
        sha256=sha256,
        size=size if size is not None else path.stat().st_size,
    )
    document = Document(source=source, kind="excel", status="ok", excel=ExcelBody())
    parts = _sheet_parts(path)
    cached = _cached_values(path)
    threaded = _threaded_by_sheet(path, parts)
    try:
        workbook = load_workbook(path, data_only=False, read_only=False)
    except Exception as exc:
        document.status = "error"
        document.warnings.append({"code": "xlsx_unreadable", "message": f"XLSX 无法读取：{exc}"})
        return document
    try:
        document.excel.defined_names = _defined_names(workbook)
        for index, worksheet in enumerate(workbook.worksheets):
            part = parts.get(worksheet.title) or f"xl/worksheets/sheet{index + 1}.xml"
            document.excel.sheets.append(
                _read_sheet(worksheet, index, part, cached.get(worksheet.title, {}), threaded.get(worksheet.title, []))
            )
    finally:
        workbook.close()
    features = set(package_feature_codes(_names(path)))
    if any(cell.formula for sheet in document.excel.sheets for cell in sheet.cells):
        features.add("formulas")
    if any(sheet.merged_ranges for sheet in document.excel.sheets):
        features.add("merged_cells")
    if any(sheet.data_validations for sheet in document.excel.sheets):
        features.add("data_validations")
    if any(sheet.comments for sheet in document.excel.sheets):
        features.add("comments")
    if any(sheet.state != "visible" or sheet.hidden_rows or sheet.hidden_columns for sheet in document.excel.sheets):
        features.add("hidden")
    document.features = sorted(features)
    if "calc_chain" in features or "formulas" in features:
        document.warnings.append(
            {
                "code": "formula_cache_only",
                "message": "公式只读取文件中的表达式和缓存结果，本工具不重新计算。",
            }
        )
    return document


def _names(path: Path) -> list[str]:
    with Package(path) as package:
        return list(package.names)


def _sheet_parts(path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    with Package(path) as package:
        root = package.xml("xl/workbook.xml")
        rels = package.rels("xl/workbook.xml")
        if root is None:
            return mapping
        for node in root.iter():
            if not isinstance(node.tag, str) or local(node) != "sheet":
                continue
            name = node.get("name")
            target = rels.get(attr(node, "id", R) or "")
            if name and target:
                mapping[name] = target
    return mapping


def _cached_values(path: Path) -> dict[str, dict[tuple[int, int], object]]:
    found: dict[str, dict[tuple[int, int], object]] = {}
    workbook = load_workbook(path, data_only=True, read_only=False)
    try:
        for worksheet in workbook.worksheets:
            cells = {}
            for (row, column), cell in getattr(worksheet, "_cells", {}).items():
                cells[(row, column)] = cell.value
            found[worksheet.title] = cells
    finally:
        workbook.close()
    return found


def _defined_names(workbook) -> list[dict]:
    rows = []
    try:
        values = workbook.defined_names.values()
    except Exception:
        return rows
    for item in values:
        rows.append(
            {
                "name": getattr(item, "name", ""),
                "attr": getattr(item, "attr_text", None),
                "value": getattr(item, "value", None),
            }
        )
    return rows


def _read_sheet(worksheet, index: int, part: str, cached: dict, threaded: list[dict]) -> Sheet:
    hidden_rows = sorted(int(key) for key, dim in worksheet.row_dimensions.items() if dim.hidden)
    hidden_columns, hidden_ranges = _hidden_columns(worksheet)
    hidden_row_set = set(hidden_rows)
    hidden_column_set = set(hidden_columns)
    merged_ranges = [str(item) for item in worksheet.merged_cells.ranges]
    merge_origin = _merge_origins(merged_ranges)
    validations = []
    for item in worksheet.data_validations.dataValidation:
        sqref = str(item.sqref)
        validations.append(
            {
                "anchor": f"{part}#validation:{sqref}",
                "sqref": sqref,
                "type": item.type,
                "operator": item.operator,
                "formula1": item.formula1,
                "formula2": item.formula2,
                "allow_blank": bool(item.allow_blank),
                "prompt": item.prompt,
                "prompt_title": item.promptTitle,
            }
        )
    comments: list[dict] = []
    cells: list[ExcelCell] = []
    for (row, column), cell in sorted(getattr(worksheet, "_cells", {}).items()):
        formula = _formula(cell.value)
        cached_value = cached.get((row, column))
        note = None
        if cell.comment is not None:
            note = {"kind": "note", "author": cell.comment.author or "", "text": cell.comment.text or ""}
            comments.append({"anchor": f"{part}#cell:{cell.coordinate}", **note})
        if formula is None and cached_value is None and note is None and cell.value is None:
            continue
        if formula is None and cell.value is None and cached_value is None and note is None:
            continue
        displayed = cached_value if formula else cell.value
        hyperlink = None
        if cell.hyperlink is not None:
            hyperlink = cell.hyperlink.target or cell.hyperlink.location
        cells.append(
            ExcelCell(
                anchor=f"{part}#cell:{cell.coordinate}",
                sheet=worksheet.title,
                coordinate=cell.coordinate,
                row=row,
                column=column,
                formula=formula,
                cached_value=_jsonable(displayed if formula else cell.value),
                cached_text=_text(displayed if formula else cell.value),
                data_type=cell.data_type,
                number_format=cell.number_format,
                font=_font(cell.font),
                fill=_fill(cell.fill),
                alignment=_alignment(cell.alignment),
                comment=note,
                hyperlink=hyperlink,
                hidden_row=row in hidden_row_set,
                hidden_column=get_column_letter(column) in hidden_column_set,
                merge_origin=merge_origin.get((row, column)),
            )
        )
    for item in threaded:
        comments.append(item)
        for cell in cells:
            if cell.coordinate == item.get("coordinate") and cell.comment is None:
                cell.comment = {"kind": "threaded", "author": item.get("author") or "", "text": item.get("text") or ""}
    state = worksheet.sheet_state or "visible"
    return Sheet(
        name=worksheet.title,
        index=index,
        state=state,
        part=part,
        dimension=worksheet.dimensions,
        merged_ranges=merged_ranges,
        hidden_rows=hidden_rows,
        hidden_columns=hidden_columns,
        hidden_column_ranges=hidden_ranges,
        data_validations=validations,
        comments=comments,
        cells=cells,
    )


def _formula(value) -> str | None:
    if isinstance(value, str) and value.startswith("="):
        return value
    text = getattr(value, "text", None)
    if text and not isinstance(value, str):
        rendered = str(text)
        return rendered if rendered.startswith("=") else f"={rendered}"
    return None


def _hidden_columns(worksheet) -> tuple[list[str], list[str]]:
    letters: list[str] = []
    ranges: list[str] = []
    for key, dim in worksheet.column_dimensions.items():
        if not dim.hidden:
            continue
        start = dim.min or column_index_from_string(key)
        end = dim.max or start
        if end < start:
            start, end = end, start
        if end - start > 256:
            ranges.append(f"{get_column_letter(start)}:{get_column_letter(end)}")
            continue
        letters.extend(get_column_letter(index) for index in range(start, end + 1))
    return sorted(set(letters), key=column_index_from_string), ranges


def _merge_origins(ranges: list[str]) -> dict[tuple[int, int], str]:
    origins: dict[tuple[int, int], str] = {}
    for ref in ranges:
        min_col, min_row, max_col, max_row = range_boundaries(ref)
        origin = f"{get_column_letter(min_col)}{min_row}"
        for row in range(min_row, max_row + 1):
            for column in range(min_col, max_col + 1):
                if (row, column) != (min_row, min_col):
                    origins[(row, column)] = origin
    return origins


def _font(font) -> dict:
    color = None
    if font is not None and font.color is not None and font.color.type == "rgb":
        color = str(font.color.rgb)
    elif font is not None and font.color is not None and font.color.type == "theme":
        color = f"theme:{font.color.theme}"
    return {
        "name": getattr(font, "name", None),
        "size": getattr(font, "size", None),
        "bold": bool(getattr(font, "bold", False)),
        "italic": bool(getattr(font, "italic", False)),
        "color": color,
    }


def _fill(fill) -> dict:
    color = None
    fg = getattr(fill, "fgColor", None)
    if fg is not None and getattr(fg, "type", None) == "rgb":
        color = str(fg.rgb)
    return {"pattern": getattr(fill, "patternType", None), "fg_color": color}


def _alignment(alignment) -> dict:
    return {
        "horizontal": getattr(alignment, "horizontal", None),
        "vertical": getattr(alignment, "vertical", None),
        "wrap_text": bool(getattr(alignment, "wrap_text", False)),
    }


def _jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value).strip()


def _threaded_by_sheet(path: Path, parts: dict[str, str]) -> dict[str, list[dict]]:
    """Best-effort read of Excel 365 threaded comments. Legacy notes come from openpyxl."""

    by_part: dict[str, list[dict]] = {}
    with Package(path) as package:
        people = _people(package)
        parsed: dict[str, list[dict]] = {}
        for name in package.names:
            if "threadedcomment" not in name.lower() or not name.endswith(".xml"):
                continue
            root = package.xml(name)
            if root is None:
                continue
            rows = []
            for index, node in enumerate(root.iter(f"{{{_TC}}}threadedComment")):
                ref = node.get("ref") or ""
                rows.append(
                    {
                        "kind": "threaded",
                        "author": people.get(node.get("personId") or "", ""),
                        "text": "".join(node.itertext()).strip(),
                        "coordinate": ref,
                        "anchor": f"{name}#threaded:{ref or index}",
                    }
                )
            parsed[name] = rows
        for sheet_part in set(parts.values()):
            for target in package.rels(sheet_part).values():
                if target in parsed:
                    by_part.setdefault(sheet_part, []).extend(parsed[target])
    grouped: dict[str, list[dict]] = {}
    for title, part in parts.items():
        grouped[title] = by_part.get(part, [])
    return grouped


def _people(package: Package) -> dict[str, str]:
    people: dict[str, str] = {}
    for name in package.names:
        if not name.endswith(".xml") or "person" not in name.lower():
            continue
        root = package.xml(name)
        if root is None:
            continue
        for node in root.iter():
            if not isinstance(node.tag, str):
                continue
            if local(node) != "person":
                continue
            person_id = node.get("id")
            display = node.get("displayName")
            if person_id and display:
                people[person_id] = display
    return people
