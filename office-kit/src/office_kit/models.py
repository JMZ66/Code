"""JSON-ready document and finding models.

Parsed fields describe the file as stored. They are source observations.
Findings produced by a semantic provider are labeled ``origin="inference"``
and are never source facts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any


def to_plain(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {key: to_plain(value) for key, value in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(key): to_plain(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(value) for value in obj]
    return obj


@dataclass
class SourceInfo:
    path: str
    filename: str
    format: str
    sha256: str
    size: int
    converter: str | None = None
    converted_from: str | None = None


@dataclass
class TextNode:
    anchor: str
    text: str
    kind: str
    revision: str | None = None
    formatting: dict[str, Any] = field(default_factory=dict)


@dataclass
class Paragraph:
    anchor: str
    index: int
    text_accepted: str
    text_original: str
    number_label: str | None = None
    number_ilvl: int | None = None
    number_suffix: str | None = None
    style_id: str | None = None
    style_name: str | None = None
    heading_level: int | None = None
    heading_path: list[dict[str, Any]] = field(default_factory=list)
    section_index: int = 0
    in_table: bool = False
    table_anchor: str | None = None
    formatting: dict[str, Any] = field(default_factory=dict)
    runs: list[TextNode] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)

    @property
    def display(self) -> str:
        if self.number_label:
            return f"{self.number_label} {self.text_accepted}".strip()
        return self.text_accepted


@dataclass
class Cell:
    anchor: str
    text: str
    grid_span: int = 1
    v_merge: str | None = None
    cover_origin: str | None = None
    paragraphs: list[Paragraph] = field(default_factory=list)
    nested_tables: list["Table"] = field(default_factory=list)


@dataclass
class Table:
    anchor: str
    index: int | None
    section_index: int
    rows: list[list[Cell]]
    coverage: list[list[dict[str, Any]]] = field(default_factory=list)
    nested: bool = False
    parent_anchor: str | None = None
    issues: list[str] = field(default_factory=list)


@dataclass
class Comment:
    comment_id: str
    author: str
    date: str | None
    text: str
    anchor: str
    range_anchor: str | None = None


@dataclass
class Revision:
    kind: str
    author: str
    date: str | None
    rev_id: str | None
    text: str
    anchor: str
    previous: dict[str, Any] = field(default_factory=dict)


@dataclass
class HeaderFooter:
    kind: str
    type: str
    part: str
    text: str
    paragraphs: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Section:
    index: int
    anchor: str
    headers: list[HeaderFooter] = field(default_factory=list)
    footers: list[HeaderFooter] = field(default_factory=list)
    page: dict[str, Any] = field(default_factory=dict)
    margins: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutlineItem:
    level: int
    text: str
    display: str
    anchor: str
    number_label: str | None = None
    paragraph_index: int | None = None
    kind: str = "heading"
    state: str | None = None


@dataclass
class WordBody:
    paragraphs: list[Paragraph] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    revisions: list[Revision] = field(default_factory=list)
    outline: list[OutlineItem] = field(default_factory=list)
    styles: list[dict[str, Any]] = field(default_factory=list)
    blocks: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ExcelCell:
    anchor: str
    sheet: str
    coordinate: str
    row: int
    column: int
    formula: str | None = None
    cached_value: Any = None
    cached_text: str = ""
    data_type: str | None = None
    number_format: str | None = None
    font: dict[str, Any] = field(default_factory=dict)
    fill: dict[str, Any] = field(default_factory=dict)
    alignment: dict[str, Any] = field(default_factory=dict)
    comment: dict[str, Any] | None = None
    hyperlink: str | None = None
    hidden_row: bool = False
    hidden_column: bool = False
    merge_origin: str | None = None


@dataclass
class Sheet:
    name: str
    index: int
    state: str
    part: str
    dimension: str | None = None
    merged_ranges: list[str] = field(default_factory=list)
    hidden_rows: list[int] = field(default_factory=list)
    hidden_columns: list[str] = field(default_factory=list)
    hidden_column_ranges: list[str] = field(default_factory=list)
    data_validations: list[dict[str, Any]] = field(default_factory=list)
    comments: list[dict[str, Any]] = field(default_factory=list)
    cells: list[ExcelCell] = field(default_factory=list)


@dataclass
class ExcelBody:
    sheets: list[Sheet] = field(default_factory=list)
    defined_names: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Document:
    source: SourceInfo
    kind: str
    status: str
    warnings: list[dict[str, Any]] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    word: WordBody | None = None
    excel: ExcelBody | None = None
    pdf: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


@dataclass
class Evidence:
    source_path: str
    sha256: str
    anchor: str
    quote: str
    part: str = ""


@dataclass
class Finding:
    id: str
    rule_id: str
    severity: str
    origin: str
    category: str
    message: str
    evidence: list[Evidence] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)
