"""核心数据模型：索引、字段、问题与审查结果。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    CONFIRMED_ERROR = "确定错误"
    SUSPECTED_CONFLICT = "疑似冲突"
    MISSING_EVIDENCE = "缺少依据"
    NEEDS_HUMAN = "需要人工判断"
    INFO = "提示"


class IssueCategory(str, Enum):
    FORMAT = "格式"
    PLACEHOLDER = "占位/缺失"
    FIELD = "关键字段"
    CONSISTENCY = "跨文件一致性"
    INTEGRITY = "完整性校验"
    STRUCTURE = "结构"


@dataclass
class Location:
    """可定位的结构位置。"""

    filename: str
    file_type: str
    section: str = ""
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    cell_index: int | None = None
    page: int | None = None
    xpath_hint: str = ""
    sheet: str = ""
    excerpt: str = ""

    def label(self) -> str:
        parts = [self.filename]
        if self.sheet:
            parts.append(f"工作表:{self.sheet}")
        if self.section:
            parts.append(f"章节:{self.section}")
        if self.page is not None:
            parts.append(f"页码:{self.page}")
        if self.paragraph_index is not None:
            parts.append(f"段落#{self.paragraph_index}")
        if self.table_index is not None:
            parts.append(f"表格#{self.table_index}")
            if self.row_index is not None:
                parts.append(f"行#{self.row_index}")
            if self.cell_index is not None:
                parts.append(f"单元格#{self.cell_index}")
        if self.xpath_hint:
            parts.append(self.xpath_hint)
        return " / ".join(parts)


@dataclass
class Block:
    """文档块（段落或表格单元格）。"""

    block_id: str
    kind: str  # paragraph | table_cell | header | footer | comment
    text: str
    location: Location
    style: str = ""
    font_name: str = ""
    font_size_pt: float | None = None
    bold: bool | None = None
    line_spacing: float | None = None
    numbering: str = ""


@dataclass
class TableInfo:
    table_id: str
    location: Location
    rows: list[list[str]]
    n_rows: int
    n_cols: int


@dataclass
class DocumentIndex:
    path: str
    filename: str
    file_type: str  # docx | pdf | xlsx
    sha256: str
    size_bytes: int
    sections: list[str] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    tables: list[TableInfo] = field(default_factory=list)
    page_count: int | None = None
    has_revisions: bool = False
    has_comments: bool = False
    margins_cm: dict[str, float] = field(default_factory=dict)
    headers: list[str] = field(default_factory=list)
    footers: list[str] = field(default_factory=list)
    section_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def all_text(self) -> str:
        return "\n".join(b.text for b in self.blocks if b.text.strip())


@dataclass
class ExtractedField:
    key: str
    label: str
    value: str
    normalized: str
    location: Location
    confidence: float
    context: str = ""
    conditions: list[str] = field(default_factory=list)
    source_authority: int = 50  # higher = more authoritative


@dataclass
class Issue:
    issue_id: str
    category: IssueCategory
    severity: Severity
    title: str
    description: str
    evidence: list[Location] = field(default_factory=list)
    rationale: str = ""
    suggestion: str = ""
    related_fields: list[str] = field(default_factory=list)

    def to_row(self) -> dict[str, Any]:
        return {
            "问题编号": self.issue_id,
            "类别": self.category.value,
            "严重程度": self.severity.value,
            "标题": self.title,
            "说明": self.description,
            "判断依据": self.rationale,
            "建议": self.suggestion,
            "关联字段": "、".join(self.related_fields),
            "位置": " | ".join(loc.label() for loc in self.evidence),
            "原文摘录": " | ".join(loc.excerpt[:200] for loc in self.evidence if loc.excerpt),
        }


@dataclass
class FileIntegrity:
    path: str
    filename: str
    sha256_before: str
    sha256_after: str
    unchanged: bool
    size_bytes: int


@dataclass
class ReviewResult:
    files: list[DocumentIndex]
    fields: list[ExtractedField]
    issues: list[Issue]
    integrity: list[FileIntegrity]
    template_path: str | None = None
    started_at: str = ""
    finished_at: str = ""
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {s.value: 0 for s in Severity}
        for issue in self.issues:
            counts[issue.severity.value] = counts.get(issue.severity.value, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "files": [asdict(f) for f in self.files],
            "fields": [asdict(f) for f in self.fields],
            "issues": [asdict(i) for i in self.issues],
            "integrity": [asdict(i) for i in self.integrity],
            "template_path": self.template_path,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "notes": self.notes,
            "summary": self.summary(),
        }
