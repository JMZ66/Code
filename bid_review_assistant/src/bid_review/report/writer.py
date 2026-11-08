"""生成 Excel / HTML / Markdown 审查报告（写入输出目录，不触碰原文件）。"""

from __future__ import annotations

import html
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from bid_review.models import ReviewResult


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_markdown(result: ReviewResult, out_path: Path) -> Path:
    lines: list[str] = []
    lines.append("# 招投标文件审查报告")
    lines.append("")
    lines.append(f"- 开始时间：{result.started_at}")
    lines.append(f"- 结束时间：{result.finished_at}")
    if result.template_path:
        lines.append(f"- 模板：`{result.template_path}`")
    lines.append("")
    lines.append("## 摘要")
    lines.append("")
    for k, v in result.summary().items():
        lines.append(f"- {k}：{v}")
    lines.append("")
    lines.append("## 文件完整性（SHA-256）")
    lines.append("")
    lines.append("| 文件 | 核查前 | 核查后 | 未改动 |")
    lines.append("|---|---|---|---|")
    for it in result.integrity:
        lines.append(
            f"| {it.filename} | `{it.sha256_before}` | `{it.sha256_after}` | "
            f"{'是' if it.unchanged else '否'} |"
        )
    lines.append("")
    lines.append("## 抽取字段")
    lines.append("")
    lines.append("| 字段 | 原文值 | 规范化 | 位置 | 条件 | 置信度 |")
    lines.append("|---|---|---|---|---|---|")
    for f in result.fields:
        lines.append(
            f"| {f.label} | {f.value} | {f.normalized} | {f.location.label()} | "
            f"{'；'.join(f.conditions) or '-'} | {f.confidence:.2f} |"
        )
    lines.append("")
    lines.append("## 问题清单")
    lines.append("")
    for issue in result.issues:
        lines.append(f"### {issue.issue_id} · {issue.severity.value} · {issue.title}")
        lines.append("")
        lines.append(f"- 类别：{issue.category.value}")
        lines.append(f"- 说明：{issue.description}")
        lines.append(f"- 判断依据：{issue.rationale}")
        lines.append(f"- 建议：{issue.suggestion}")
        if issue.evidence:
            lines.append("- 证据位置：")
            for loc in issue.evidence:
                lines.append(f"  - {loc.label()}")
                if loc.excerpt:
                    lines.append(f"    - 原文：{loc.excerpt}")
        lines.append("")
    if result.notes:
        lines.append("## 备注")
        lines.append("")
        for note in result.notes:
            lines.append(f"- {note}")
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def write_html(result: ReviewResult, out_path: Path) -> Path:
    summary_rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>" for k, v in result.summary().items()
    )
    integrity_rows = "".join(
        "<tr>"
        f"<td>{html.escape(i.filename)}</td>"
        f"<td><code>{i.sha256_before}</code></td>"
        f"<td><code>{i.sha256_after}</code></td>"
        f"<td>{'是' if i.unchanged else '<b>否</b>'}</td>"
        "</tr>"
        for i in result.integrity
    )
    issue_blocks = []
    for issue in result.issues:
        evid = "".join(
            f"<li>{html.escape(loc.label())}"
            + (
                f"<br/><small>原文：{html.escape(loc.excerpt)}</small>"
                if loc.excerpt
                else ""
            )
            + "</li>"
            for loc in issue.evidence
        )
        issue_blocks.append(
            f"""
            <section class="issue sev-{html.escape(issue.severity.name)}">
              <h3>{html.escape(issue.issue_id)} · {html.escape(issue.severity.value)} · {html.escape(issue.title)}</h3>
              <p><b>类别</b>：{html.escape(issue.category.value)}</p>
              <p><b>说明</b>：{html.escape(issue.description)}</p>
              <p><b>判断依据</b>：{html.escape(issue.rationale)}</p>
              <p><b>建议</b>：{html.escape(issue.suggestion)}</p>
              <ul>{evid}</ul>
            </section>
            """
        )
    doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>招投标文件审查报告</title>
