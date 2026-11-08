"""Read-only XLSX reader. The workbook is never saved."""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from bidreview.models import Document, Location, SectionInfo, Table


def _cell_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def read_xlsx(path: Path, *, role: str, title: str, sha256: str) -> Document:
    doc = Document(
        path=str(path),
        file_name=path.name,
        role=role,
        title=title or path.stem,
        sha256=sha256,
        kind="xlsx",
    )
    try:
        workbook = load_workbook(path, read_only=True, data_only=False)
    except Exception as exc:
        doc.unreadable = f"XLSX 无法读取：{exc}"
        return doc
    try:
        for s_index, sheet in enumerate(workbook.worksheets):
            rows: list[list[str]] = []
            for row in sheet.iter_rows(values_only=True):
                rows.append([_cell_str(cell) for cell in row])
            while rows and not any(cell.strip() for cell in rows[-1]):
                rows.pop()
            header = [cell.strip() for cell in rows[0]] if rows else []
            loc = Location(
                file_name=path.name,
                file_path=str(path),
                sha256=sha256,
                kind="xlsx",
                part=f"xl/worksheets/sheet{s_index + 1}",
                xml_path=f"sheet[{sheet.title}]",
                section_title=sheet.title,
                section_index=s_index,
                table_index=s_index,
            )
            doc.tables.append(
                Table(
                    location=loc,
                    rows=rows,
                    header=header,
                    preceding_heading=sheet.title,
                    section_title=sheet.title,
                    section_index=s_index,
                )
            )
            doc.sections.append(SectionInfo(index=s_index, header_text=sheet.title))
            doc.headings.append((1, sheet.title, loc))
        doc.page_count = None
        return doc
    finally:
        workbook.close()
