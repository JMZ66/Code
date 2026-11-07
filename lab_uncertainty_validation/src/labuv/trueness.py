"""CRM bias and spike recovery. The two designs are not interchangeable."""

from __future__ import annotations

import math

from scipy import stats

from labuv.errors import LabError
from labuv.numbers import fmt, parse_float

MODEL_CRM = "crm-bias"
MODEL_SPIKE = "spike-recovery"
MODEL_LEVELS = "multi-level-recovery-summary"


def crm_bias(payload: dict) -> dict:
    values = [parse_float(value, what="测定值") for value in payload.get("replicates") or []]
    if len(values) < 2:
        raise LabError("CRM 偏倚至少需要 2 次测定。", code="trueness")
    reference = parse_float(payload.get("reference"), what="证书值")
    applicable = bool(payload.get("certificate_uncertainty_applicable"))
    n = len(values)
    mean = sum(values) / n
    variance = sum((value - mean) ** 2 for value in values) / (n - 1)
    standard = math.sqrt(variance)
    bias = mean - reference
    trace = [
        f"CRM 与加标回收不是同一个模型。本次是 CRM 偏倚。",
        f"n={n}，测定均值={fmt(mean)}，样本标准差 s={fmt(standard)}，自由度 {n - 1}。",
        f"偏倚 = 均值 - 证书值 = {fmt(bias)}。",
    ]
    warnings = []
    u_reference = None
    if applicable:
        expanded = parse_float(payload.get("certificate_expanded"), what="证书扩展不确定度")
        k = parse_float(payload.get("certificate_k"), what="证书覆盖因子")
        if expanded < 0 or k <= 0:
            raise LabError("证书扩展不确定度必须非负，覆盖因子必须为正。缺少 k 时不会把它假设成 2。", code="trueness")
        u_reference = expanded / k
        u_bias = math.sqrt(variance / n + u_reference ** 2)
        t_value = bias / u_bias if u_bias else math.inf
        p_value = float(2 * stats.t.sf(abs(t_value), n - 1)) if u_bias else None
        trace.append(f"证书标准不确定度 u_ref = U/k = {fmt(u_reference)}。用户确认该不确定度适用于本次比对。")
        trace.append(f"u(偏倚) = sqrt(s^2/n + u_ref^2) = {fmt(u_bias)}。t = 偏倚/u(偏倚) = {fmt(t_value)}，自由度按 n-1（把 u_ref 视为无额外有限自由度）。")
        trace.append("这是近似检验，不是把证书自由度未知时的严格 Welch 检验伪造成精确结果。")
    else:
        u_bias = None
        t_value = None
        p_value = None
        warnings.append("用户标明证书不确定度不适用。未把证书不确定度放进显著性检验。")
        trace.append("未计算包含证书不确定度的 u(偏倚)。")
    return {
        "model_id": MODEL_CRM,
        "n": n,
        "mean": mean,
        "sd": standard,
        "df": n - 1,
        "bias": bias,
        "u_reference": u_reference,
        "u_bias": u_bias,
        "t": t_value,
        "p": p_value,
        "warnings": warnings,
        "trace": "\n".join(trace),
        "design": "CRM，测定均值与独立证书值比较。",
    }


def spike_recovery(payload: dict) -> dict:
    design = str(payload.get("design") or "")
    if design == "replicates":
        return _replicate_recovery(payload)
    if design == "paired_native":
        return _paired_recovery(payload)
    raise LabError("加标必须选择 replicates（空白或本底可忽略的重复回收）或 paired_native（同一试样加标前后成对）。", code="trueness")


def _replicate_recovery(payload):
    found = [parse_float(value, what="测得值") for value in payload.get("found") or []]
    if len(found) < 2:
        raise LabError("重复回收至少需要 2 个测得值。", code="trueness")
    added = parse_float(payload.get("added"), what="加入量")
    blank = 0.0 if payload.get("blank") in (None, "") else parse_float(payload.get("blank"), what="空白")
    if added == 0.0:
        raise LabError("加入量为 0，不能计算回收率。", code="division_by_zero")
    recoveries = [(value - blank) / added for value in found]
    return _summarize_recoveries(
        recoveries,
        trace_head=(
            f"加标重复回收。空白={fmt(blank)}，加入量={fmt(added)}。"
            "回收率 = (测得值 - 空白) / 加入量。空白为 0 时必须是用户留空或明确填写 0，软件不另外猜测本底。"
        ),
        spike_uncertainty=payload.get("added_u"),
        added=added,
    )


