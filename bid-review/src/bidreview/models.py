"""Shared data structures. Findings always carry evidence locations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


DEFINITE = "确定错误"
SUSPECTED = "疑似冲突"
NO_BASIS = "缺少依据"
HUMAN = "需要人工判断"
CATEGORIES = (DEFINITE, SUSPECTED, NO_BASIS, HUMAN)

SEVERITY = {
    DEFINITE: "高",
    SUSPECTED: "中",
    HUMAN: "中",
    NO_BASIS: "低",
}


def file_token(file_name: str) -> str:
    """Stable short id used in machine keys. Leading digits win, else the stem."""
    stem = Path(file_name).stem
    digits = ""
    for ch in stem:
        if ch.isdigit():
            digits += ch
        else:
            break
    return digits or stem


@dataclass
class Location:
    file_name: str
    file_path: str
    sha256: str
    kind: str
    part: str
    xml_path: str
    section_title: str = "（文首）"
    section_index: int | None = None
    paragraph_index: int | None = None
    table_index: int | None = None
    row: int | None = None
    col: int | None = None
    pdf_page: int | None = None

    def human(self) -> str:
        bits = [self.part, self.xml_path]
        if self.table_index is not None:
            bits.append(f"表{self.table_index + 1}")
        if self.row is not None:
            bits.append(f"第{self.row}行")
        if self.col is not None:
            bits.append(f"第{self.col}列")
        if self.pdf_page is not None:
            bits.append(f"PDF第{self.pdf_page}页")
        return " / ".join(b for b in bits if b)

    def to_dict(self) -> dict:
        return {
            "file_name": self.file_name,
            "sha256": self.sha256,
            "kind": self.kind,
            "part": self.part,
            "xml_path": self.xml_path,
            "section_title": self.section_title,
            "section_index": self.section_index,
            "paragraph_index": self.paragraph_index,
            "table_index": self.table_index,
            "row": self.row,
            "col": self.col,
            "pdf_page": self.pdf_page,
            "human": self.human(),
        }


@dataclass
class RunFormat:
    text: str
    east_asia: str | None = None
    size_half: int | None = None
    bold: bool | None = None


@dataclass
class EffectiveFormat:
    east_asia: str | None = None
    size_half: int | None = None
    line: int | None = None
    line_rule: str | None = None
    align: str | None = None

    def same_as(self, other: "EffectiveFormat") -> bool:
        return (
            self.east_asia == other.east_asia
            and self.size_half == other.size_half
            and self.line == other.line
            and (self.line_rule or "auto") == (other.line_rule or "auto")
            and self.align == other.align
        )


@dataclass
class Paragraph:
    text: str
    accepted_text: str
    location: Location
    style_id: str | None = None
    style_name: str | None = None
    heading_level: int | None = None
    in_table: bool = False
    has_insert: bool = False
    has_delete: bool = False
    inserted_text: str = ""
    deleted_text: str = ""
    section_index: int = 0
    section_title: str = "（文首）"
    effective: EffectiveFormat = field(default_factory=EffectiveFormat)
    runs: list[RunFormat] = field(default_factory=list)


@dataclass
class Table:
    location: Location
    rows: list[list[str]]
    header: list[str]
    preceding_heading: str
    section_title: str
    section_index: int = 0


@dataclass
class CommentNote:
    comment_id: str
    author: str
    text: str
    location: Location


@dataclass
class RevisionNote:
    kind: str
    text: str
    author: str
    location: Location


@dataclass
class SectionInfo:
    index: int
    top: int | None = None
    bottom: int | None = None
    left: int | None = None
    right: int | None = None
    header: int | None = None
    footer: int | None = None
    header_text: str = ""
    footer_text: str = ""
    footer_has_page_field: bool = False


@dataclass
class StyleInfo:
    style_id: str
    name: str
    based_on: str | None = None
    outline_lvl: int | None = None
    east_asia: str | None = None
    size_half: int | None = None
    line: int | None = None
    line_rule: str | None = None
    align: str | None = None
    has_numbering: bool = False
    num_id: str | None = None
    ilvl: str | None = None
    num_fmt: str | None = None
    lvl_text: str | None = None


@dataclass
class Document:
    path: str
    file_name: str
    role: str
    title: str
    sha256: str
    kind: str
    paragraphs: list[Paragraph] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    comments: list[CommentNote] = field(default_factory=list)
    revisions: list[RevisionNote] = field(default_factory=list)
    sections: list[SectionInfo] = field(default_factory=list)
    styles: dict[str, StyleInfo] = field(default_factory=dict)
    headings: list[tuple[int, str, Location]] = field(default_factory=list)
    page_count: int | None = None
    unreadable: str | None = None

    def all_text(self) -> str:
        parts: list[str] = []
        for p in self.paragraphs:
            if p.accepted_text:
                parts.append(p.accepted_text)
        for table in self.tables:
            for row in table.rows:
                parts.append("\t".join(row))
        for sec in self.sections:
            if sec.header_text:
                parts.append(sec.header_text)
            if sec.footer_text:
                parts.append(sec.footer_text)
        return "\n".join(parts)

    def to_index(self) -> dict:
        return {
            "file_name": self.file_name,
            "path": self.path,
            "role": self.role,
            "title": self.title,
            "sha256": self.sha256,
            "kind": self.kind,
            "unreadable": self.unreadable,
            "paragraph_count": len(self.paragraphs),
            "table_count": len(self.tables),
            "comment_count": len(self.comments),
            "revision_count": len(self.revisions),
            "page_count": self.page_count,
            "headings": [
                {"level": level, "title": title, "location": loc.human()}
                for level, title, loc in self.headings
            ],
            "sections": [
                {
                    "index": s.index,
                    "margins_twips": {
                        "top": s.top,
                        "bottom": s.bottom,
                        "left": s.left,
                        "right": s.right,
                    },
                    "header_text": s.header_text,
                    "footer_text": s.footer_text,
                    "footer_has_page_field": s.footer_has_page_field,
                }
                for s in self.sections
            ],
            "tables": [
                {
                    "heading": t.preceding_heading,
                    "section": t.section_title,
                    "rows": len(t.rows),
                    "cols": len(t.header) if t.header else (len(t.rows[0]) if t.rows else 0),
                    "header": t.header,
                    "location": t.location.human(),
                }
                for t in self.tables
            ],
            "paragraphs": [
                {
                    "section": paragraph.section_title,
                    "location": paragraph.location.human(),
                    "pdf_page": paragraph.location.pdf_page,
                    "style": paragraph.style_id,
                    "text": paragraph.accepted_text[:160],
                }
                for paragraph in self.paragraphs
                if paragraph.accepted_text.strip()
            ],
        }


@dataclass
class Fact:
    family: str
    subject: str
    kind: str
    value_norm: str
    value_display: str
    number: float | None
    unit: str | None
    unit_family: str | None
    quote: str
    location: Location
    section: str
    role: str
    file_name: str
    label: str = ""
    operator: str = ""

    def to_dict(self) -> dict:
        return {
            "family": self.family,
            "subject": self.subject,
            "kind": self.kind,
            "label": self.label,
            "operator": self.operator,
            "value_norm": self.value_norm,
            "value_display": self.value_display,
            "number": self.number,
            "unit": self.unit,
            "unit_family": self.unit_family,
            "quote": self.quote,
            "section": self.section,
            "role": self.role,
            "file_name": self.file_name,
            "location": self.location.to_dict(),
        }


@dataclass
class Precedence:
    labels: list[str]
    quote: str
    location: Location | None
    source: str

    def to_dict(self) -> dict:
        return {
            "labels": self.labels,
            "quote": self.quote,
            "source": self.source,
            "location": None if self.location is None else self.location.to_dict(),
        }


@dataclass
class Finding:
    rule_id: str
    category: str
    title: str
    original_text: str
    basis: str
    suggestion: str
    key: str
    files: list[str] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    pdf_pages: list[int] = field(default_factory=list)
    details: dict = field(default_factory=dict)
    finding_id: str = ""

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"invalid category: {self.category}")

    @property
    def severity(self) -> str:
        return SEVERITY[self.category]

    def blob(self) -> str:
        values = self.details.get("values") or []
        return "\n".join(
            [
                self.title,
                self.original_text,
                self.basis,
                self.suggestion,
                " ".join(self.files),
                " ".join(self.sections),
                " ".join(self.locations),
                " ".join(str(v) for v in values),
            ]
        )

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "rule_id": self.rule_id,
            "category": self.category,
            "severity": self.severity,
            "title": self.title,
            "original_text": self.original_text,
            "basis": self.basis,
            "suggestion": self.suggestion,
            "key": self.key,
            "files": self.files,
            "sections": self.sections,
            "locations": self.locations,
            "pdf_pages": self.pdf_pages,
            "details": self.details,
        }


def make_finding(**kwargs) -> Finding:
    return Finding(**kwargs)
