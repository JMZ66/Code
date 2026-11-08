"""Review orchestration. Inputs are hashed before and after a read-only pass."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from bidreview.checks import (
    check_consistency,
    check_external_basis,
    check_format,
    check_missing_attachments,
    check_missing_sections,
    check_read_errors,
    check_residue,
)
from bidreview.docx_reader import read_docx
from bidreview.facts import extract_document_facts, extract_precedence
from bidreview.integrity import sha256_file, snapshot, unchanged
from bidreview.models import DEFINITE, Document, Fact, Finding, Precedence
from bidreview.pdf_reader import read_pdf
from bidreview.report_writer import write_reports
from bidreview.xlsx_reader import read_xlsx

_CATEGORY_ORDER = {"确定错误": 0, "疑似冲突": 1, "需要人工判断": 2, "缺少依据": 3}


@dataclass
class ReviewResult:
    findings: list[Finding]
    documents: list[Document]
    template: Document | None
    facts: list[Fact]
    precedence: Precedence | None
    hashes_before: dict[str, str]
    hashes_after: dict[str, str]
    inputs_unchanged: bool
    out_dir: str
    report_paths: dict[str, str] = field(default_factory=dict)

    def to_summary(self) -> dict:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.category] = counts.get(finding.category, 0) + 1
        return {
            "finding_count": len(self.findings),
            "by_category": counts,
            "inputs_unchanged": self.inputs_unchanged,
            "document_count": len(self.documents),
            "fact_count": len(self.facts),
            "precedence": None if self.precedence is None else self.precedence.labels,
            "reports": self.report_paths,
        }


def load_rules(path: Path | None) -> dict:
    if path is None:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("规则文件必须是 JSON 对象")
    return data


def read_document(path: Path, *, role: str, title: str, sha256: str) -> Document:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return read_docx(path, role=role, title=title, sha256=sha256)
    if suffix == ".pdf":
        return read_pdf(path, role=role, title=title, sha256=sha256)
    if suffix == ".xlsx":
        return read_xlsx(path, role=role, title=title, sha256=sha256)
    doc = Document(
        path=str(path),
        file_name=path.name,
        role=role,
        title=title or path.stem,
        sha256=sha256,
        kind=suffix.lstrip(".") or "unknown",
    )
    doc.unreadable = f"不支持的文件类型：{suffix or '无扩展名'}。仅读取 DOCX、PDF、XLSX。"
    return doc


def _number(findings: list[Finding]) -> list[Finding]:
    ordered = sorted(findings, key=lambda item: (_CATEGORY_ORDER.get(item.category, 9), item.rule_id, item.key))
    for index, finding in enumerate(ordered, start=1):
        finding.finding_id = f"BR-{index:04d}"
    return ordered


def review(
    *,
    template: Path,
    documents: list[tuple[Path, str, str]],
    conforming: set[str],
    rules: dict | None,
    out_dir: Path,
) -> ReviewResult:
    """Run a read-only review and write reports into ``out_dir``.

    ``documents`` items are ``(path, role, title)``. ``conforming`` contains
    file names that must follow the template's explicit formatting.
    """
    rules = rules or {}
    template = template.resolve()
    documents = [(path.resolve(), role, title) for path, role, title in documents]
    inputs = [template] + [path for path, _role, _title in documents]
    before = snapshot(inputs)
    template_sha = before[str(template)]
    template_doc = read_docx(template, role="template", title=template.stem, sha256=template_sha)
    loaded: list[Document] = []
    for path, role, title in documents:
        loaded.append(read_document(path, role=role, title=title, sha256=before[str(path)]))

    conforming_names = set(conforming)
    conforming_names.update(doc.file_name for doc in loaded if doc.role == "conforming")

    findings: list[Finding] = []
    findings.extend(check_read_errors(loaded))
    if template_doc.unreadable:
        findings.append(
            Finding(
                rule_id="FILE_READ_ERROR",
                category="需要人工判断",
                title="模板未能读取",
                original_text=template_doc.unreadable or "",
                basis="没有模板就没有格式和章节依据，不能改用内置公文标准。",
                suggestion="请换一份可读的 DOCX 模板。本工具不会修改原文件。",
                key="FILE_READ_ERROR:template",
                files=[template_doc.file_name],
                sections=["模板"],
                locations=[template_doc.path],
            )
        )
    for doc in loaded:
        if doc.file_name in conforming_names and not template_doc.unreadable:
            findings.extend(check_format(template_doc, doc))
            findings.extend(check_missing_sections(template_doc, doc))
        if doc.file_name != template_doc.file_name:
            findings.extend(check_residue(doc))
    findings.extend(check_missing_attachments(loaded))
    facts: list[Fact] = []
    for doc in loaded:
        facts.extend(extract_document_facts(doc, rules))
    precedence = extract_precedence(loaded, rules)
    findings.extend(check_consistency(facts, precedence))
    findings.extend(check_external_basis(loaded, rules))

    after = snapshot(inputs)
    intact = unchanged(before, after)
    if not intact:
        changed = sorted(path for path, digest in before.items() if after.get(path) != digest)
        findings.append(
            Finding(
                rule_id="INTEGRITY",
                category=DEFINITE,
                title="审查前后原文件哈希不一致",
                original_text="\n".join(changed),
                basis="审查开始和结束时分别计算 SHA-256。不一致说明原文件被写过，审查结论不能当作只读结果。",
                suggestion="请停止使用本次输出，从备份恢复原文件后重新审查。",
                key="INTEGRITY:changed",
                files=[Path(path).name for path in changed],
                sections=["完整性"],
                locations=changed,
            )
        )
    findings = _number(findings)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_resolved = out_dir.resolve()
    for source in inputs:
        if source == out_resolved:
            raise ValueError(f"输出目录不能是原文件本身：{source}")
    report_paths = write_reports(
        out_dir,
        findings=findings,
        documents=loaded,
        template=template_doc,
        facts=facts,
        precedence=precedence,
        hashes_before=before,
        hashes_after=after,
        inputs_unchanged=intact,
    )
    return ReviewResult(
        findings=findings,
        documents=loaded,
        template=template_doc,
        facts=facts,
        precedence=precedence,
        hashes_before=before,
        hashes_after=after,
        inputs_unchanged=intact,
        out_dir=str(out_dir),
        report_paths=report_paths,
    )


def hash_paths(paths: list[Path]) -> list[tuple[str, str]]:
    return [(sha256_file(path), str(path)) for path in paths]
