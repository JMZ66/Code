"""Read-only CSV and Excel import. The source file is never opened for writing."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from labuv.errors import LabError


def import_table(path: str | Path) -> dict:
    source = Path(path)
    if not source.is_file():
        raise LabError(f"找不到文件：{source}", code="import")
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    suffix = source.suffix.lower()
    if suffix == ".csv":
        frame, encoding = _read_csv(source)
    elif suffix in (".xlsx", ".xlsm"):
        frame = pd.read_excel(source, dtype=str, keep_default_na=False, engine="openpyxl")
        encoding = "xlsx"
    else:
        raise LabError("只读入 CSV 或 XLSX。文件没有被修改。", code="import")
    frame = frame.fillna("")
    headers = [str(column).strip() for column in frame.columns]
    if any(header == "" for header in headers) or len(set(headers)) != len(headers):
        raise LabError("表头有空白或重复列名。原始行没有被删除，但在修正表头前不能导入。", code="import")
    rows = []
    for position, record in enumerate(frame.to_dict(orient="records"), start=2):
        item = {headers[index]: "" if value is None else str(value) for index, value in enumerate(record.values())}
        item["_row"] = position
        rows.append(item)
    return {
        "path": str(source),
        "sha256": digest,
        "encoding": encoding,
        "headers": headers,
        "rows": rows,
        "raw_bytes": raw,
        "note": "原始文件只读。预览中的文字是读入快照，计算前不会删行或改值。",
    }


def _read_csv(path: Path):
    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding=encoding)
            return frame, encoding
        except UnicodeError as exc:
            last_error = exc
    raise LabError(f"CSV 编码无法按 UTF-8 或 GB18030 读取：{last_error}", code="import")


def require_columns(table: dict, columns: list[str]):
    missing = [column for column in columns if column not in table["headers"]]
    if missing:
        raise LabError("缺少列：" + "、".join(missing) + "。没有丢弃已读入的行。", code="import")


def column_error(message: str, *, row: int, column: str):
    raise LabError(message, row=row, column=column, code="import")
