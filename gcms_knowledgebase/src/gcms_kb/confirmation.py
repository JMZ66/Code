from __future__ import annotations

from gcms_kb.constants import (
    BASIS_REVIEW,
    BASIS_STANDARD,
    DECISION_MANUAL,
    DECISION_STANDARD,
)
from gcms_kb.errors import ValidationError


def validate_confirmation(record: dict) -> None:
    decision = record.get("decision")
    basis = record.get("basis")
    if decision not in (DECISION_STANDARD, DECISION_MANUAL):
        raise ValidationError("结论类型无效。谱库相似度不能直接保存为鉴定。")
    if decision == DECISION_STANDARD and basis != BASIS_STANDARD:
        raise ValidationError("标准品确认的依据必须是标准品对照（保留时间/保留指数与谱图）。")
    if decision == DECISION_MANUAL and basis != BASIS_REVIEW:
        raise ValidationError("人工审核的依据必须是审核人判断。")
    if not str(record.get("compound_name") or "").strip():
        raise ValidationError("请填写化合物名称。")
    if not str(record.get("user_name") or "").strip():
        raise ValidationError("请先在设置里填写操作者姓名。确认记录必须留下人名。")
    evidence = str(record.get("evidence") or "").strip()
    detail = str(record.get("basis_detail") or "").strip()
    if not evidence:
        raise ValidationError("必须填写证据说明。")
    if not detail:
        raise ValidationError("必须填写依据摘要。")
    if decision == DECISION_STANDARD and len(evidence) < 8:
        raise ValidationError("请写明标准品对照的具体证据，包括保留时间、保留指数和谱图比较。")


def validate_unknown(record: dict) -> None:
    if not str(record.get("user_name") or "").strip():
        raise ValidationError("请先在设置里填写操作者姓名。")
    if not str(record.get("note") or "").strip():
        raise ValidationError("请填写未知峰说明。")
    if record.get("rt") is None:
        raise ValidationError("未知峰需要保留时间。")
