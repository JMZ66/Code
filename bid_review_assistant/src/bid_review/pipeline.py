"""审查流水线：导入 → 索引 → 格式/占位/抽取/一致性 → 报告 → SHA 复核。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from bid_review import __version__
from bid_review.consistency import check_consistency
from bid_review.extract import check_placeholders, extract_fields
from bid_review.format_check import check_format, load_profile, profile_from_template_docx
from bid_review.hashutil import sha256_file
from bid_review.models import FileIntegrity, ReviewResult
from bid_review.parsers import parse_document
from bid_review.report import write_reports


ProgressCb = Callable[[str], None]


def run_review(
    input_paths: list[str | Path],
    output_dir: str | Path,
    *,
    template_docx: str | Path | None = None,
    profile_json: str | Path | None = None,
    role_hints: dict[str, str] | None = None,
    progress: ProgressCb | None = None,
) -> tuple[ReviewResult, dict[str, str]]:
    def log(msg: str) -> None:
        if progress:
            progress(msg)

    paths = [Path(p) for p in input_paths]
    for p in paths:
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {p}")
        if p.suffix.lower() not in {".docx", ".pdf", ".xlsx", ".xlsm"}:
            raise ValueError(f"不支持的文件类型: {p.name}")

    # 1) 核查前哈希
    log("计算核查前 SHA-256…")
    before_hashes = {str(p.resolve()): sha256_file(p) for p in paths}

    # 2) 模板配置
    if template_docx:
        log(f"自模板反推格式配置: {Path(template_docx).name}")
        profile = profile_from_template_docx(template_docx)
        # 若同时提供 json，用 json 覆盖部分键
        if profile_json:
            overlay = load_profile(profile_json)
            profile = _deep_merge(profile, overlay)
    else:
        log("加载格式配置…")
        profile = load_profile(profile_json)

    # 3) 解析索引
    documents = []
    role_hints = role_hints or {}
    for p in paths:
        log(f"解析索引: {p.name}")
        role = role_hints.get(p.name) or role_hints.get(str(p))
        documents.append(parse_document(p, role=role))

    # 若指定模板文件也在输入中，标记角色
    if template_docx:
        tname = Path(template_docx).name
        for d in documents:
            if d.filename == tname and d.role == "未知":
                d.role = "模板"
                d.authority_rank = 5

    # 4) 各项检查（全部只读）
    log("检查格式…")
    findings = check_format(documents, profile)
    log("检查占位与附件…")
    findings.extend(check_placeholders(documents, profile))
    log("抽取关键字段…")
    fields = extract_fields(documents)
    log("跨文件一致性检查…")
    findings.extend(check_consistency(documents, fields))

    # 5) 核查后哈希 —— 原文件必须不变
    log("复核 SHA-256…")
    integrity: list[FileIntegrity] = []
    for p in paths:
        key = str(p.resolve())
        after = sha256_file(p)
        integrity.append(
            FileIntegrity(
                path=key,
                filename=p.name,
                sha256_before=before_hashes[key],
                sha256_after=after,
                unchanged=before_hashes[key] == after,
            )
        )
        if before_hashes[key] != after:
            raise RuntimeError(
                f"原文件在核查过程中发生变化（严禁写回）: {p.name}\n"
                f"before={before_hashes[key]}\nafter={after}"
            )

    result = ReviewResult(
        documents=documents,
        findings=findings,
        fields=fields,
        integrity=integrity,
        template_profile=profile,
        meta={
            "version": __version__,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "input_count": len(paths),
            "readonly": True,
            "offline": True,
        },
    )

    log("生成报告…")
    report_paths = write_reports(result, output_dir)
    log("完成。")
    return result, report_paths


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out
