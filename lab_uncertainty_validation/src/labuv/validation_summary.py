"""Validation summary. Criteria come only from the user."""

from __future__ import annotations

import math

from labuv.errors import LabError
from labuv.numbers import fmt, parse_float


def summarize(payload: dict) -> dict:
    characteristics = []
    for index, row in enumerate(payload.get("characteristics") or [], start=1):
        name = str(row.get("name") or "").strip()
        if not name:
            raise LabError("性能特性名称为空白。", row=index, column="特性")
        result = row.get("result")
        criterion = row.get("criterion")
        source = str(row.get("criterion_source") or "").strip()
        status, note = _judge(result, criterion, source, index)
        characteristics.append(
            {
                "name": name,
                "result": result,
                "unit": row.get("unit") or "",
                "criterion": criterion,
                "criterion_source": source,
                "status": status,
                "note": note,
            }
        )
    working = _working_range(payload.get("working_range") or {})
    selectivity = _selectivity(payload.get("selectivity") or {})
    robustness = _robustness(payload.get("robustness") or [])
    trace = ["验证总表只使用用户录入的准则。准则或出处空白时状态为未评价。"]
    for row in characteristics:
        trace.append(f"{row['name']}：结果 {row['result']} {row['unit']}，准则 {row['criterion'] or '未录入'}，状态 {row['status']}。{row['note']}")
    trace.append(working["trace"])
    trace.append(selectivity["trace"])
    trace.append(robustness["trace"])
    return {
        "characteristics": characteristics,
        "working_range": working,
        "selectivity": selectivity,
        "robustness": robustness,
        "trace": "\n".join(trace),
        "warnings": ["本表不是 CNAS 认可结论，也不是软件自定的统一合格阈值。"],
    }


def _judge(result, criterion, source, index):
    if criterion in (None, "", {}) or not source:
        return "未评价", "缺少准则或出处。"
    if not isinstance(criterion, dict):
        return "未评价", "准则格式无法比较。"
    try:
        value = parse_float(result, row=index, what="结果")
    except LabError:
        return "未评价", "结果不是可比较的单个数值。"
    low = criterion.get("min")
    high = criterion.get("max")
    if low in (None, "") and high in (None, ""):
        return "未评价", "准则没有上下限。"
    if low not in (None, "") and value < parse_float(low, row=index, what="准则下限"):
        return "不满足", f"按用户录入的准则和出处“{source}”判定。"
    if high not in (None, "") and value > parse_float(high, row=index, what="准则上限"):
        return "不满足", f"按用户录入的准则和出处“{source}”判定。"
    return "满足", f"按用户录入的准则和出处“{source}”判定。这不是软件自定阈值。"


def _working_range(options):
    levels = options.get("tested_levels") or []
    if not levels:
        return {"status": "实验设计不支持结论", "trace": "没有已测浓度水平，不给工作范围结论。"}
    numbers = [parse_float(value, what="已测水平") for value in levels]
    low = min(numbers)
    high = max(numbers)
    trace = f"已测水平最小值 {fmt(low)}，最大值 {fmt(high)}。这只说明这些水平有数据，不是自动的线性范围。"
    claimed = options.get("claimed") or {}
    if claimed.get("min") in (None, "") or claimed.get("max") in (None, ""):
        return {"status": "仅列出已测水平", "min": low, "max": high, "trace": trace + " 未录入声称范围，端点覆盖未评价。"}
    claimed_min = parse_float(claimed.get("min"), what="声称下限")
    claimed_max = parse_float(claimed.get("max"), what="声称上限")
    covered = claimed_min >= low and claimed_max <= high
    trace += f" 声称范围 {fmt(claimed_min)} 至 {fmt(claimed_max)}。端点{'落在' if covered else '没有全部落在'}已测最小和最大之内。这不是内插有效性的证明。"
    return {"status": "端点已覆盖" if covered else "端点未覆盖", "min": low, "max": high, "trace": trace}


def _selectivity(options):
    if not options:
        return {"status": "实验设计不支持结论", "trace": "没有选择性或基体效应数据。"}
    if options.get("slope_matrix") in (None, "") or options.get("slope_solvent") in (None, ""):
        return {"status": "实验设计不支持结论", "trace": "没有同时给出基体斜率和溶剂斜率，不做斜率比较。"}
    b1 = parse_float(options.get("slope_matrix"), what="基体斜率")
    b2 = parse_float(options.get("slope_solvent"), what="溶剂斜率")
    u1 = parse_float(options.get("u_matrix"), what="基体斜率标准不确定度")
    u2 = parse_float(options.get("u_solvent"), what="溶剂斜率标准不确定度")
    if u1 < 0 or u2 < 0:
        raise LabError("斜率标准不确定度不能为负。", code="selectivity")
    denominator = math.sqrt(u1 ** 2 + u2 ** 2)
    if denominator == 0.0:
        return {"status": "无法比较", "trace": "两个斜率的标准不确定度都是 0，不做统计比较。"}
    t_value = (b1 - b2) / denominator
    trace = (
        f"独立斜率差：t = (b_基体 - b_溶剂) / sqrt(u1^2 + u2^2) = {fmt(t_value)}。"
        "没有给出自由度时，不把该 t 换成 p 值或合格结论。实验设计假设两条斜率来自独立实验。"
    )
    return {"status": "已计算斜率差，未评价合格", "t": t_value, "trace": trace}


def _robustness(rows):
    if not rows:
        return {"status": "实验设计不支持结论", "trace": "没有稳健性实验数据。"}
    parsed = []
    for index, row in enumerate(rows, start=1):
        if row.get("difference") in (None, ""):
            return {"status": "实验设计不支持结论", "trace": "稳健性表缺少水平差，只保存原始记录，不给统计结论。"}
        parsed.append(parse_float(row.get("difference"), row=index, what="水平差"))
    mean = sum(parsed) / len(parsed)
    if len(parsed) < 2:
        trace = f"只有 1 个水平差 {fmt(mean)}。不做标准差，也不给稳健性合格结论。"
        return {"status": "描述不足", "trace": trace}
    variance = sum((value - mean) ** 2 for value in parsed) / (len(parsed) - 1)
    trace = (
        f"稳健性水平差的描述统计：n={len(parsed)}，均值={fmt(mean)}，样本标准差={fmt(math.sqrt(variance))}。"
        "这不是 Youden 试验的自动结论，也没有合格阈值。"
    )
    return {"status": "仅描述统计", "mean_difference": mean, "sd": math.sqrt(variance), "trace": trace}
