"""生成 Excel / HTML / Markdown 审查报告（不写回原文件）。"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from bid_review.models import ReviewResult


def write_reports(result: ReviewResult, output_dir: str | Path) -> dict[str, str]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    paths = {
        "markdown": str(out / f"审查报告_{stamp}.md"),
        "html": str(out / f"审查报告_{stamp}.html"),
        "excel": str(out / f"审查报告_{stamp}.xlsx"),
        "json": str(out / f"审查报告_{stamp}.json"),
    }
    _write_markdown(result, paths["markdown"])
    _write_html(result, paths["html"])
    _write_excel(result, paths["excel"])
    with Path(paths["json"]).open("w", encoding="utf-8") as fh:
        json.dump(result.to_dict(), fh, ensure_ascii=False, indent=2)
    return paths


def _write_markdown(result: ReviewResult, path: str) -> None:
    summary = result.summary()
    lines = [
        "# 招投标文件审查报告",
        "",
        f"- 生成时间（UTC）：{result.meta.get('generated_at', '')}",
        f"- 工具版本：{result.meta.get('version', '')}",
        f"- 导入文件数：{len(result.documents)}",
        f"- 发现问题数：{len(result.findings)}",
        "",
        "## 严重程度汇总",
        "",
    ]
    for k, v in summary.items():
        lines.append(f"- {k}：{v}")
    lines += ["", "## 原文件 SHA-256 校验", ""]
    for i in result.integrity:
        flag = "未变更" if i.unchanged else "已变更（异常）"
        lines.append(f"- `{i.filename}`：`{i.sha256_before}` → {flag}")
    lines += ["", "## 抽取关键字段（抽样）", ""]
    for f in result.fields[:80]:
        loc = f.loc.label() if f.loc else ""
        cond = f"（条件：{f.condition}）" if f.condition else ""
        lines.append(f"- **{f.label}**：{f.value}{cond} — {loc}")
    lines += ["", "## 问题清单", ""]
    for finding in result.findings:
        lines += [
            f"### {finding.finding_id} [{finding.severity.value}] {finding.title}",
            "",
            f"- 类别：{finding.category.value}",
            f"- 说明：{finding.detail}",
            f"- 判断依据：{finding.rationale}",
            f"- 建议：{finding.suggestion}",
            f"- 规则：{finding.rule_id}",
            "- 原文位置：",
        ]
        for e in finding.evidence:
            lines.append(f"  - {e.label()}")
            if e.excerpt:
                lines.append(f"    > {e.excerpt}")
        lines.append("")
    lines += [
        "## 声明",
        "",
        "本工具为只读核查助手，不自动改写招标文件，不编造法规或资质标准。",
        "无法确认的事项已标记为“需要人工判断”或“缺少依据”。",
        "",
    ]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def _write_html(result: ReviewResult, path: str) -> None:
    summary = result.summary()
    rows = []
    for f in result.findings:
        locs = "<br/>".join(html.escape(e.label()) for e in f.evidence)
        excerpts = "<br/>".join(html.escape(e.excerpt) for e in f.evidence if e.excerpt)
        rows.append(
            "<tr>"
            f"<td>{html.escape(f.finding_id)}</td>"
            f"<td>{html.escape(f.severity.value)}</td>"
            f"<td>{html.escape(f.category.value)}</td>"
            f"<td>{html.escape(f.title)}</td>"
            f"<td>{html.escape(f.detail)}</td>"
            f"<td>{locs}</td>"
            f"<td>{excerpts}</td>"
            f"<td>{html.escape(f.rationale)}</td>"
            f"<td>{html.escape(f.suggestion)}</td>"
            "</tr>"
        )
    integrity_rows = "".join(
        f"<tr><td>{html.escape(i.filename)}</td><td><code>{i.sha256_before}</code></td>"
        f"<td>{'是' if i.unchanged else '否'}</td></tr>"
        for i in result.integrity
    )
    summary_li = "".join(f"<li>{html.escape(k)}：{v}</li>" for k, v in summary.items())
    doc_li = "".join(
        f"<li>{html.escape(d.filename)}（{html.escape(d.role)} / {d.file_type}）"
        f" SHA-256=<code>{d.sha256}</code></li>"
        for d in result.documents
    )
    content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>招投标文件审查报告</title>
<style>
body {{ font-family: "Microsoft YaHei", "PingFang SC", sans-serif; margin: 24px; color: #1a1a1a; }}
h1 {{ border-bottom: 2px solid #245b8a; padding-bottom: 8px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ border: 1px solid #ccc; padding: 6px 8px; vertical-align: top; }}
th {{ background: #e8f1f8; }}
.tag {{ display: inline-block; padding: 2px 6px; background: #f0f0f0; }}
.note {{ color: #555; margin-top: 24px; }}
</style>
</head>
<body>
<h1>招投标文件审查报告</h1>
<p>生成时间（UTC）：{html.escape(str(result.meta.get('generated_at', '')))} |
工具版本：{html.escape(str(result.meta.get('version', '')))}</p>
<h2>严重程度汇总</h2>
<ul>{summary_li}</ul>
<h2>导入文件</h2>
<ul>{doc_li}</ul>
<h2>SHA-256 校验</h2>
<table><tr><th>文件</th><th>核查前哈希</th><th>未变更</th></tr>{integrity_rows}</table>
<h2>问题清单</h2>
<table>
<tr>
<th>编号</th><th>严重程度</th><th>类别</th><th>标题</th><th>说明</th>
<th>原文位置</th><th>原文摘录</th><th>判断依据</th><th>建议</th>
</tr>
{''.join(rows)}
</table>
<p class="note">本工具只读核查，不修改原文件，不上传企业文件，不调用云端 API。</p>
</body>
</html>
"""
    Path(path).write_text(content, encoding="utf-8")


def _write_excel(result: ReviewResult, path: str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "问题清单"
    headers = [
        "编号",
        "类别",
        "严重程度",
        "标题",
        "说明",
        "原文位置",
        "原文摘录",
        "判断依据",
        "建议",
        "规则ID",
    ]
    ws.append(headers)
    header_fill = PatternFill("solid", fgColor="D9E8F5")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(wrap_text=True)
    for f in result.findings:
        row = f.to_row()
        ws.append([row[h] for h in headers])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 18

    ws2 = wb.create_sheet("字段抽取")
    ws2.append(["字段", "值", "归一化", "单位", "条件", "位置", "置信度"])
    for f in result.fields:
        ws2.append(
            [
                f.label,
                f.value,
                f.normalized,
                f.unit,
                f.condition,
                f.loc.label() if f.loc else "",
                f.confidence,
            ]
        )

    ws3 = wb.create_sheet("完整性校验")
    ws3.append(["文件名", "路径", "核查前SHA256", "核查后SHA256", "未变更"])
    for i in result.integrity:
        ws3.append([i.filename, i.path, i.sha256_before, i.sha256_after, i.unchanged])

    ws4 = wb.create_sheet("文档索引")
    ws4.append(["文件名", "类型", "角色", "效力序", "段落数", "表格数", "章节", "SHA256"])
    for d in result.documents:
        ws4.append(
            [
                d.filename,
                d.file_type,
                d.role,
                d.authority_rank,
                len(d.paragraphs),
                len(d.tables),
                " / ".join(s.name for s in d.sections[:12]),
                d.sha256,
            ]
        )

    wb.save(path)
