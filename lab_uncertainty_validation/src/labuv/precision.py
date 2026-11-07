"""Repeatability and intermediate precision.

One-way random-effects ANOVA accepts balanced and unbalanced groups.
A crossed two-factor layout is used only when every cell has the same
positive replication. Other layouts are refused instead of being forced
into a one-way model.
"""

from __future__ import annotations

import math
from collections import defaultdict

from labuv.errors import LabError
from labuv.numbers import fmt, parse_float

MODEL_ONE_WAY = "one-way-random-anova"
MODEL_TWO_WAY = "two-way-balanced-random-interaction"


def analyze_precision(payload: dict) -> dict:
    rows = payload.get("rows") or []
    if len(rows) < 2:
        raise LabError("精密度数据至少需要 2 行，空白行不会被删除。", code="precision")
    parsed = []
    for index, row in enumerate(rows, start=1):
        parsed.append(
            {
                "value": parse_float(row.get("value"), row=index, column="测定值"),
                "factor1": _factor(row.get("factor1"), index, "因素1"),
                "factor2": None if row.get("factor2") in (None, "") else _factor(row.get("factor2"), index, "因素2"),
            }
        )
    design = str(payload.get("design") or "one_way")
    if design == "one_way":
        if any(row["factor2"] is not None for row in parsed):
            raise LabError("数据里有第二个因素。不能把交叉设计套进单因素方差分析。", code="design")
        result = _one_way(parsed)
    elif design == "two_way_balanced":
        if any(row["factor2"] is None for row in parsed):
            raise LabError("二因素设计要求每一行都有两个因素。", code="design")
        result = _two_way(parsed)
    else:
        raise LabError("设计只能是 one_way 或 two_way_balanced。", code="design")
    values = [row["value"] for row in parsed]
    mean = sum(values) / len(values)
    result["n_total"] = len(values)
    result["mean"] = mean
    result["warnings"] = list(result.get("warnings") or [])
    if payload.get("include_rsd"):
        if mean == 0.0:
            raise LabError("均值为 0，不能计算相对标准偏差。", code="rsd")
        result["rsd"] = result["repeatability_sd"] / abs(mean)
        result["trace"] += f"\n重复性相对标准偏差 RSD = s_r / |均值| = {fmt(result['rsd'])}。均值不是 0。"
    future = payload.get("future_mean")
    if future:
        result["future"] = _future(result, future)
        result["trace"] += "\n" + result["future"]["trace"]
    result["assumptions"] = [
        "重复性标准差是单次结果在重复性条件下的标准差，不是均值的标准误。",
        "中间精密度对应所声明的随机效应模型；负的方差分量估计会同时保留原值和截断为 0 的报告值。",
    ]
    return result


def sample_statistics(values) -> dict:
    numbers = [parse_float(value, what="测定值") for value in values]
    if len(numbers) < 2:
        raise LabError("至少需要 2 个数值。", code="precision")
    n = len(numbers)
    mean = sum(numbers) / n
    variance = sum((value - mean) ** 2 for value in numbers) / (n - 1)
    standard = math.sqrt(variance)
    return {
        "n": n,
        "mean": mean,
        "sample_sd": standard,
        "standard_error_of_mean": standard / math.sqrt(n),
        "df": n - 1,
        "trace": (
            f"n={n}，均值={fmt(mean)}，样本标准差 s={fmt(standard)}（除以 n-1），"
            f"均值标准误 s/sqrt(n)={fmt(standard / math.sqrt(n))}。二者不是同一个量。"
        ),
    }


def _factor(value, row, column):
    if value is None or str(value).strip() == "":
        raise LabError("因素水平为空白。", row=row, column=column)
    return str(value).strip()


def _one_way(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["factor1"]].append(row["value"])
    if len(groups) < 2:
        raise LabError("单因素中间精密度至少需要 2 个水平。", code="design")
    counts = {key: len(values) for key, values in groups.items()}
    if any(count < 1 for count in counts.values()):
        raise LabError("有因素水平没有数据。", code="design")
    total_n = sum(counts.values())
    grand = sum(sum(values) for values in groups.values()) / total_n
    within = 0.0
    between = 0.0
    for values in groups.values():
        mean = sum(values) / len(values)
        within += sum((value - mean) ** 2 for value in values)
        between += len(values) * (mean - grand) ** 2
    df_within = total_n - len(groups)
    df_between = len(groups) - 1
    if df_within <= 0:
        raise LabError("每个水平都只有 1 次测定时，不能分离重复性方差。请改用只有重复的设计，或不要声称已分离重复性。", code="design")
    ms_within = within / df_within
    ms_between = between / df_between
    n0 = (total_n - sum(count ** 2 for count in counts.values()) / total_n) / df_between
    raw_between = (ms_between - ms_within) / n0
    reported_between = raw_between
    warnings = []
    if raw_between < 0.0:
        reported_between = 0.0
        warnings.append(f"水平间方差的矩估计为 {fmt(raw_between)}，是负数。报告用的该分量取 0，原始负值同时保留。")
    repeatability = math.sqrt(ms_within)
    intermediate = math.sqrt(ms_within + reported_between)
    balanced = len(set(counts.values())) == 1
    trace = (
        f"单因素随机效应 ANOVA。水平数 {len(groups)}，总次数 {total_n}，{'平衡' if balanced else '不平衡'}。"
        f"MSW={fmt(ms_within)}（自由度 {df_within}），MSB={fmt(ms_between)}（自由度 {df_between}），n0={fmt(n0)}。"
        f"重复性方差 = MSW = {fmt(ms_within)}，水平间方差矩估计 = {fmt(raw_between)}。"
        f"重复性标准差 s_r = {fmt(repeatability)}。中间精密度标准差（单次结果）s_I = {fmt(intermediate)}。"
    )
    return {
        "model_id": MODEL_ONE_WAY,
        "repeatability_variance": ms_within,
        "between_variance_raw": raw_between,
        "between_variance_reported": reported_between,
        "repeatability_sd": repeatability,
        "intermediate_sd": intermediate,
        "df_within": df_within,
        "df_between": df_between,
        "n0": n0,
        "balanced": balanced,
        "warnings": warnings,
        "trace": trace,
    }


