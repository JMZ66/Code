"""Bottom-up uncertainty: JCGM 100:2008 first-order propagation.

Welch–Satterthwaite (Annex G.4) is used only when every off-diagonal
correlation is zero. Correlated inputs still get a combined standard
uncertainty from equation (13); they do not get an effective degrees of
freedom. Monte Carlo is delegated to montecarlo.py.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

from labuv.errors import LabError
from labuv.expression import compile_expression, second_derivative_diagnostic
from labuv.numbers import fmt, parse_float
from labuv.units import (
    base_magnitudes,
    calculation_magnitude,
    compatible,
    conversion_factor,
    evaluate_quantity,
    parse_unit,
    to_base_scale,
    unit_text,
    ureg,
)
from labuv.version import ENGINE_VERSION, MODEL_BOTTOM_UP

_CORR_ATOL = 1e-8


def evaluate_bottom_up(payload: dict) -> dict:
    expression = compile_expression(payload.get("expression", ""))
    inputs = _prepare_inputs(payload.get("inputs") or [], expression.names)
    correlation, correlated = _correlation(expression.names, payload.get("correlation"), payload.get("correlation_names"))
    magnitudes = {item["name"]: item["magnitude"] for item in inputs}
    units = {item["name"]: item["calc_unit"] for item in inputs}
    quantity = evaluate_quantity(expression.source, magnitudes, units)
    bases, scales = base_magnitudes(magnitudes, units)
    y_base, gradient_base = expression.value_and_gradient(bases)
    _same(y_base, float(quantity.to_base_units().magnitude), "按基本单位计算的结果与按输入单位直接计算的结果")
    report_unit = _report_unit(quantity.units, payload.get("expected_unit"), payload.get("report_unit"))
    y_scale = conversion_factor(quantity.to_base_units().units, report_unit)
    y_value = y_base * y_scale
    _same(y_value, float(quantity.to(report_unit).magnitude), "报告单位下的结果")

    sensitivities = {}
    for item in inputs:
        # dy_report / dx_user, with x_user in the calculation magnitude's unit.
        sensitivities[item["name"]] = gradient_base[item["name"]] * y_scale * scales[item["name"]]

    u_user = np.array([item["u"] for item in inputs], dtype=float)
    names = [item["name"] for item in inputs]
    c = np.array([sensitivities[name] for name in names], dtype=float)
    covariance = np.outer(u_user, u_user) * correlation
    variance = float(c @ covariance @ c)
    if variance < 0.0 and variance > -1e-18:
        variance = 0.0
    if variance < 0.0 or not math.isfinite(variance):
        raise LabError("合成方差为负或非有限，已拒绝给出合成标准不确定度。", code="variance")
    uc = math.sqrt(variance)
    contributions = c * u_user
    shares = _variance_shares(c, covariance, variance)

    trace = []
    warnings = []
    if expression.literals:
        warnings.append(
            "表达式含有除 -1、0、1 以外的纯数字。纯数字按无量纲处理，不会把“mL/1000”自动变成 L。"
            "请把换算交给单位，不要把换算系数写进表达式。"
        )
    trace.append(f"模型：{payload.get('output_name') or 'y'} = {expression.source}")
    trace.append(f"报告单位：{unit_text(report_unit)}")
    trace.append("各输入的原始数值已保留。百分数单位会在计算前换成小数，并在下面写明。")
    for item in inputs:
        trace.append(item["trace"])
        trace.append(
            f"  灵敏系数 c({item['name']}) = {fmt(sensitivities[item['name']])} "
            f"{unit_text(report_unit)} / {item['unit_label']}"
        )
        trace.append(
            f"  分量 c·u = {fmt(contributions[names.index(item['name'])])} {unit_text(report_unit)}；"
            f"方差分解份额 = {fmt(shares[names.index(item['name'])] * 100)} %（相关时份额可以是负数，且不以各项平方和为唯一分摊）。"
        )
    trace.append("合成标准不确定度来自 JCGM 100:2008 式(10)（输入不相关）或式(13)（输入相关）：uc = sqrt(c^T Cov c)。")
    trace.append(f"y = {fmt(y_value)} {unit_text(report_unit)}")
    trace.append(f"uc(y) = {fmt(uc)} {unit_text(report_unit)}")
    trace.append("这里的 uc 是标准不确定度，不是扩展不确定度，也不是置信区间半宽。")

    ws = _welch_satterthwaite(contributions, [item["df"] for item in inputs], uc, correlated)
    trace.extend(ws["trace"])
    warnings.extend(ws["warnings"])

    coverage = _coverage(payload.get("coverage") or {"mode": "k", "k": 2}, uc, ws["veff"], correlated, ws["applicable"])
    trace.extend(coverage["trace"])
    warnings.extend(coverage["warnings"])

    diagnostic = _nonlinearity(expression, bases, covariance, scales, y_scale, uc)
    trace.extend(diagnostic["trace"])
    warnings.extend(diagnostic["warnings"])

    monte_carlo = None
    if (payload.get("monte_carlo") or {}).get("enabled"):
        from labuv.montecarlo import run_monte_carlo

        monte_carlo = run_monte_carlo(
            expression,
            inputs,
            correlation,
            scales,
            y_scale,
            payload["monte_carlo"],
            gum_y=y_value,
            gum_uc=uc,
            gum_expanded=coverage.get("expanded"),
        )
        trace.extend(monte_carlo["trace"])
        warnings.extend(monte_carlo["warnings"])

    budget = []
    for index, item in enumerate(inputs):
        budget.append(
            {
                "name": item["name"],
                "estimate": item["estimate_display"],
                "unit": item["unit_label"],
                "distribution": item["distribution_label"],
                "u": item["u"],
                "df": item["df"],
                "sensitivity": sensitivities[item["name"]],
                "contribution": float(contributions[index]),
                "variance_share": float(shares[index]),
                "source": item["source"],
                "kind": item["kind"],
            }
        )
    return {
        "model_id": MODEL_BOTTOM_UP,
        "engine_version": ENGINE_VERSION,
        "expression": expression.source,
        "output_name": payload.get("output_name") or "y",
        "y": y_value,
        "unit": unit_text(report_unit),
        "uc": uc,
        "veff": ws["veff"],
        "veff_applicable": ws["applicable"],
        "coverage": coverage,
        "budget": budget,
        "warnings": warnings,
        "trace": "\n".join(trace),
        "assumptions": _assumptions(correlated, ws["applicable"], coverage),
        "monte_carlo": monte_carlo,
        "nonlinearity": diagnostic["summary"],
        "display": {
            "y": fmt(y_value),
            "uc": fmt(uc),
            "U": fmt(coverage.get("expanded")),
            "k": fmt(coverage.get("k")),
        },
    }


def _prepare_inputs(rows, names: list[str]) -> list[dict]:
    if not isinstance(rows, list) or not rows:
        raise LabError("没有输入量。", code="inputs")
    prepared = []
    seen = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise LabError("输入量格式错误。", row=index, code="inputs")
        name = str(row.get("name") or "").strip()
        if name == "":
            raise LabError("输入量名称为空白。", row=index, column="名称")
        if name in seen:
            raise LabError(f"输入量名称“{name}”重复。", row=index, column="名称")
        seen.add(name)
        if name not in names:
            raise LabError(f"输入量“{name}”没有出现在表达式中。未使用的输入不会被悄悄丢弃，请删除或写入表达式。", row=index)
        unit = parse_unit(row.get("unit"))
        kind = str(row.get("kind") or "").strip().upper()
        if kind not in ("A", "B"):
            raise LabError("输入类型必须是 A 或 B。", row=index, column="类型")
        if kind == "A":
            item = _type_a(row, name, unit, index)
        else:
            item = _type_b(row, name, unit, index)
        prepared.append(item)
    missing = [name for name in names if name not in seen]
    if missing:
        raise LabError("表达式中的这些量没有输入：" + "、".join(missing), code="missing_input")
    order = {name: position for position, name in enumerate(names)}
    prepared.sort(key=lambda item: order[item["name"]])
    return prepared


def _type_a(row, name, unit, index) -> dict:
    role = str(row.get("role") or "").strip().lower()
    if role not in ("single", "mean"):
        raise LabError("A 类必须明确用于“single”（单次结果）或“mean”（重复数据的均值）。", row=index, column="用途")
    raw_values = row.get("raw")
    if not isinstance(raw_values, (list, tuple)) or len(raw_values) < 2:
        raise LabError("A 类至少需要 2 个原始重复值，空值不会被自动剔除。", row=index, column="原始数据")
    values = [parse_float(value, row=index, column="原始数据", what="重复值") for value in raw_values]
    n = len(values)
    mean = sum(values) / n
    variance = sum((value - mean) ** 2 for value in values) / (n - 1)
    standard_deviation = math.sqrt(variance)
    df = n - 1
    if role == "mean":
        if row.get("estimate") not in (None, ""):
            given = parse_float(row.get("estimate"), row=index, column="估计值")
            scale = max(1.0, abs(mean))
            if abs(given - mean) > 1e-8 * scale:
                raise LabError(
                    f"填写的估计值 {given} 与重复数据均值 {mean} 不一致。软件不会用均值悄悄替换原始估计值。",
                    row=index,
                    column="估计值",
                )
        estimate = mean
        standard_u = standard_deviation / math.sqrt(n)
        role_text = f"均值（n={n}），标准不确定度取实验标准差除以 sqrt(n)，自由度 {df}"
        distribution = "JCGM 101 移位标度 t（由重复均值得到）"
    else:
        if row.get("estimate") in (None, ""):
            raise LabError("单次结果必须单独填写估计值。重复数据只用来计算实验标准差，不会被当成这一次的结果。", row=index, column="估计值")
        estimate = parse_float(row.get("estimate"), row=index, column="估计值")
        standard_u = standard_deviation
        role_text = f"单次结果，标准不确定度取重复实验的实验标准差 s，自由度 {df}。这不是把均值当作该次结果。"
        distribution = "JCGM 101 形式的移位标度 t（尺度为实验标准差 s）"
    magnitude, calc_unit = calculation_magnitude(estimate, unit)
    u_magnitude, _ = calculation_magnitude(standard_u, unit)
    sample = {"kind": "scaled_t", "loc_user": magnitude, "scale_user": u_magnitude, "df": df, "half_user": None}
    trace = (
        f"A 类 {name}：n={n}，均值={fmt(mean)}，实验标准差 s={fmt(standard_deviation)} {unit_text(unit)}。"
        f"{role_text}。u={fmt(u_magnitude)}（计算用量）。来源：{row.get('source') or '未填写'}。"
    )
    if is_percent_unit(unit):
        trace += f" 原始估计按百分数保留为 {fmt(estimate)} %，计算用小数 {fmt(magnitude)}。"
    return _input_dict(name, estimate, magnitude, unit, calc_unit, "A", u_magnitude, df, distribution, sample, trace, row)


def _type_b(row, name, unit, index) -> dict:
    distribution = str(row.get("distribution") or "").strip().lower()
    mode = str(row.get("u_mode") or "").strip().lower()
    if distribution not in ("normal", "rectangular", "triangular"):
        raise LabError("B 类分布只实现正态、矩形和三角。", row=index, column="分布")
    df = _optional_df(row.get("df"), index)
    if distribution == "normal" and mode == "standard":
        u_value = parse_float(row.get("u"), row=index, column="标准不确定度", what="标准不确定度")
        if u_value < 0:
            raise LabError("标准不确定度不能为负。", row=index, column="标准不确定度")
        standard_u = u_value
        half = None
        explanation = "正态分布，用户直接给出标准不确定度 u。Monte Carlo 按 N(x, u^2) 抽样，不把分布截断。"
        if df is not None:
            raise LabError("直接给出标准不确定度的正态 B 类按无穷自由度处理。有限自由度的重复数据请用 A 类。", row=index, column="自由度")
        df = math.inf
        sample_kind = "normal"
    elif distribution == "normal" and mode in ("expanded", "half_width_k"):
        half = parse_float(row.get("half_width"), row=index, column="半宽", what="半宽")
        k = parse_float(row.get("k"), row=index, column="k", what="覆盖因子")
        if half < 0 or k <= 0:
            raise LabError("正态半宽必须非负，覆盖因子 k 必须为正。u = a/k，a 是从估计值到边界的半宽，不是全宽。", row=index)
        standard_u = half / k
        explanation = f"正态分布，半宽 a={fmt(half)}，覆盖因子 k={fmt(k)}，标准不确定度 u=a/k。k 不是矩形分布的 √3。"
        df = math.inf
        sample_kind = "normal"
    elif distribution in ("rectangular", "triangular") and mode == "half_width":
        half = parse_float(row.get("half_width"), row=index, column="半宽", what="半宽")
        if half < 0:
            raise LabError("半宽不能为负。", row=index, column="半宽")
        divisor = math.sqrt(3.0) if distribution == "rectangular" else math.sqrt(6.0)
        standard_u = half / divisor
        clause = "JCGM 100:2008 第4.3.7节，u=a/√3" if distribution == "rectangular" else "JCGM 100:2008 第4.3.9节，u=a/√6"
        explanation = f"{'矩形' if distribution == 'rectangular' else '三角'}分布，半宽 a={fmt(half)}，{clause}。a 是半宽。"
        df = math.inf
        sample_kind = "uniform" if distribution == "rectangular" else "triangular"
    else:
        raise LabError(
            "B 类组合无效。正态可用“standard”或“half_width_k”；矩形和三角只用“half_width”，避免把半宽和标准偏差混用。",
            row=index,
        )
    if row.get("estimate") in (None, ""):
        raise LabError("B 类估计值为空白。", row=index, column="估计值")
    estimate = parse_float(row.get("estimate"), row=index, column="估计值")
    magnitude, calc_unit = calculation_magnitude(estimate, unit)
    u_magnitude, _ = calculation_magnitude(standard_u, unit)
    half_magnitude = None if half is None else calculation_magnitude(half, unit)[0]
    sample = {"kind": sample_kind, "loc_user": magnitude, "scale_user": u_magnitude, "df": None, "half_user": half_magnitude}
    trace = (
        f"B 类 {name}：估计值 {fmt(estimate)} {unit_text(unit)}。{explanation} u={fmt(u_magnitude)}（计算用量）。"
        f"来源：{row.get('source') or '未填写'}。"
    )
    return _input_dict(
        name, estimate, magnitude, unit, calc_unit, "B", u_magnitude, df,
        explanation, sample, trace, row,
    )


def _input_dict(name, estimate, magnitude, unit, calc_unit, kind, u_value, df, distribution, sample, trace, row):
    return {
        "name": name,
        "estimate_display": estimate,
        "magnitude": magnitude,
        "unit": unit,
        "calc_unit": calc_unit,
        "unit_label": unit_text(calc_unit if is_percent_unit(unit) else unit),
        "kind": kind,
        "u": u_value,
        "df": df,
        "distribution_label": distribution,
        "sample": sample,
        "trace": trace,
        "source": str(row.get("source") or ""),
    }


def is_percent_unit(unit) -> bool:
    return unit == ureg.percent


def _optional_df(value, index):
    if value in (None, "", "inf", "∞"):
        return None
    df = parse_float(value, row=index, column="自由度", what="自由度")
    if df <= 0:
        raise LabError("自由度必须为正。", row=index, column="自由度")
    return df


def _correlation(names, matrix, matrix_names):
    size = len(names)
    if matrix in (None, []):
        return np.eye(size), False
    if matrix_names is None:
        matrix_names = names
    if list(matrix_names) != list(names):
        if sorted(matrix_names) != sorted(names):
            raise LabError("相关矩阵的量名必须与输入量完全一致。", code="correlation")
        reorder = [list(matrix_names).index(name) for name in names]
        matrix = [[matrix[i][j] for j in reorder] for i in reorder]
    try:
        array = np.array(matrix, dtype=float)
    except (TypeError, ValueError) as exc:
        raise LabError("相关矩阵含有非数字。", code="correlation") from exc
    if array.shape != (size, size) or not np.all(np.isfinite(array)):
        raise LabError("相关矩阵必须是与输入量数目相同的有限方阵。", code="correlation")
    if np.max(np.abs(array - array.T)) > _CORR_ATOL:
        raise LabError("相关矩阵不对称。软件没有把它自动改成对称阵。", code="correlation")
    if np.max(np.abs(np.diag(array) - 1.0)) > _CORR_ATOL:
        raise LabError("相关矩阵的对角线必须是 1。", code="correlation")
    if np.max(np.abs(array)) > 1.0 + _CORR_ATOL:
        raise LabError("相关系数超出 [-1, 1]。", code="correlation")
    eigenvalues = np.linalg.eigvalsh(array)
    if float(eigenvalues.min()) < -1e-8:
        raise LabError(
            f"相关矩阵不是正半定矩阵，最小特征值为 {fmt(float(eigenvalues.min()))}。结果已被拒绝。",
            code="correlation",
        )
    correlated = bool(np.max(np.abs(array - np.eye(size))) > 1e-12)
    return array, correlated


def _variance_shares(sensitivity, covariance, variance):
    if variance == 0.0:
        return np.zeros(len(sensitivity))
    # c_i * (Cov c)_i / uc^2 sums to 1 and can be negative when inputs are correlated.
    weighted = covariance @ sensitivity
    return sensitivity * weighted / variance


def _welch_satterthwaite(contributions, degrees, uc, correlated) -> dict:
    trace = []
    warnings = []
    if correlated:
        warnings.append(
            "输入量相关。JCGM 100:2008 附录 G.4 的 Welch–Satterthwaite 式用于不相关分量；"
            "本软件不在未经推导的情况下把独立量有效自由度套到相关量上。"
        )
        trace.append("有效自由度：不适用（存在相关）。")
        return {"applicable": False, "veff": None, "trace": trace, "warnings": warnings}
    if uc == 0.0:
        trace.append("合成标准不确定度为 0，有效自由度不适用。")
        return {"applicable": False, "veff": None, "trace": trace, "warnings": warnings}
    denominator = 0.0
    finite = False
    for contribution, df in zip(contributions, degrees):
        if contribution == 0.0:
            continue
        if df is None or math.isinf(df):
            continue
        finite = True
        denominator += (contribution ** 4) / df
    if not finite or denominator == 0.0:
        trace.append("有效自由度：无穷大（没有有限自由度的非零分量）。")
        return {"applicable": True, "veff": math.inf, "trace": trace, "warnings": warnings}
    veff = (uc ** 4) / denominator
    trace.append(
        f"Welch–Satterthwaite 有效自由度 veff = uc^4 / Σ(u_i(y)^4 / v_i) = {fmt(veff)}。"
        "公式见 JCGM 100:2008 式(G.2b)，只在本次不相关的条件下使用。覆盖因子使用连续 t 分布分位数，不把 veff 向下取整。"
    )
    return {"applicable": True, "veff": veff, "trace": trace, "warnings": warnings}


def _coverage(options, uc, veff, correlated, ws_applicable) -> dict:
    mode = str(options.get("mode") or "k")
    warnings = []
    trace = []
    if mode == "k":
        k = parse_float(options.get("k", 2), what="覆盖因子")
        if k <= 0:
            raise LabError("覆盖因子必须为正。", code="coverage")
        expanded = k * uc
        trace.append(f"扩展不确定度 U = k·uc，k={fmt(k)} 由用户指定，U={fmt(expanded)}。")
        trace.append("k=2 只在输出近似正态且有效自由度很大时约对应 95.45% 的覆盖概率，不是无条件的精确 95%。")
        if ws_applicable and veff is not None and not math.isinf(veff):
            t_value = float(stats.t.ppf(0.975, veff))
            warnings.append(
                f"当前有效自由度有限。若要按约 95% 的 t 分布覆盖，k 约为 {fmt(t_value)}，与用户指定的 k={fmt(k)} 不是同一个数。"
            )
        if correlated:
            warnings.append("相关输入下，这个 k 只是用户指定的乘数，不能解释成由 Welch–Satterthwaite 自由度得到的覆盖概率。")
        return {"mode": "k", "k": k, "p": None, "expanded": expanded, "trace": trace, "warnings": warnings}
    if mode == "probability":
        if not ws_applicable:
            raise LabError(
                "当前条件不能由 t 分布计算覆盖因子。请改用用户指定的 k，或先消除相关后再按概率计算。",
                code="coverage",
            )
        probability = parse_float(options.get("p", 0.95), what="覆盖概率")
        if not 0.0 < probability < 1.0:
            raise LabError("覆盖概率必须在 0 和 1 之间。", code="coverage")
        if veff is None:
            raise LabError("没有可用于 t 分布的自由度。", code="coverage")
        if math.isinf(veff):
            k = float(stats.norm.ppf(0.5 + probability / 2.0))
            distribution = "标准正态"
        else:
            k = float(stats.t.ppf(0.5 + probability / 2.0, veff))
            distribution = f"t 分布（veff={fmt(veff)}）"
        expanded = k * uc
        trace.append(
            f"按用户要求的覆盖概率 p={fmt(probability)}，从{distribution}得到双侧覆盖因子 k={fmt(k)}，U=k·uc={fmt(expanded)}。"
        )
        trace.append("该覆盖概率依赖线性化、输出近似正态或 t 分布以及输入不相关。不满足时，U 不能当成精确置信区间。")
        return {"mode": "probability", "k": k, "p": probability, "expanded": expanded, "trace": trace, "warnings": warnings}
    raise LabError("覆盖方式只能是指定 k 或指定覆盖概率。", code="coverage")


def _nonlinearity(expression, bases, covariance_user, scales, y_scale, uc) -> dict:
    diagnostic = second_derivative_diagnostic(expression, bases)
    if not diagnostic.get("available"):
        return {
            "summary": {"available": False},
            "trace": [f"二阶数值诊断没有完成：{diagnostic.get('reason')}"],
            "warnings": ["未能做非线性诊断。一阶合成标准不确定度仍然给出，但没有用占位的二阶修正冒充完整评定。"],
        }
    # User-space covariance is converted to the base magnitudes used by the Hessian.
    names = expression.names
    scale = np.array([scales[name] for name in names])
    covariance_base = covariance_user * np.outer(scale, scale)
    shift_base = 0.0
    hessian = diagnostic["hessian"]
    for i, name_i in enumerate(names):
        for j, name_j in enumerate(names):
            shift_base += 0.5 * hessian[(name_i, name_j)] * covariance_base[i, j]
    shift = shift_base * y_scale
    warning = []
    if uc > 0 and abs(shift) > 0.2 * uc:
        warning.append(
            "二阶泰勒期望偏移的数值诊断超过 uc 的 20%。JCGM 100 的一阶结果仍按 f(x) 报告，没有把这个偏移偷偷加进结果；"
            "非线性明显时应以 Monte Carlo 为准。JCGM 100:2008/Amd.1:2026 的修订全文本次没有取得，诊断式不是该修订的逐式实现。"
        )
    trace = [
        f"二阶期望偏移的数值诊断（独立或按协方差的多元泰勒一阶修正，仅供判断，不替代 uc）约为 {fmt(shift)}。",
        "报告的测量估计值仍是输入估计处的 f(x)，不是 Monte Carlo 均值。",
    ]
    return {"summary": {"available": True, "shift": shift}, "trace": trace, "warnings": warning}


def _assumptions(correlated, ws_applicable, coverage) -> list[str]:
    items = [
        "合成标准不确定度使用一阶泰勒传播（JCGM 100:2008 式(10)或式(13)）。",
        "标准不确定度、合成标准不确定度和扩展不确定度在结果中分开列出。",
        "k=2 不是无条件的精确 95% 覆盖。",
    ]
    if correlated:
        items.append("已计入相关；有效自由度未计算。")
    elif ws_applicable:
        items.append("输入按不相关处理，并在适用时给出 Welch–Satterthwaite 有效自由度。")
    if coverage.get("mode") == "probability":
        items.append("按概率给出的 k 依赖线性模型、对称分布和 t 分布近似。")
    return items


def _report_unit(actual, expected_text, report_text):
    if expected_text:
        expected = parse_unit(expected_text)
        if not ureg.Quantity(1, actual).is_compatible_with(ureg.Quantity(1, expected)):
            raise LabError(
                f"结果单位“{unit_text(actual)}”与预期单位“{expected_text}”的量纲不同。本次没有改写公式或强行换算。",
                code="unit",
            )
    chosen = report_text or expected_text
    if not chosen:
        return actual
    report = parse_unit(chosen)
    if not ureg.Quantity(1, actual).is_compatible_with(ureg.Quantity(1, report)):
        raise LabError(
            f"不能把结果单位“{unit_text(actual)}”换算成“{chosen}”。",
            code="unit",
        )
    return report


def _same(left, right, what):
    scale = max(1.0, abs(left), abs(right))
    if not math.isfinite(left) or not math.isfinite(right) or abs(left - right) > 1e-7 * scale:
        raise LabError(f"{what}不一致，已拒绝输出。", code="unit")