<style>
body {{ font-family: "Microsoft YaHei", "PingFang SC", sans-serif; margin: 24px; color: #222; }}
h1 {{ border-bottom: 2px solid #1f4e79; padding-bottom: 8px; }}
table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
th, td {{ border: 1px solid #ccc; padding: 6px 8px; vertical-align: top; }}
th {{ background: #e8eef5; }}
.issue {{ border-left: 4px solid #888; padding: 8px 12px; margin: 12px 0; background: #fafafa; }}
.sev-CONFIRMED_ERROR {{ border-left-color: #b00020; }}
.sev-SUSPECTED_CONFLICT {{ border-left-color: #c77800; }}
.sev-MISSING_EVIDENCE {{ border-left-color: #555; }}
.sev-NEEDS_HUMAN {{ border-left-color: #1f4e79; }}
code {{ font-size: 12px; word-break: break-all; }}
</style>
</head>
<body>
<h1>招投标文件审查报告</h1>
<p>开始：{html.escape(result.started_at)}　结束：{html.escape(result.finished_at)}</p>
<h2>摘要</h2>
<table><tr><th>严重程度</th><th>数量</th></tr>{summary_rows}</table>
<h2>文件完整性（SHA-256）</h2>
<table><tr><th>文件</th><th>核查前</th><th>核查后</th><th>未改动</th></tr>{integrity_rows}</table>
<h2>问题清单</h2>
{''.join(issue_blocks) or '<p>未发现问题。</p>'}
</body>
</html>
"""
    out_path.write_text(doc, encoding="utf-8")
    return out_path


def write_excel(result: ReviewResult, out_path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "问题清单"
    headers = [
        "问题编号",
        "类别",
        "严重程度",
        "标题",
        "说明",
        "判断依据",
        "建议",
        "关联字段",
        "位置",
        "原文摘录",
    ]
    ws.append(headers)
    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(color="FFFFFF", bold=True)
    for col, _ in enumerate(headers, 1):
        cell = ws.cell(1, col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(wrap_text=True)

    sev_fill = {
        "确定错误": PatternFill("solid", fgColor="F8D7DA"),
        "疑似冲突": PatternFill("solid", fgColor="FFF3CD"),
        "缺少依据": PatternFill("solid", fgColor="E2E3E5"),
        "需要人工判断": PatternFill("solid", fgColor="D6EAF8"),
        "提示": PatternFill("solid", fgColor="FFFFFF"),
    }
    for issue in result.issues:
        row = issue.to_row()
        values = [row[h] for h in headers]
        ws.append(values)
        fill = sev_fill.get(issue.severity.value)
        if fill:
            for col in range(1, len(headers) + 1):
                ws.cell(ws.max_row, col).fill = fill
                ws.cell(ws.max_row, col).alignment = Alignment(wrap_text=True, vertical="top")

    ws2 = wb.create_sheet("字段抽取")
    ws2.append(["字段", "原文值", "规范化", "文件", "位置", "条件", "效力分", "置信度"])
    for f in result.fields:
        ws2.append(
            [
                f.label,
                f.value,
                f.normalized,
                f.location.filename,
                f.location.label(),
                "；".join(f.conditions),
                f.source_authority,
                f.confidence,
            ]
        )

    ws3 = wb.create_sheet("完整性")
    ws3.append(["文件", "路径", "SHA256前", "SHA256后", "未改动", "字节数"])
    for i in result.integrity:
        ws3.append(
            [i.filename, i.path, i.sha256_before, i.sha256_after, i.unchanged, i.size_bytes]
        )

    ws4 = wb.create_sheet("摘要")
    ws4.append(["项", "值"])
    ws4.append(["开始时间", result.started_at])
    ws4.append(["结束时间", result.finished_at])
    ws4.append(["模板", result.template_path or ""])
    for k, v in result.summary().items():
        ws4.append([k, v])
    for note in result.notes:
        ws4.append(["备注", note])

    for sheet in wb.worksheets:
        for col in sheet.columns:
            max_len = 0
            letter = col[0].column_letter
            for cell in col:
                max_len = max(max_len, len(str(cell.value or "")))
            sheet.column_dimensions[letter].width = min(max_len + 2, 48)

    wb.save(out_path)
    return out_path


def write_json(result: ReviewResult, out_path: Path) -> Path:
    out_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return out_path


def write_reports(result: ReviewResult, output_dir: str | Path) -> dict[str, str]:
    out = _ensure_dir(Path(output_dir))
    paths = {
        "markdown": str(write_markdown(result, out / "审查报告.md")),
        "html": str(write_html(result, out / "审查报告.html")),
        "excel": str(write_excel(result, out / "审查报告.xlsx")),
        "json": str(write_json(result, out / "审查报告.json")),
    }
    return paths
