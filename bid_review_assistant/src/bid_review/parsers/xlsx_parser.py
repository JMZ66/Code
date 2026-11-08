"""XLSX 只读解析：工作表、单元格文本与表格行。"""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from bid_review.models import DocumentIndex, ParagraphNode, TableNode


def parse_xlsx(path: str | Path, sha256: str) -> DocumentIndex:
    path = Path(path)
    # data_only=False 保持公式文本；只读打开
    wb = load_workbook(str(path), data_only=True, read_only=True)
    sheets = list(wb.sheetnames)
    tables: list[TableNode] = []
    paragraphs: list[ParagraphNode] = []
    parts: list[str] = []
    p_idx = 0

    for s_idx, name in enumerate(sheets):
        ws = wb[name]
        rows: list[list[str]] = []
        for row in ws.iter_rows(values_only=True):
            cells = [("" if c is None else str(c).strip()) for c in row]
            # 去掉尾部空单元格
            while cells and not cells[-1]:
                cells.pop()
            if any(cells):
                rows.append(cells)
                for c in cells:
                    if c:
                        parts.append(c)
                        paragraphs.append(
                            ParagraphNode(
                                index=p_idx,
                                text=c,
                                section=name,
                                ooxml_part=f"xlsx:{name}",
                            )
                        )
                        p_idx += 1
        tables.append(TableNode(index=s_idx, rows=rows, section=name, ooxml_part=f"xlsx:{name}"))

    wb.close()
    return DocumentIndex(
        path=str(path.resolve()),
        filename=path.name,
        file_type="xlsx",
        sha256=sha256,
        paragraphs=paragraphs,
        tables=tables,
        sheets=sheets,
        raw_text="\n".join(parts),
    )
