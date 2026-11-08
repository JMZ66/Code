"""核心数据模型：索引节点、抽取字段、审查发现。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    """问题判定类别（需求第 8 条）。"""

    CONFIRMED = "确定错误"
    SUSPECTED = "疑似冲突"
    MISSING_EVIDENCE = "缺少依据"
    NEEDS_HUMAN = "需要人工判断"


class IssueCategory(str, Enum):
    FORMAT = "格式"
    PLACEHOLDER = "占位/残留"
    FIELD = "关键字段"
    CONSISTENCY = "跨文件一致性"
    STRUCTURE = "结构/附件"
    INTEGRITY = "完整性/校验"


@dataclass
class SourceLoc:
    """可定位的结构位置。"""

    filename: str
    file_type: str
    sha256: str = ""
    section: str = ""
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    cell_index: int | None = None
    ooxml_part: str = ""
    pdf_page: int | None = None
    sheet_name: str = ""
    excel_cell: str = ""
    excerpt: str = ""

    def label(self) -> str:
        parts: list[str] = [self.filename]
        if self.section:
            parts.append(f"章节:{self.section}")
        if self.paragraph_index is not None:
            parts.append(f"段落#{self.paragraph_index}")
        if self.table_index is not None:
            parts.append(f"表格#{self.table_index}")
            if self.row_index is not None:
                parts.append(f"行#{self.row_index}")
            if self.cell_index is not None:
                parts.append(f"单元格#{self.cell_index}")
        if self.pdf_page is not None:
            parts.append(f"PDF页:{self.pdf_page}")
        if self.sheet_name:
            parts.append(f"工作表:{self.sheet_name}")
        if self.excel_cell:
            parts.append(f"单元格:{self.excel_cell}")
        if self.ooxml_part:
            parts.append(f"部件:{self.ooxml_part}")
        return " | ".join(parts)


@dataclass
class ParagraphNode:
    index: int
    text: str
    style: str = ""
    section: str = ""
    font_name: str = ""
    font_size_pt: float | None = None
    bold: bool | None = None
    line_spacing: float | None = None
    alignment: str = ""
    is_heading: bool = False
    numbering_id: str = ""
    has_revision: bool = False
    has_comment: bool = False
    ooxml_part: str = "word/document.xml"


@dataclass
class TableNode:
    index: int
    rows: list[list[str]]
    section: str = ""
    row_count: int = 0
    col_count: int = 0
    ooxml_part: str = "word/document.xml"

    def __post_init__(self) -> None:
        self.row_count = len(self.rows)
        self.col_count = max((len(r) for r in self.rows), default=0)


@dataclass
class SectionNode:
    name: str
    level: int
    start_paragraph: int
    end_paragraph: int | None = None


@dataclass
class HeaderFooterNode:
    kind: str  # header/footer
    section_index: int
    text: str


@dataclass
class DocumentIndex:
    """单个文件的结构索引。"""

    path: str
    filename: str
    file_type: str  # docx|pdf|xlsx
    sha256: str
    paragraphs: list[ParagraphNode] = field(default_factory=list)
    tables: list[TableNode] = field(default_factory=list)
    sections: list[SectionNode] = field(default_factory=list)
    headers_footers: list[HeaderFooterNode] = field(default_factory=list)
    page_margins: list[dict[str, Any]] = field(default_factory=list)
    section_count: int = 0
    comments: list[str] = field(default_factory=list)
    revisions: list[str] = field(default_factory=list)
    pdf_pages: list[str] = field(default_factory=list)
    sheets: list[str] = field(default_factory=list)
    raw_text: str = ""
    role: str = ""  # 正文|预算|技术|合同|附件|模板|未知
    authority_rank: int = 50  # 越小效力越高

    def all_text_blocks(self) -> list[tuple[str, SourceLoc]]:
        blocks: list[tuple[str, SourceLoc]] = []
        for p in self.paragraphs:
            if not p.text.strip():
                continue
            blocks.append(
                (
                    p.text,
                    SourceLoc(
                        filename=self.filename,
                        file_type=self.file_type,
                        sha256=self.sha256,
                        section=p.section,
                        paragraph_index=p.index,
                        ooxml_part=p.ooxml_part,
                        excerpt=p.text[:200],
                    ),
                )
            )
        for t in self.tables:
            for ri, row in enumerate(t.rows):
                for ci, cell in enumerate(row):
                    if not str(cell).strip():
                        continue
                    blocks.append(
                        (
                            str(cell),
                            SourceLoc(
                                filename=self.filename,
                                file_type=self.file_type,
                                sha256=self.sha256,
                                section=t.section,
                                table_index=t.index,
                                row_index=ri,
                                cell_index=ci,
                                ooxml_part=t.ooxml_part,
                                excerpt=str(cell)[:200],
                            ),
                        )
                    )
        # PDF 已按行进入 paragraphs，不再把整页原文重复加入，避免条件误绑与字段重复。
        return blocks


@dataclass
class ExtractedField:
    key: str
    label: str
    value: str
    normalized: str
    unit: str = ""
    condition: str = ""
    loc: SourceLoc | None = None
    confidence: float = 0.8


@dataclass
class Finding:
    finding_id: str
    category: IssueCategory
    severity: Severity
    title: str
    detail: str
    evidence: list[SourceLoc] = field(default_factory=list)
    rationale: str = ""
    suggestion: str = ""
    rule_id: str = ""

    def to_row(self) -> dict[str, Any]:
        locs = " || ".join(e.label() for e in self.evidence)
        excerpts = " || ".join(e.excerpt for e in self.evidence if e.excerpt)
        return {
            "编号": self.finding_id,
            "类别": self.category.value,
            "严重程度": self.severity.value,
            "标题": self.title,
            "说明": self.detail,
            "原文位置": locs,
            "原文摘录": excerpts,
            "判断依据": self.rationale,
            "建议": self.suggestion,
            "规则ID": self.rule_id,
        }


@dataclass
class FileIntegrity:
    path: str
    filename: str
    sha256_before: str
    sha256_after: str
    unchanged: bool


@dataclass
class ReviewResult:
    documents: list[DocumentIndex]
    findings: list[Finding]
    fields: list[ExtractedField]
    integrity: list[FileIntegrity]
    template_profile: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, int]:
        counts = {s.value: 0 for s in Severity}
        for f in self.findings:
            counts[f.severity.value] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "meta": self.meta,
            "summary": self.summary(),
            "integrity": [asdict(i) for i in self.integrity],
            "fields": [asdict(f) for f in self.fields],
            "findings": [f.to_row() for f in self.findings],
            "documents": [
                {
                    "filename": d.filename,
                    "file_type": d.file_type,
                    "sha256": d.sha256,
                    "role": d.role,
                    "paragraphs": len(d.paragraphs),
                    "tables": len(d.tables),
                    "sections": [s.name for s in d.sections],
                }
                for d in self.documents
            ],
        }
