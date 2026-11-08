"""只读 XLSX 解析：工作表、单元格与表格结构。"""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from bid_review.integrity import sha256_file
from bid_review.models import Block, DocumentIndex, Location, TableInfo


def read_xlsx(path: str | Path) -> DocumentIndex:
    p = Path(path).resolve()
    # read_only + data_only 保证不写回；不启用 keep_vba 写操作
    wb = load_workbook(filename=str(p), read_only=True, data_only=True)
    filename = p.name
    blocks: list[Block] = []
    tables: list[TableInfo] = []
    sections: list[str] = []

    for sheet_i, ws in enumerate(wb.worksheets):
        sections.append(ws.title)
        rows_data: list[list[str]] = []
        for ri, row in enumerate(ws.iter_rows(values_only=True)):
            row_cells: list[str] = []
            for ci, value in enumerate(row):
                if value is None:
                    cell_text = ""
                else:
                    cell_text = str(value).strip()
                row_cells.append(cell_text)
                if not cell_text:
                    continue
                loc = Location(
                    filename=filename,
                    file_type="xlsx",
                    section=ws.title,
                    sheet=ws.title,
                    table_index=sheet_i,
                    row_index=ri + 1,
                    cell_index=ci + 1,
                    xpath_hint=f"{ws.title}!R{ri + 1}C{ci + 1}",
                    excerpt=cell_text[:240],
                )
                blocks.append(
                    Block(
                        block_id=f"{filename}#{ws.title}r{ri + 1}c{ci + 1}",
                        kind="table_cell",
                        text=cell_text,
                        location=loc,
                    )
                )
            rows_data.append(row_cells)
        n_cols = max((len(r) for r in rows_data), default=0)
        tables.append(
            TableInfo(
                table_id=f"{filename}#{ws.title}",
                location=Location(
                    filename=filename,
                    file_type="xlsx",
                    section=ws.title,
                    sheet=ws.title,
                    table_index=sheet_i,
                ),
                rows=rows_data,
                n_rows=len(rows_data),
                n_cols=n_cols,
            )
        )

    wb.close()
    return DocumentIndex(
        path=str(p),
        filename=filename,
        file_type="xlsx",
        sha256=sha256_file(p),
        size_bytes=p.stat().st_size,
        sections=sections,
        blocks=blocks,
        tables=tables,
        metadata={"sheet_count": len(sections)},
    )
