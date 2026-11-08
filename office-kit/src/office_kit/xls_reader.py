"""Legacy .xls reader via xlrd.

xlrd 2.0 exposes cached cell values, merges and row/column/sheet visibility
when ``formatting_info=True``. It does not expose formula text, comments or
data validation. Those limits are reported once on the document.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import xlrd

from office_kit.models import Document, ExcelBody, ExcelCell, Sheet, SourceInfo
from office_kit.ooxml import col_letter

_VISIBILITY = {0: "visible", 1: "hidden", 2: "veryHidden"}


def parse_xls(path: Path, sha256: str, *, size: int | None = None) -> Document:
    source = SourceInfo(
        path=str(path),
        filename=path.name,
        format="xls",
        sha256=sha256,
        size=size if size is not None else path.stat().st_size,
    )
    document = Document(source=source, kind="excel", status="ok", excel=ExcelBody())
    formatting = True
    try:
        book = xlrd.open_workbook(str(path), formatting_info=True)
    except TypeError:
        formatting = False
        book = xlrd.open_workbook(str(path))
        document.warnings.append(
            {
                "code": "xls_formatting_unavailable",
                "message": "当前 xlrd 不能读取 .xls 的格式信息，合并单元格和隐藏行列会缺失。",
            }
        )
    except Exception as exc:
        document.status = "error"
        document.warnings.append({"code": "xls_unreadable", "message": f"XLS 无法读取：{exc}"})
        return document
    document.warnings.append(
        {
            "code": "xls_limited",
            "message": "xls 只读取缓存值和基础格式。公式文本、批注和数据有效性在 xlrd 中不可用，未当作空值以外的事实。",
        }
    )
    for index in range(book.nsheets):
        sheet = book.sheet_by_index(index)
        document.excel.sheets.append(_read_sheet(book, sheet, index, formatting))
    features = ["xls"]
    if any(item.merged_ranges for item in document.excel.sheets):
        features.append("merged_cells")
    if any(item.state != "visible" or item.hidden_rows or item.hidden_columns for item in document.excel.sheets):
        features.append("hidden")
    document.features = features
    return document


def _read_sheet(book, sheet, index: int, formatting: bool) -> Sheet:
    hidden_rows: list[int] = []
    hidden_columns: list[str] = []
    merged: list[str] = []
    if formatting:
        hidden_rows = sorted(row + 1 for row, info in sheet.rowinfo_map.items() if info.hidden)
        hidden_columns = sorted(
            (col_letter(col + 1) for col, info in sheet.colinfo_map.items() if info.hidden),
            key=lambda item: len(item) * 26 + ord(item[-1]),
        )
        for rlo, rhi, clo, chi in sheet.merged_cells:
            start = f"{col_letter(clo + 1)}{rlo + 1}"
            end = f"{col_letter(chi)}{rhi}"
            merged.append(start if start == end else f"{start}:{end}")
    hidden_row_set = set(hidden_rows)
    hidden_column_set = set(hidden_columns)
    cells: list[ExcelCell] = []
    part = f"xls/{sheet.name}"
    for row in range(sheet.nrows):
        for column in range(sheet.ncols):
            cell = sheet.cell(row, column)
            if cell.ctype in {xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK}:
                continue
            value = _value(book, cell)
            text = _text(value)
            if text == "" and cell.ctype != xlrd.XL_CELL_BOOLEAN:
                continue
            number_format, font = _format(book, cell) if formatting else (None, {})
            coordinate = f"{col_letter(column + 1)}{row + 1}"
            cells.append(
                ExcelCell(
                    anchor=f"{part}#cell:{coordinate}",
                    sheet=sheet.name,
                    coordinate=coordinate,
                    row=row + 1,
                    column=column + 1,
                    formula=None,
                    cached_value=value,
                    cached_text=text,
                    data_type=_type_name(cell.ctype),
                    number_format=number_format,
                    font=font,
                    hidden_row=(row + 1) in hidden_row_set,
                    hidden_column=col_letter(column + 1) in hidden_column_set,
                )
            )
    return Sheet(
        name=sheet.name,
        index=index,
        state=_VISIBILITY.get(getattr(sheet, "visibility", 0), "visible"),
        part=part,
        merged_ranges=merged,
        hidden_rows=hidden_rows,
        hidden_columns=hidden_columns,
        cells=cells,
    )


def _value(book, cell):
    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            return xlrd.xldate_as_datetime(cell.value, book.datemode).isoformat()
        except Exception:
            return cell.value
    if cell.ctype == xlrd.XL_CELL_NUMBER:
        if isinstance(cell.value, float) and cell.value.is_integer():
            return int(cell.value)
        return cell.value
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return bool(cell.value)
    if cell.ctype == xlrd.XL_CELL_ERROR:
        return None
    return cell.value


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value).strip()


def _format(book, cell) -> tuple[str | None, dict]:
    try:
        xf = book.xf_list[cell.xf_index]
        font = book.font_list[xf.font_index]
        fmt = book.format_map.get(xf.format_key)
        number_format = getattr(fmt, "format_str", None)
        return number_format, {
            "name": font.name,
            "bold": bool(font.bold),
            "italic": bool(font.italic),
            "size_pt": (font.height / 20) if font.height else None,
        }
    except Exception:
        return None, {}


def _type_name(ctype: int) -> str:
    return {
        xlrd.XL_CELL_TEXT: "text",
        xlrd.XL_CELL_NUMBER: "number",
        xlrd.XL_CELL_DATE: "date",
        xlrd.XL_CELL_BOOLEAN: "boolean",
        xlrd.XL_CELL_ERROR: "error",
    }.get(ctype, "unknown")
