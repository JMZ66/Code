"""Top-down models that are not one formula applied to every data set.

The implemented equations are printed in the trace. Pieces of the 2026
Eurachem/CITAC guide whose extracted equations could not be read unambiguously
are not calculated.
"""

from __future__ import annotations

import math

from labuv.errors import LabError
from labuv.numbers import fmt, parse_float

MODEL_RELATIVE = "topdown-relative-precision-recovery"
MODEL_ABSOLUTE = "topdown-absolute-precision-bias"
MODEL_RECOVERY = "mupr-2026-eq8-eq9-mean-recovery"
MODEL_FUTURE = "future-single-crm"


def evaluate_topdown(payload: dict) -> dict:
    model = str(payload.get("model") or "")
    if model == "relative":
        return _relative(payload)
    if model == "absolute":
        return _absolute(payload)
    if model == "mean_recovery":
        return _mean_recovery(payload)
    if model == "future_single_crm":
        return _future_single(payload)
    raise LabError(
        "自上而下模型必须明确选择：relative、absolute、mean_recovery 或 future_single_crm。不存在一个用于所有项目的默认模型。",
        code="topdown",
    )


def _overlap_guard(payload):
    flag = payload.get("precision_includes_recovery")
    if flag is None:
        raise LabError(
            "必须声明精密度是否已经包含回收率变动。不声明时不合成，以免把同一效应算两次。",
            code="double_count",
        )
    if bool(flag):
        raise LabError(
            "用户声明精密度已经包含回收率变动。本次拒绝再把回收率不确定度加进去。请改用只含精密度的模型，或更正该声明。",
            code="double_count",
        )


def _relative(payload):
    _overlap_guard(payload)
    value = parse_float(payload.get("value"), what="测定值")
    if value == 0.0:
        raise LabError("测定值为 0。相对不确定度模型不能把相对分量乘到 0 上假装得到绝对不确定度。", code="topdown")
    rsd = parse_float(payload.get("intermediate_rsd"), what="中间精密度相对标准差")
    if rsd < 0:
        raise LabError("相对标准差不能为负。", code="topdown")
    recovery = parse_float(payload.get("mean_recovery"), what="平均回收率")
    u_recovery = parse_float(payload.get("u_recovery"), what="平均回收率标准不确定度")
    if recovery == 0.0 or u_recovery < 0:
        raise LabError("平均回收率不能为 0，其标准不确定度不能为负。", code="topdown")
    extras = [_positive_relative(item) for item in payload.get("additional_relative") or []]
    correct = bool(payload.get("correct_recovery"))
    if correct:
        result = value / recovery
        u_rel = math.sqrt(rsd ** 2 + (u_recovery / recovery) ** 2 + sum(item ** 2 for item in extras))
        equation = "修正回收率：y = x / R，u(y)/|y| = sqrt(RSD_I^2 + (u(R)/R)^2 + Σu_add^2)"
    else:
        result = value
        u_rel = math.sqrt(rsd ** 2 + u_recovery ** 2 + sum(item ** 2 for item in extras))
        equation = (
            "不修正回收率：y = x，u(y)/|y| = sqrt(RSD_I^2 + u(R)^2 + Σu_add^2)。"
            "这里的 u(R) 是回收率因子的标准不确定度，不是 u(R)/R。"
        )
    uc = abs(result) * u_rel
    trace = [
        "相对自上而下模型。适用条件：该浓度附近相对中间精密度近似恒定，且用户声明回收率不确定度没有包含在精密度里。",
        equation,
        f"x={fmt(value)}，RSD_I={fmt(rsd)}，R={fmt(recovery)}，u(R)={fmt(u_recovery)}。",
        f"y={fmt(result)}，uc={fmt(uc)}。",
        "结构对应 Eurachem/CITAC MUPR 2026 第9节的相对合成；文本提取中的式(20)是相对形式。式(19)的排版提取不完整，所以不把本式编号成式(19)。",
        "k=2 时可形成扩展不确定度，但 k=2 不是无条件精确 95%。本次不自动乘 k，除非用户在覆盖栏填写。",
    ]
    if payload.get("k") not in (None, ""):
        k = parse_float(payload.get("k"), what="覆盖因子")
        if k <= 0:
            raise LabError("覆盖因子必须为正。", code="coverage")
        trace.append(f"用户指定 k={fmt(k)}，U={fmt(k * uc)}。")
        expanded = k * uc
    else:
        expanded = None
    return _pack(MODEL_RELATIVE, result, uc, expanded, trace, payload.get("unit") or "")


