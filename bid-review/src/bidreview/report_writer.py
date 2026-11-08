"""Standalone Excel, HTML and Markdown reports. No external assets."""

from __future__ import annotations

import html
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from bidreview.models import Document, Fact, Finding, Precedence

_HEADERS = ["序号", "类别", "严重程度", "规则", "问题", "原文", "文件名", "章节", "结构位置", "PDF页码", "判定依据", "建议"]
_FILLS = {
    "确定错误": "F4C7C3",
    "疑似冲突": "FCE4B3",
    "需要人工判断": "D6E3F0",
    "缺少依据": "E6E6E6",
}


def _join(values: list, sep: str = "\n") -> str:
    return sep.join(str(value) for value in values if value not in (None, ""))


def _pages(finding: Finding) -> str:
    if not finding.pdf_pages:
        return "—"
    return "、".join(str(page) for page in finding.pdf_pages)


def _md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


def write_reports(
    out_dir: Path,
    *,
    findings: list[Finding],
    documents: list[Document],
    template: Document | None,
    facts: list[Fact],
    precedence: Precedence | None,
    hashes_before: dict[str, str],
    hashes_after: dict[str, str],
    inputs_unchanged: bool,
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "xlsx": str(out_dir / "审查报告.xlsx"),
        "html": str(out_dir / "审查报告.html"),
        "markdown": str(out_dir / "审查报告.md"),
        "findings_json": str(out_dir / "findings.json"),
        "index_json": str(out_dir / "index.json"),
        "integrity_json": str(out_dir / "integrity.json"),
    }
    _write_xlsx(Path(paths["xlsx"]), findings, documents, template, facts, hashes_before, hashes_after, inputs_unchanged, precedence)
    _write_html(Path(paths["html"]), findings, documents, template, hashes_before, inputs_unchanged, precedence)
    _write_markdown(Path(paths["markdown"]), findings, documents, template, hashes_before, inputs_unchanged, precedence)
    Path(paths["findings_json"]).write_text(
        json.dumps([item.to_dict() for item in findings], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    index = {
        "template": None if template is None else template.to_index(),
        "documents": [doc.to_index() for doc in documents],
        "precedence": None if precedence is None else precedence.to_dict(),
        "facts": [fact.to_dict() for fact in facts],
    }
    Path(paths["index_json"]).write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    integrity = {
        "unchanged": inputs_unchanged,
        "files": [
            {
                "path": path,
                "sha256_before": digest,
                "sha256_after": hashes_after.get(path),
                "unchanged": hashes_after.get(path) == digest,
            }
            for path, digest in hashes_before.items()
        ],
    }
    Path(paths["integrity_json"]).write_text(json.dumps(integrity, ensure_ascii=False, indent=2), encoding="utf-8")
    return paths


def _write_xlsx(path, findings, documents, template, facts, before, after, unchanged, precedence) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "审查问题"
    sheet.append(_HEADERS)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E79")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for finding in findings:
        sheet.append(
            [
                finding.finding_id,
                finding.category,
                finding.severity,
                finding.rule_id,
                finding.title,
                finding.original_text,
                _join(finding.files),
                _join(finding.sections),
                _join(finding.locations),
                _pages(finding),
                finding.basis,
                finding.suggestion,
            ]
        )
        fill = _FILLS.get(finding.category)
        if fill:
            for cell in sheet[sheet.max_row]:
                cell.fill = PatternFill("solid", fgColor=fill)
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    sheet.auto_filter.ref = f"A1:L{sheet.max_row}"
    sheet.freeze_panes = "A2"
    widths = [12, 14, 10, 22, 28, 48, 28, 22, 36, 12, 48, 36]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width

    integrity = book.create_sheet("文件完整性")
    integrity.append(["路径", "审查前SHA-256", "审查后SHA-256", "是否一致"])
    for file_path, digest in before.items():
        integrity.append([file_path, digest, after.get(file_path, ""), "是" if after.get(file_path) == digest else "否"])
    integrity.append([])
    integrity.append(["结论", "原文件未被修改" if unchanged else "原文件哈希发生变化"])

    index = book.create_sheet("文档索引")
    index.append(["文件", "角色", "类型", "SHA-256", "段落", "表格", "页数", "章节", "批注", "修订"])
    rows = documents if template is None else [template] + list(documents)
    for doc in rows:
        headings = "；".join(title for _level, title, _loc in doc.headings[:12])
        index.append(
            [
                doc.file_name,
                doc.role,
                doc.kind,
                doc.sha256,
                len(doc.paragraphs),
                len(doc.tables),
                doc.page_count if doc.page_count is not None else "—",
                headings,
                len(doc.comments),
                len(doc.revisions),
            ]
        )

    extracted = book.create_sheet("抽取字段")
    extracted.append(["事项", "类型", "标签", "取值", "规范值", "单位", "章节", "文件", "原文", "结构位置", "PDF页码"])
    for fact in facts:
        extracted.append(
            [
                fact.subject,
                fact.kind,
                fact.label,
                fact.value_display,
                fact.value_norm,
                fact.unit or "",
                fact.section,
                fact.file_name,
                fact.quote,
                fact.location.human(),
                fact.location.pdf_page or "—",
            ]
        )

    note = book.create_sheet("说明")
    lines = [
        "本报告由招投标文件审查助手在本地生成，审查过程不上传文件、不调用云端接口。",
        "类别：确定错误 / 疑似冲突 / 缺少依据 / 需要人工判断。",
        "判定只使用模板、导入文件和用户规则中已经写明的内容。",
        "工具不修改原文件，不统一版式，不删除空行，不重编号，不重画表格，不填空。",
        "DOCX 不计算排版页码；PDF 页码只在文本层可定位时给出。",
        "效力顺序：" + (" > ".join(precedence.labels) if precedence else "（文件和规则均未给出）"),
    ]
    for line in lines:
        note.append([line])
    book.save(path)


def _write_html(path, findings, documents, template, before, unchanged, precedence) -> None:
    rows = []
    for finding in findings:
        rows.append(
            "<tr class='{cls}'>".format(cls=html.escape(finding.category))
            + "".join(
                f"<td>{html.escape(value).replace(chr(10), '<br>')}</td>"
                for value in [
                    finding.finding_id,
                    finding.category,
                    finding.severity,
                    finding.rule_id,
                    finding.title,
                    finding.original_text,
                    _join(finding.files),
                    _join(finding.sections),
                    _join(finding.locations),
                    _pages(finding),
                    finding.basis,
                    finding.suggestion,
                ]
            )
            + "</tr>"
        )
    hash_rows = []
    for file_path, digest in before.items():
        hash_rows.append(f"<li><code>{html.escape(digest)}</code> {html.escape(file_path)}</li>")
    precedence_text = " > ".join(precedence.labels) if precedence else "（未给出）"
    doc_bits = []
    for doc in documents:
        doc_bits.append(
            f"<li>{html.escape(doc.file_name)}（{html.escape(doc.role)} / {html.escape(doc.kind)}，"
            f"段落 {len(doc.paragraphs)}，表格 {len(doc.tables)}，页 {doc.page_count or '—'}）</li>"
        )
    template_name = html.escape(template.file_name) if template else "（无）"
    document = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>招投标文件审查报告</title>
<style>
body {{ font-family: "Microsoft YaHei", "Noto Sans SC", "Source Han Sans SC", sans-serif; margin: 24px; color: #1b1b1b; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ border: 1px solid #c8c8c8; padding: 6px 8px; vertical-align: top; }}
th {{ background: #1f4e79; color: white; }}
tr.确定错误 {{ background: #fdeceb; }}
tr.疑似冲突 {{ background: #fff6e8; }}
tr.需要人工判断 {{ background: #eef4fb; }}
tr.缺少依据 {{ background: #f4f4f4; }}
code {{ font-family: Consolas, monospace; font-size: 12px; }}
</style>
</head>
<body>
<h1>招投标文件审查报告</h1>
<p>本地只读审查。原文件 SHA-256：{"一致，未被修改" if unchanged else "发生变化"}。</p>
<p>模板：{template_name}</p>
<p>效力顺序：{html.escape(precedence_text)}</p>
<h2>导入文件</h2>
<ul>
{''.join(doc_bits)}
</ul>
<h2>原文件哈希</h2>
<ul>
{''.join(hash_rows)}
</ul>
<h2>问题</h2>
<table>
<thead><tr>{''.join(f'<th>{html.escape(name)}</th>' for name in _HEADERS)}</tr></thead>
<tbody>
{''.join(rows) if rows else '<tr><td colspan="12">未发现问题。</td></tr>'}
</tbody>
</table>
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")


def _write_markdown(path, findings, documents, template, before, unchanged, precedence) -> None:
    lines = [
        "# 招投标文件审查报告",
        "",
        f"- 原文件：{'审查前后 SHA-256 一致，未被修改' if unchanged else '哈希发生变化'}",
        f"- 模板：{template.file_name if template else '（无）'}",
        "- 效力顺序：" + (" > ".join(precedence.labels) if precedence else "（文件和规则均未给出）"),
        "",
        "## 文件索引",
        "",
        "| 文件 | 角色 | 类型 | SHA-256 | 段落 | 表格 | 页 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for doc in documents:
        lines.append(
            f"| {_md_cell(doc.file_name)} | {_md_cell(doc.role)} | {doc.kind} | `{doc.sha256}` | "
            f"{len(doc.paragraphs)} | {len(doc.tables)} | {doc.page_count or '—'} |"
        )
    lines.extend(["", "## 原文件哈希", ""])
    for file_path, digest in before.items():
        lines.append(f"- `{digest}` {file_path}")
    lines.extend(
        [
            "",
            "## 问题一览",
            "",
            "| 序号 | 类别 | 严重程度 | 规则 | 问题 | 文件 | 章节 | PDF页码 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for finding in findings:
        lines.append(
            "| "
            + " | ".join(
                _md_cell(value)
                for value in [
                    finding.finding_id,
                    finding.category,
                    finding.severity,
                    finding.rule_id,
                    finding.title,
                    _join(finding.files, "；"),
                    _join(finding.sections, "；"),
                    _pages(finding),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## 逐条说明")
    lines.append("")
    for finding in findings:
        lines.extend(
            [
                f"### {finding.finding_id} {finding.title}",
                "",
                f"- 类别：{finding.category}（{finding.severity}）",
                f"- 规则：{finding.rule_id}",
                f"- 文件：{_join(finding.files, '；')}",
                f"- 章节：{_join(finding.sections, '；')}",
                f"- 结构位置：{_join(finding.locations, '；')}",
                f"- PDF页码：{_pages(finding)}",
                "",
                "原文：",
                "",
                "```",
                finding.original_text,
                "```",
                "",
                f"判定依据：{finding.basis}",
                "",
                f"建议：{finding.suggestion}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")