def _two_way(rows):
    cells = defaultdict(list)
    factor_a = set()
    factor_b = set()
    for row in rows:
        factor_a.add(row["factor1"])
        factor_b.add(row["factor2"])
        cells[(row["factor1"], row["factor2"])].append(row["value"])
    a_levels = sorted(factor_a)
    b_levels = sorted(factor_b)
    counts = [len(cells[(a, b)]) for a in a_levels for b in b_levels if (a, b) in cells]
    expected = len(a_levels) * len(b_levels)
    if len(cells) != expected or len(set(counts)) != 1 or counts[0] < 2:
        raise LabError(
            "二因素交叉设计只在每个格子都有、且重复次数完全相同且至少为 2 时计算。"
            "不平衡或缺少格子的设计被拒绝，不会改成单因素。",
            code="design",
        )
    n = counts[0]
    a = len(a_levels)
    b = len(b_levels)
    cell_mean = {(aa, bb): sum(cells[(aa, bb)]) / n for aa in a_levels for bb in b_levels}
    grand = sum(cell_mean.values()) / (a * b)
    mean_a = {aa: sum(cell_mean[(aa, bb)] for bb in b_levels) / b for aa in a_levels}
    mean_b = {bb: sum(cell_mean[(aa, bb)] for aa in a_levels) / a for bb in b_levels}
    ss_a = b * n * sum((mean_a[aa] - grand) ** 2 for aa in a_levels)
    ss_b = a * n * sum((mean_b[bb] - grand) ** 2 for bb in b_levels)
    ss_ab = n * sum((cell_mean[(aa, bb)] - mean_a[aa] - mean_b[bb] + grand) ** 2 for aa in a_levels for bb in b_levels)
    ss_e = sum((value - cell_mean[(aa, bb)]) ** 2 for (aa, bb), values in cells.items() for value in values)
    df_a, df_b, df_ab, df_e = a - 1, b - 1, (a - 1) * (b - 1), a * b * (n - 1)
    ms_a, ms_b, ms_ab, ms_e = ss_a / df_a, ss_b / df_b, ss_ab / df_ab, ss_e / df_e
    raw = {
        "error": ms_e,
        "interaction": (ms_ab - ms_e) / n,
        "factor1": (ms_a - ms_ab) / (b * n),
        "factor2": (ms_b - ms_ab) / (a * n),
    }
    reported = {}
    warnings = []
    for key, value in raw.items():
        if value < 0.0:
            reported[key] = 0.0
            warnings.append(f"方差分量 {key} 的矩估计为 {fmt(value)}。报告值取 0，并保留这个负值。")
        else:
            reported[key] = value
    repeatability = math.sqrt(reported["error"])
    intermediate = math.sqrt(sum(reported.values()))
    trace = (
        f"平衡二因素随机效应（含交互）。因素1水平 {a}，因素2水平 {b}，每格重复 {n}。"
        f"MS1={fmt(ms_a)}，MS2={fmt(ms_b)}，MS12={fmt(ms_ab)}，MSE={fmt(ms_e)}。"
        f"方差分量原始值 { {key: fmt(value) for key, value in raw.items()} }。"
        f"重复性标准差 = {fmt(repeatability)}。两个因素都变化时的单次中间精密度标准差 = {fmt(intermediate)}。"
    )
    return {
        "model_id": MODEL_TWO_WAY,
        "components_raw": raw,
        "components_reported": reported,
        "repeatability_sd": repeatability,
        "intermediate_sd": intermediate,
        "repeatability_variance": reported["error"],
        "warnings": warnings,
        "trace": trace,
        "df": {"factor1": df_a, "factor2": df_b, "interaction": df_ab, "error": df_e},
    }


def _future(result, future):
    if result["model_id"] != MODEL_ONE_WAY:
        raise LabError("未来均值的标准不确定度目前只按单因素模型给出。", code="design")
    days = int(future.get("days"))
    replicates = int(future.get("replicates_per_day"))
    if days < 1 or replicates < 1:
        raise LabError("未来测量的天数和每日重复次数都必须至少为 1。", code="design")
    variance = result["between_variance_reported"] / days + result["repeatability_variance"] / (days * replicates)
    standard = math.sqrt(variance)
    return {
        "u": standard,
        "trace": (
            f"若未来结果是 {days} 天、每天 {replicates} 次的均值，其标准不确定度取 "
            f"sqrt(s_day^2/p + s_r^2/(n p)) = {fmt(standard)}。这不是验证数据自身均值的标准误。"
        ),
    }