def _absolute(payload):
    _overlap_guard(payload)
    value = parse_float(payload.get("value"), what="测定值")
    s_i = parse_float(payload.get("intermediate_sd"), what="中间精密度标准差")
    u_bias = parse_float(payload.get("u_bias"), what="偏倚标准不确定度")
    if s_i < 0 or u_bias < 0:
        raise LabError("标准差和偏倚不确定度不能为负。", code="topdown")
    extras = [parse_float(item, what="附加标准不确定度") for item in payload.get("additional_absolute") or []]
    if any(item < 0 for item in extras):
        raise LabError("附加标准不确定度不能为负。", code="topdown")
    uc = math.sqrt(s_i ** 2 + u_bias ** 2 + sum(item ** 2 for item in extras))
    trace = [
        "绝对自上而下模型：uc = sqrt(s_I^2 + u_bias^2 + Σu_add^2)。",
        "适用条件：该浓度附近绝对中间精密度近似恒定，各分量用同一单位，且用户声明没有重复计入。",
        f"y={fmt(value)}，s_I={fmt(s_i)}，u_bias={fmt(u_bias)}，uc={fmt(uc)}。",
    ]
    return _pack(MODEL_ABSOLUTE, value, uc, None, trace, payload.get("unit") or "")


def _mean_recovery(payload):
    materials = payload.get("materials") or []
    if len(materials) < 1:
        raise LabError("平均回收率至少需要一份参考物质。", code="topdown")
    rows = []
    for index, material in enumerate(materials, start=1):
        mean = parse_float(material.get("mean"), row=index, what="测定均值")
        reference = parse_float(material.get("reference"), row=index, what="参考值")
        standard = parse_float(material.get("sd"), row=index, what="标准差")
        n = material.get("n")
        if reference == 0.0 or mean == 0.0:
            raise LabError("参考值或测定均值为 0，不能按式(8)计算回收率。", row=index, code="division_by_zero")
        if standard < 0:
            raise LabError("标准差不能为负。", row=index)
        try:
            count = int(n)
        except (TypeError, ValueError) as exc:
            raise LabError("重复次数无效。", row=index) from exc
        if count < 1:
            raise LabError("重复次数必须至少为 1。", row=index)
        u_reference = parse_float(material.get("u_reference"), row=index, what="参考值标准不确定度")
        if u_reference < 0:
            raise LabError("参考值标准不确定度不能为负。", row=index)
        recovery = mean / reference
        u_recovery_sq = recovery ** 2 * ((standard / (mean * math.sqrt(count))) ** 2 + (u_reference / reference) ** 2)
        rows.append({"recovery": recovery, "u2": u_recovery_sq, "n": count})
    count_materials = len(rows)
    mean_recovery = sum(row["recovery"] for row in rows) / count_materials
    u_mean = math.sqrt(sum(row["u2"] for row in rows)) / count_materials
    trace = [
        "独立参考物质或空白加标的平均回收率，按 Eurachem/CITAC MUPR 2026 式(8)和式(9)。",
        "R_i = 测定均值 / 参考值，R̄ = Σ R_i / N。",
        "u(R_i)^2 = R_i^2·[(s_i /(均值·sqrt(n_i)))^2 + (u(参考值)/参考值)^2]，u(R̄)=sqrt(Σ u(R_i)^2)/N。",
        "各物质按独立处理，且不做逆方差加权；指南说明加权只在不确定度明显不同且有意使用时才考虑，这里不自动加权。",
        f"N={count_materials}，R̄={fmt(mean_recovery)}，u(R̄)={fmt(u_mean)}。",
    ]
    for index, row in enumerate(rows, start=1):
        trace.append(f"物质 {index}：R={fmt(row['recovery'])}，u(R)={fmt(math.sqrt(row['u2']))}，n={row['n']}。")
    decision = {"status": "未评价"}
    if payload.get("use_k2"):
        total = sum(row["n"] for row in rows)
        if total < 10:
            decision = {"status": "未评价", "reason": "回收测定总次数少于 10，不采用指南中“多于 10 次可用 2”的比较。"}
        else:
            limit = 2.0 * u_mean
            equivalent = abs(1.0 - mean_recovery) <= limit
            decision = {
                "status": "按用户选择的 k=2 比较",
                "equivalent_to_one": equivalent,
                "limit": limit,
                "reason": "用户选择使用 2。这不是数据自动满足的 t 分布临界值。",
            }
        trace.append(decision["reason"] + f" |1-R̄|={fmt(abs(1 - mean_recovery))}，2·u={fmt(2 * u_mean)}。")
    else:
        trace.append("未指定自由度或覆盖系数，因此不判断平均回收率是否可视为 1。状态：未评价。")
    trace.append("若 |1-R̄| 不超过临界值，指南允许把回收率取为 1 且不修正结果；本函数只计算回收率及其不确定度，不自动改写样品结果。")
    return {
        "model_id": MODEL_RECOVERY,
        "mean_recovery": mean_recovery,
        "u_recovery": u_mean,
        "decision": decision,
        "trace": "\n".join(trace),
        "warnings": ["式(8)、式(9) 已用公开例题的数值代入核对。附录 A 的浓度模型和第 8.3 节均方误差放大没有实现。"],
        "unit": "1",
        "y": mean_recovery,
        "uc": u_mean,
    }


