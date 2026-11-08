"""Offline smoke test that creates temporary files and deletes nothing of the user."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from bidreview.engine import review
from bidreview.ooxml_build import write_minimal_docx


def run_self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="bidreview-selftest-") as folder:
        root = Path(folder)
        template = root / "template.docx"
        left = root / "left.docx"
        right = root / "right.docx"
        write_minimal_docx(template, ["投标文件格式模板", "项目名称："])
        write_minimal_docx(left, ["本项目总工期为10日历天。", "投标保证金：【待填写】"])
        write_minimal_docx(right, ["本项目总工期为12日历天。"])
        before = {path: path.read_bytes() for path in (template, left, right)}
        result = review(
            template=template,
            documents=[(left, "tender", ""), (right, "contract", "")],
            conforming=set(),
            rules={},
            out_dir=root / "out",
        )
        after = {path: path.read_bytes() for path in before}
        keys = {finding.key for finding in result.findings}
        problems = []
        if before != after or not result.inputs_unchanged:
            problems.append("原文件字节或 SHA-256 发生变化")
        if "VALUE_CONFLICT:总工期" not in keys:
            problems.append("未发现总工期 10 天与 12 天的冲突")
        if not any(key.startswith("UNFILLED:") and "bracket" in key for key in keys):
            problems.append("未发现【待填写】")
        report = result.report_paths
        for name in ("xlsx", "html", "markdown"):
            if not Path(report[name]).is_file():
                problems.append(f"缺少报告 {name}")
        payload = {"ok": not problems, "problems": problems, "keys": sorted(keys), "summary": result.to_summary()}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if not problems else 1
