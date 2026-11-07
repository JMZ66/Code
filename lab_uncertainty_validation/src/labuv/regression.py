"""Ordinary and weighted least squares for a straight line.

Absolute inverse-variance weights are not rescaled. Proportional weights
(1/x, 1/x^2 or a user weight column) estimate one residual scale. R^2 is
reported and is never used as a pass/fail rule.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

from labuv.errors import LabError
from labuv.numbers import fmt, parse_float

MODEL_ID = "straight-line-wls-1"


def fit_line(payload: dict) -> dict:
    rows = payload.get("rows") or []
    if len(rows) < 2:
        raise LabError("直线拟合至少需要 2 个点。没有点会被自动删除。", code="regression")
    x_values = []
    y_values = []
    sigmas = []
    custom_weights = []
    for index, row in enumerate(rows, start=1):
        row_number = int(row.get("_row") or index)
        x_values.append(parse_float(row.get("x"), row=row_number, column="x"))
        y_values.append(parse_float(row.get("y"), row=row_number, column="y"))
        sigmas.append(None if row.get("sigma") in (None, "") else parse_float(row.get("sigma"), row=row_number, column="sigma"))
        custom_weights.append(None if row.get("weight") in (None, "") else parse_float(row.get("weight"), row=row_number, column="weight"))
    x = np.asarray(x_values, dtype=float)
    y = np.asarray(y_values, dtype=float)
    mode = str(payload.get("weight_mode") or "ols")
    weights, weight_note, absolute = _weights(mode, x, sigmas, custom_weights)
    design = _normal_equations(x, y, weights)
    n = len(x)
    residual = y - (design["intercept"] + design["slope"] * x)
    weighted_ss = float(np.sum(weights * residual ** 2))
    df = n - 2
    if df <= 0:
        scale = None
        warnings = ["点数减去 2 后自由度不是正数，不能估计残差标准差，也不给出参数标准不确定度。"]
    elif absolute:
        scale = 1.0
        warnings = [
            "权重是已知方差的倒数。参数协方差没有再乘残差尺度。"
            f"加权残差平方和 = {fmt(weighted_ss)}，自由度 {df}。若模型与方差都合适，这个和大致应接近自由度；软件不据此自动重标定。"
        ]
    else:
        scale = weighted_ss / df
        warnings = [
            "权重是相对权重。每个点的方差写成 σ^2/w_i，σ^2 由加权残差估计。"
            "这与“权重已经是绝对方差倒数”不是同一种计算。"
        ]
    covariance = None if scale is None else {
        "intercept": scale * design["var_intercept"],
        "slope": scale * design["var_slope"],
        "covariance": scale * design["cov_intercept_slope"],
    }
    r_squared = _r_squared(y, residual, weights)
    lack = _lack_of_fit(x, y, residual) if mode == "ols" else {
        "applicable": False,
        "reason": "失拟检验只对普通最小二乘实现。加权拟合不套用这个同方差公式。",
    }
    hetero = _heteroscedasticity(x, residual)
    trace = [
        f"模型 y = a + b x，权重模式 {mode}。点数 n={n}，未删除任何行。",
        weight_note,
        f"截距 a = {fmt(design['intercept'])}，斜率 b = {fmt(design['slope'])}。",
        f"R² = {fmt(r_squared)}。R² 只作描述，不作为线性是否可接受的判据。",
    ]
    if covariance:
        trace.append(
            f"u(a) = {fmt(math.sqrt(covariance['intercept']))}，u(b) = {fmt(math.sqrt(covariance['slope']))}，"
            f"cov(a,b) = {fmt(covariance['covariance'])}，自由度 {df}。"
        )
    trace.append(lack["trace"] if "trace" in lack else lack["reason"])
    trace.append(hetero["trace"])
    inverse = None
    if payload.get("inverse"):
        inverse = _inverse(payload["inverse"], design, covariance, df, x, y, weights, mode, scale, absolute)
        trace.extend(inverse["trace"])
        warnings.extend(inverse["warnings"])
    return {
        "model_id": MODEL_ID,
        "n": n,
        "df": df,
        "intercept": design["intercept"],
        "slope": design["slope"],
        "r_squared": r_squared,
        "residuals": residual.tolist(),
        "x": x.tolist(),
        "y": y.tolist(),
        "weights": weights.tolist(),
        "covariance": covariance,
        "residual_scale": None if scale is None else scale,
        "absolute_variance_weights": absolute,
        "lack_of_fit": lack,
        "heteroscedasticity": hetero,
        "inverse": inverse,
        "warnings": warnings,
        "trace": "\n".join(trace),
        "assumptions": [
            "直线模型。高阶曲线没有被拟合。",
            "参数标准不确定度来自加权正态方程，不是只看 R²。",
            "反算只在条件允许时给出一阶标准不确定度，不给出 Fieller 置信区间。",
        ],
    }


def _weights(mode, x, sigmas, custom):
    n = len(x)
    if mode == "ols":
        return np.ones(n), "普通最小二乘，权重都是 1，并估计共同残差方差。", False
    if mode == "wls_absolute":
        if any(value is None for value in sigmas):
            raise LabError("绝对方差加权要求每一行都有 sigma，缺失行不会被跳过。", code="weights")
        if any(value <= 0 for value in sigmas):
            raise LabError("sigma 必须为正，权重才是方差倒数。", code="weights")
        weights = 1.0 / np.square(sigmas)
        return weights, "权重 w=1/σ²，σ 为用户给出的每个点的标准差。协方差不乘残差尺度。", True
    if mode in ("wls_inv_x", "wls_inv_x2"):
        for index, value in enumerate(x, start=1):
            if value == 0.0:
                raise LabError("x=0 时不能使用 1/x 或 1/x² 权重。该行保留，拟合没有进行。", row=index, column="x", code="weights")
        weights = 1.0 / x if mode == "wls_inv_x" else 1.0 / np.square(x)
        note = "用户选择相对权重 1/x。" if mode == "wls_inv_x" else "用户选择相对权重 1/x²。"
        return weights, note + "这些权重不是绝对方差，残差尺度会另行估计。选择它们需要用户自己的依据。", False
    if mode == "wls_custom":
        if any(value is None for value in custom):
            raise LabError("自定义权重缺少数值。", code="weights")
        if any(value <= 0 for value in custom):
            raise LabError("自定义相对权重必须为正。", code="weights")
        return np.asarray(custom, dtype=float), "用户给出相对权重，残差尺度另行估计。", False
    raise LabError("未知的权重模式。", code="weights")


def _normal_equations(x, y, w):
    sw = float(np.sum(w))
    sx = float(np.sum(w * x))
    sy = float(np.sum(w * y))
    sxx = float(np.sum(w * x * x))
    sxy = float(np.sum(w * x * y))
    delta = sw * sxx - sx * sx
    if delta <= 0.0 or not math.isfinite(delta):
        raise LabError("加权后的 x 没有有效散布，不能拟合直线。", code="regression")
    slope = (sw * sxy - sx * sy) / delta
    intercept = (sxx * sy - sx * sxy) / delta
    return {
        "intercept": intercept,
        "slope": slope,
        "var_intercept": sxx / delta,
        "var_slope": sw / delta,
        "cov_intercept_slope": -sx / delta,
        "delta": delta,
        "sw": sw,
        "sx": sx,
        "sxx": sxx,
    }


def _r_squared(y, residual, w):
    weighted_mean = float(np.sum(w * y) / np.sum(w))
    total = float(np.sum(w * (y - weighted_mean) ** 2))
    if total == 0.0:
        return 1.0 if float(np.sum(w * residual ** 2)) == 0.0 else 0.0
    return 1.0 - float(np.sum(w * residual ** 2)) / total


def _lack_of_fit(x, y, residual):
    groups = {}
    for value_x, value_y in zip(x, y):
        groups.setdefault(float(value_x), []).append(float(value_y))
    pure_df = sum(len(values) - 1 for values in groups.values() if len(values) > 1)
    residual_df = len(x) - 2
    lack_df = residual_df - pure_df
    if pure_df <= 0 or lack_df <= 0:
        return {"applicable": False, "reason": "没有足够的重复校准点或剩余自由度，不做失拟检验。", "trace": "失拟检验不适用。"}
    pure_ss = 0.0
    for values in groups.values():
        if len(values) < 2:
            continue
        mean = sum(values) / len(values)
        pure_ss += sum((value - mean) ** 2 for value in values)
    residual_ss = float(np.sum(residual ** 2))
    lack_ss = residual_ss - pure_ss
    if lack_ss < 0.0 and lack_ss > -1e-10:
        lack_ss = 0.0
    if pure_ss == 0.0:
        return {
            "applicable": False,
            "reason": "纯误差平方和为 0，F 值无定义。不能据此宣布有失拟或无失拟。",
            "pure_ss": pure_ss,
            "lack_ss": lack_ss,
            "trace": "纯误差为 0，失拟 F 检验无定义。",
        }
    f_value = (lack_ss / lack_df) / (pure_ss / pure_df)
    p_value = float(stats.f.sf(f_value, lack_df, pure_df))
    trace = (
        f"重复点失拟：SS_lof={fmt(lack_ss)}（自由度 {lack_df}），SS_pe={fmt(pure_ss)}（自由度 {pure_df}），"
        f"F={fmt(f_value)}，p={fmt(p_value)}。这是统计诊断，不是自动合格结论。"
    )
    return {
        "applicable": True,
        "f": f_value,
        "p": p_value,
        "df_lof": lack_df,
        "df_pe": pure_df,
        "trace": trace,
    }


def _heteroscedasticity(x, residual):
    if len(x) < 4 or float(np.sum(residual ** 2)) == 0.0:
        return {"applicable": False, "trace": "残差为 0 或点数不足，不做 Breusch–Pagan 诊断。"}
    squared = residual ** 2
    design = np.column_stack([np.ones(len(x)), x])
    beta = np.linalg.lstsq(design, squared, rcond=None)[0]
    fitted = design @ beta
    total = float(np.sum((squared - squared.mean()) ** 2))
    if total == 0.0:
        return {"applicable": False, "trace": "残差平方没有变化，异方差诊断不适用。"}
    r2 = 1.0 - float(np.sum((squared - fitted) ** 2)) / total
    statistic = len(x) * max(0.0, r2)
    p_value = float(stats.chi2.sf(statistic, 1))
    return {
        "applicable": True,
        "statistic": statistic,
        "p": p_value,
        "trace": (
            f"Koenker 学生化 Breusch–Pagan 诊断：LM={fmt(statistic)}，自由度 1，p={fmt(p_value)}。"
            "这只提示残差平方是否随 x 变化，不是线性合格判定。"
        ),
    }


def _inverse(options, design, covariance, df, x, y, weights, mode, scale, absolute):
    y0 = parse_float(options.get("y"), what="待反算响应")
    slope = design["slope"]
    intercept = design["intercept"]
    warnings = []
    if slope == 0.0:
        raise LabError("斜率为 0，不能反算浓度。", code="inverse")
    estimate = (y0 - intercept) / slope
    trace = [f"反算点估计 x = (y - a) / b = {fmt(estimate)}。"]
    if covariance is None:
        warnings.append("没有残差自由度，不给出反算标准不确定度。")
        return {"x": estimate, "u": None, "trace": trace, "warnings": warnings}
    u_slope = math.sqrt(covariance["slope"])
    if u_slope > 0.0 and abs(slope) < 3.0 * u_slope:
        warnings.append("斜率小于其标准不确定度的 3 倍，一阶反算标准不确定度不可靠，本次不给出。")
        trace.append("已拒绝反算标准不确定度，也没有编造置信区间。")
        return {"x": estimate, "u": None, "trace": trace, "warnings": warnings}
    variance_y = _new_response_variance(options, estimate, mode, scale, absolute, x)
    da = -1.0 / slope
    db = -(y0 - intercept) / (slope ** 2)
    dy = 1.0 / slope
    variance = (
        da ** 2 * covariance["intercept"]
        + db ** 2 * covariance["slope"]
        + 2.0 * da * db * covariance["covariance"]
        + dy ** 2 * variance_y
    )
    if variance < 0.0 and variance > -1e-18:
        variance = 0.0
    if variance < 0.0:
        raise LabError("反算方差为负，已拒绝。", code="inverse")
    standard = math.sqrt(variance)
    trace.append(
        f"反算标准不确定度按一阶传播为 {fmt(standard)}（含截距、斜率的协方差以及新响应的方差）。"
        "这不是 Fieller 区间，也没有把它乘覆盖因子后称作置信区间。"
    )
    if df is not None and df <= 0:
        warnings.append("自由度不足，标准不确定度的分布假设没有建立。")
    return {"x": estimate, "u": standard, "variance_y": variance_y, "trace": trace, "warnings": warnings, "df": df}


def _new_response_variance(options, estimate, mode, scale, absolute, x):
    if options.get("u_y") not in (None, ""):
        u_y = parse_float(options.get("u_y"), what="新响应标准不确定度")
        if u_y < 0:
            raise LabError("新响应的标准不确定度不能为负。", code="inverse")
        return u_y ** 2
    replicates = options.get("replicates", 1)
    replicates = int(replicates)
    if replicates < 1:
        raise LabError("新响应的重复次数必须至少为 1。", code="inverse")
    if absolute:
        raise LabError(
            "绝对方差加权时，新响应的方差不会从校准残差里编造。请填写该响应自己的标准不确定度。",
            code="inverse",
        )
    if scale is None:
        raise LabError("没有残差尺度，不能估计新响应的方差。", code="inverse")
    if mode == "ols":
        return scale / replicates
    if mode == "wls_inv_x":
        if estimate == 0.0:
            raise LabError("反算得到 x=0，1/x 权重无法用于新响应。", code="inverse")
        return scale / (replicates * (1.0 / estimate))
    if mode == "wls_inv_x2":
        if estimate == 0.0:
            raise LabError("反算得到 x=0，1/x² 权重无法用于新响应。", code="inverse")
        return scale / (replicates * (1.0 / estimate ** 2))
    raise LabError("这种相对权重没有自动的新响应方差模型。请直接填写新响应的标准不确定度。", code="inverse")