def _future_single(payload):
    if not payload.get("certificate_applicable"):
        raise LabError("证书不确定度未确认为适用，不能把它放进未来单次结果的不确定度。", code="topdown")
    value = parse_float(payload.get("value"), what="未来单次测定值")
    s_future = parse_float(payload.get("single_sd"), what="单次结果标准差")
    s_validation = parse_float(payload.get("validation_sd"), what="验证标准差")
    try:
        n = int(payload.get("validation_n"))
    except (TypeError, ValueError) as exc:
        raise LabError("验证次数无效。", code="topdown") from exc
    u_reference = parse_float(payload.get("u_reference"), what="证书标准不确定度")
    bias = 0.0 if payload.get("bias") in (None, "") else parse_float(payload.get("bias"), what="偏倚")
    if n < 2 or s_future < 0 or s_validation < 0 or u_reference < 0:
        raise LabError("验证次数、标准差或证书标准不确定度无效。", code="topdown")
    correct = bool(payload.get("correct_bias"))
    result = value - bias if correct else value
    uc = math.sqrt(s_future ** 2 + (s_validation ** 2) / n + u_reference ** 2)
    trace = [
        "未来单次结果。不修正时 y=x；修正时 y=x-偏倚。",
        "uc = sqrt(s_未来单次^2 + s_验证^2/n_验证 + u_证书^2)。",
        "s_验证^2/n 是偏倚估计的随机部分，s_未来单次是另一次测量的标准差，二者不是重复相加同一个均值标准误。",
        f"y={fmt(result)}，uc={fmt(uc)}。偏倚{'已修正' if correct else '未修正'}。",
    ]
    return _pack(MODEL_FUTURE, result, uc, None, trace, payload.get("unit") or "")


def _positive_relative(value):
    number = parse_float(value, what="附加相对标准不确定度")
    if number < 0:
        raise LabError("附加相对标准不确定度不能为负。", code="topdown")
    return number


def _pack(model, y, uc, expanded, trace, unit):
    return {
        "model_id": model,
        "y": y,
        "uc": uc,
        "expanded": expanded,
        "unit": unit,
        "trace": "\n".join(trace),
        "warnings": [],
    }
