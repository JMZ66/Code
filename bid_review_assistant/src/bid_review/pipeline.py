"""审查流水线：导入 → 校验 → 格式/字段/一致性 → 报告。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from bid_review.consistency.engine import check_consistency
from bid_review.extract.fields import extract_fields
from bid_review.format_check.checker import check_against_template, check_placeholders
from bid_review.ingest.indexer import build_corpus
from bid_review.integrity import IntegrityGuard
from bid_review.models import Issue, IssueCategory, ReviewResult, Severity
from bid_review.report.writer import write_reports

CN_TZ = ZoneInfo("Asia/Shanghai")


def _now_cn() -> str:
    return datetime.now(tz=CN_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")


def run_review(
    input_paths: list[str | Path],
    output_dir: str | Path,
    template_path: str | Path | None = None,
) -> tuple[ReviewResult, dict[str, str]]:
    paths = [str(Path(p).resolve()) for p in input_paths]
    if template_path:
        tmpl = str(Path(template_path).resolve())
    else:
        tmpl = None

    guard = IntegrityGuard()
    snap_paths = list(paths)
    if tmpl:
        snap_paths.append(tmpl)
    guard.snapshot_before(snap_paths)

    started = _now_cn()
    docs = build_corpus(paths)
    fields = extract_fields(docs)

    issues: list[Issue] = []
    issues.extend(check_placeholders(docs, start_id=1))
    if tmpl:
        issues.extend(check_against_template(docs, tmpl, start_id=1))
    issues.extend(check_consistency(docs, fields, start_id=1))

    integrity = guard.verify_after()
    for item in integrity:
        if not item.unchanged:
            issues.insert(
                0,
                Issue(
                    issue_id="INT-0001",
                    category=IssueCategory.INTEGRITY,
                    severity=Severity.CONFIRMED_ERROR,
                    title="原始文件哈希发生变化",
                    description=(
                        f"「{item.filename}」核查前后 SHA-256 不一致，可能被外部程序改写。"
                    ),
                    evidence=[],
                    rationale=f"before={item.sha256_before}; after={item.sha256_after}",
                    suggestion="立即停止使用该输出，排查是否有写权限软件介入。",
                ),
            )

    notes = [
        "本工具只读核查，默认不对原始 Word/PDF/Excel 执行写操作。",
        "未确认的空缺不会自动填写；无法确认的问题标记为需要人工判断。",
        "不上传企业文件，不调用云端 API。",
        f"UTC 参考时间戳: {datetime.now(timezone.utc).isoformat()}",
    ]

    result = ReviewResult(
        files=docs,
        fields=fields,
        issues=issues,
        integrity=integrity,
        template_path=tmpl,
        started_at=started,
        finished_at=_now_cn(),
        notes=notes,
    )
    report_paths = write_reports(result, output_dir)
    # 再次确认原文件未被报告写入影响
    integrity2 = guard.verify_after()
    result.integrity = integrity2
    return result, report_paths