def _paired_recovery(payload):
    before = [parse_float(value, what="加标前") for value in payload.get("before") or []]
    after = [parse_float(value, what="加标后") for value in payload.get("after") or []]
    if len(before) != len(after) or len(before) < 2:
        raise LabError("成对加标要求加标前后行数相同且至少 2 对。不会把长短不同的序列配成对。", code="trueness")
    added = parse_float(payload.get("added"), what="加入量")
    if added == 0.0:
        raise LabError("加入量为 0，不能计算回收率。", code="division_by_zero")
    dilution = 1.0 if payload.get("dilution_factor") in (None, "") else parse_float(payload.get("dilution_factor"), what="稀释倍数")
    if dilution == 0.0:
        raise LabError("稀释倍数为 0。", code="division_by_zero")
    recoveries = [((after_value - before_value) / dilution) / added for before_value, after_value in zip(before, after)]
    return _summarize_recoveries(
        recoveries,
        trace_head=(
            f"成对加标。回收率 = ((加标后 - 加标前) / 稀释倍数) / 加入量，稀释倍数={fmt(dilution)}。"
            "这不是 CRM 偏倚。"
        ),
        spike_uncertainty=payload.get("added_u"),
        added=added,
    )


def _summarize_recoveries(recoveries, *, trace_head, spike_uncertainty, added):
    n = len(recoveries)
    mean = sum(recoveries) / n
    variance = sum((value - mean) ** 2 for value in recoveries) / (n - 1)
    standard = math.sqrt(variance)
    u_mean = standard / math.sqrt(n)
    warnings = []
    if spike_uncertainty not in (None, ""):
        u_added = parse_float(spike_uncertainty, what="加入量标准不确定度")
        if u_added < 0:
            raise LabError("加入量标准不确定度不能为负。", code="trueness")
        # Mean recovery's relative uncertainty combines the SD of the mean and the spike.
        if mean == 0.0 or added == 0.0:
            raise LabError("回收率均值为 0 或加入量为 0，不能合并加入量不确定度。", code="trueness")
        u_combined = abs(mean) * math.sqrt((u_mean / mean) ** 2 + (u_added / added) ** 2)
        note = f"均值回收率的标准不确定度再计入加入量：{fmt(u_combined)}。只使用重复标准差时的 u(均值) = {fmt(u_mean)}。"
    else:
        u_combined = u_mean
        note = f"未提供加入量不确定度，u(平均回收率) 只来自重复回收率，等于 {fmt(u_mean)}。"
        warnings.append("加入量自身的不确定度未包含在平均回收率的不确定度中。")
    t_value = (mean - 1.0) / u_mean if u_mean else math.inf
    p_value = float(2 * stats.t.sf(abs(t_value), n - 1)) if u_mean else None
    trace = [
        trace_head,
        "各次回收率：" + "，".join(fmt(value) for value in recoveries) + "。",
        f"平均回收率={fmt(mean)}，实验标准差={fmt(standard)}，自由度 {n - 1}。",
        note,
        f"与 1 比较的 t（只用重复标准差，不含加入量不确定度）={fmt(t_value)}，双侧 p={fmt(p_value)}。这不是合格判定。",
    ]
    return {
        "model_id": MODEL_SPIKE,
        "n": n,
        "recoveries": recoveries,
        "mean_recovery": mean,
        "sd": standard,
        "u_mean_repeatability_only": u_mean,
        "u_mean": u_combined,
        "df": n - 1,
        "t_versus_one": t_value,
        "p_versus_one": p_value,
        "warnings": warnings,
        "trace": "\n".join(trace),
        "design": "加标回收",
    }


def multi_level_summary(levels: list[dict]) -> dict:
    if len(levels) < 2:
        raise LabError("多水平汇总至少需要 2 个已经算完的水平。", code="trueness")
    rows = []
    for index, level in enumerate(levels, start=1):
        mean = parse_float(level.get("mean_recovery"), row=index, what="平均回收率")
        u_value = parse_float(level.get("u"), row=index, what="标准不确定度")
        if u_value < 0:
            raise LabError("标准不确定度不能为负。", row=index)
        rows.append({"name": str(level.get("name") or index), "mean": mean, "u": u_value})
    trace = ["各水平分开列出，不自动合并成一个回收率。"]
    for row in rows:
        trace.append(f"水平 {row['name']}：平均回收率 {fmt(row['mean'])}，u={fmt(row['u'])}。")
    weighted = None
    if all(row["u"] > 0 for row in rows):
        weights = [1.0 / row["u"] ** 2 for row in rows]
        weighted_mean = sum(weight * row["mean"] for weight, row in zip(weights, rows)) / sum(weights)
        weighted_u = math.sqrt(1.0 / sum(weights))
        weighted = {"mean": weighted_mean, "u": weighted_u}
        trace.append(
            f"仅当用户另外要求逆方差加权时，加权均值={fmt(weighted_mean)}，u={fmt(weighted_u)}。"
            "权重假设各水平独立且 u 已是该水平均值的标准不确定度。默认报告仍保留分水平结果。"
        )
    return {"model_id": MODEL_LEVELS, "levels": rows, "inverse_variance": weighted, "trace": "\n".join(trace)}
