"""JCGM 101:2008 Monte Carlo propagation for one output quantity.

Joint sampling is implemented only for independent inputs and for a
multivariate normal defined by the stated means and Pearson correlations.
Marginals plus a Pearson correlation are not turned into a Gaussian copula.
"""

from __future__ import annotations

import math

import numpy as np

from labuv.errors import LabError
from labuv.numbers import fmt

_MAX_SAMPLES = 2_000_000


def run_monte_carlo(expression, inputs, correlation, scales, y_scale, options, *, gum_y, gum_uc, gum_expanded) -> dict:
    seed = int(options.get("seed"))
    if seed < 0 or seed > 2**32 - 1:
        raise LabError("随机种子必须是 0 到 2^32-1 的整数。", code="monte_carlo")
    probability = float(options.get("p", 0.95))
    if not 0.0 < probability < 1.0:
        raise LabError("Monte Carlo 覆盖概率必须在 0 和 1 之间。", code="monte_carlo")
    interval = options.get("interval", "symmetric")
    if interval not in ("symmetric", "shortest"):
        raise LabError("覆盖区间只能是 probabilistically symmetric（symmetric）或 shortest。", code="monte_carlo")
    _reject_unsupported_dependence(inputs, correlation)
    adaptive = bool(options.get("adaptive"))
    rng = np.random.Generator(np.random.PCG64(seed))
    if adaptive:
        summary = _adaptive(expression, inputs, correlation, scales, y_scale, rng, probability, interval, options)
    else:
        count = int(options.get("n", 100000))
        if count < 1000 or count > _MAX_SAMPLES:
            raise LabError("非自适应 Monte Carlo 的样本数必须在 1000 和 2000000 之间。", code="monte_carlo")
        draws = _draw(rng, inputs, correlation, count)
        values = _propagate(expression, inputs, draws, scales, y_scale)
        summary = _summarize(values, probability, interval)
        summary.update({"adaptive": False, "stabilized": None, "batches": 1, "batch_size": count, "delta": None, "n": count})
    summary["seed"] = seed
    summary["p"] = probability
    summary["interval"] = "probabilistically_symmetric" if interval == "symmetric" else "shortest"
    summary["generator"] = "numpy PCG64"
    summary["gum_endpoint_low"] = None if gum_expanded is None else gum_y - gum_expanded
    summary["gum_endpoint_high"] = None if gum_expanded is None else gum_y + gum_expanded
    if gum_expanded is not None and summary.get("low") is not None:
        summary["d_low"] = abs(summary["gum_endpoint_low"] - summary["low"])
        summary["d_high"] = abs(summary["gum_endpoint_high"] - summary["high"])
    warnings = _warnings(inputs, summary, gum_y, gum_uc)
    trace = _trace(summary, gum_y, gum_uc)
    summary["warnings"] = warnings
    summary["trace"] = trace
    return summary


def coverage_interval(samples, probability: float, interval: str) -> tuple[float, float]:
    """JCGM 101:2008 clause 7.7.2, 1-based order statistics."""
    ordered = np.sort(np.asarray(samples, dtype=float))
    count = int(ordered.size)
    product = probability * count
    if abs(product - round(product)) < 1e-8:
        q = int(round(product))
    else:
        q = int(math.floor(product + 0.5))
    if q < 1 or q >= count:
        raise LabError("样本量不足以按 JCGM 101 第7.7.2节形成覆盖区间。", code="monte_carlo")
    if interval == "shortest":
        widths = ordered[q:] - ordered[: count - q]
        start = int(np.argmin(widths)) + 1
    else:
        half = (count - q) / 2.0
        if abs(half - round(half)) < 1e-8:
            start = int(round(half))
        else:
            start = int(math.floor((count - q + 1) / 2.0))
        if start < 1:
            start = 1
    if start + q > count:
        raise LabError("覆盖区间指标超出样本。", code="monte_carlo")
    return float(ordered[start - 1]), float(ordered[start + q - 1])


def numerical_tolerance(value: float, digits: int) -> float:
    """JCGM 101:2008 clause 7.9.2."""
    if digits < 1 or digits > 6:
        raise LabError("数值容差的有效十进制位数只接受 1 到 6。", code="monte_carlo")
    magnitude = abs(float(value))
    if magnitude == 0.0 or not math.isfinite(magnitude):
        raise LabError("u(y) 为 0 或非有限时，不能按 JCGM 101 第7.9.2节计算数值容差。", code="monte_carlo")
    log_value = math.log10(magnitude)
    if abs(log_value - round(log_value)) < 1e-10:
        log_value = round(log_value)
    exponent = math.floor(log_value) - (digits - 1)
    return 0.5 * (10.0 ** exponent)


def _reject_unsupported_dependence(inputs, correlation):
    off = np.max(np.abs(correlation - np.eye(len(inputs))))
    if off <= 1e-12:
        return
    kinds = {item["sample"]["kind"] for item in inputs}
    if kinds != {"normal"}:
        raise LabError(
            "存在非零相关，且至少有一个输入不是正态分布。边际分布加 Pearson 相关并不能唯一确定联合分布；"
            "本软件不使用高斯 copula 去冒充这个 Pearson 相关，因此拒绝抽样。一阶不确定度传播仍可单独计算。",
            code="dependence",
        )


def _draw(rng, inputs, correlation, count):
    specs = [item["sample"] for item in inputs]
    if np.max(np.abs(correlation - np.eye(len(specs)))) > 1e-12:
        means = np.array([spec["loc_user"] for spec in specs])
        scales = np.array([spec["scale_user"] for spec in specs])
        covariance = np.outer(scales, scales) * correlation
        return rng.multivariate_normal(means, covariance, size=count, check_valid="raise", method="eigh")
    columns = []
    for spec in specs:
        loc = spec["loc_user"]
        if spec["kind"] == "normal":
            columns.append(np.full(count, loc) if spec["scale_user"] == 0 else rng.normal(loc, spec["scale_user"], count))
        elif spec["kind"] == "uniform":
            half = spec["half_user"]
            columns.append(np.full(count, loc) if half == 0 else rng.uniform(loc - half, loc + half, count))
        elif spec["kind"] == "triangular":
            half = spec["half_user"]
            columns.append(np.full(count, loc) if half == 0 else rng.triangular(loc - half, loc, loc + half, count))
        elif spec["kind"] == "scaled_t":
            if spec["df"] <= 0:
                raise LabError("t 分布自由度无效。", code="monte_carlo")
            draw = rng.standard_t(spec["df"], count)
            columns.append(loc + spec["scale_user"] * draw)
        else:
            raise LabError("有输入分布不能抽样。", code="monte_carlo")
    return np.column_stack(columns)


def _propagate(expression, inputs, draws, scales, y_scale):
    names = [item["name"] for item in inputs]
    output = np.empty(draws.shape[0], dtype=float)
    for index in range(draws.shape[0]):
        values = {name: float(draws[index, position]) * scales[name] for position, name in enumerate(names)}
        output[index] = expression.evaluate(values) * y_scale
    if not np.all(np.isfinite(output)):
        raise LabError("Monte Carlo 出现非有限模型值，已停止，不使用剩余样本拼出一个结果。", code="monte_carlo")
    return output


def _summarize(values, probability, interval) -> dict:
    mean = float(np.mean(values))
    # JCGM 101:2008 equation (17) divides by M-1.
    standard = float(np.std(values, ddof=1))
    low, high = coverage_interval(values, probability, interval)
    return {"mean": mean, "sd": standard, "low": low, "high": high}


def _adaptive(expression, inputs, correlation, scales, y_scale, rng, probability, interval, options) -> dict:
    digits = int(options.get("ndig", 2))
    batch = max(math.ceil(100.0 / (1.0 - probability)), 10_000)
    max_batches = int(options.get("max_batches", 20))
    max_total = int(options.get("max_total", batch * max_batches))
    if max_total > _MAX_SAMPLES:
        max_total = _MAX_SAMPLES
    collected = []
    batch_rows = []
    stabilized = False
    tolerance = None
    stability = {}
    used = 0
    while used + batch <= max_total and len(batch_rows) < max_batches:
        draws = _draw(rng, inputs, correlation, batch)
        values = _propagate(expression, inputs, draws, scales, y_scale)
        collected.append(values)
        batch_rows.append(_summarize(values, probability, interval))
        used += batch
        if len(batch_rows) == 1:
            continue
        tolerance, stability, stabilized = _stability(batch_rows, np.concatenate(collected), digits)
        if stabilized:
            break
    if not collected:
        raise LabError("Monte Carlo 样本上限太小，连一批都无法运行。", code="monte_carlo")
    pooled = np.concatenate(collected)
    summary = _summarize(pooled, probability, interval)
    summary.update(
        {
            "adaptive": True,
            "stabilized": stabilized,
            "batches": len(batch_rows),
            "batch_size": batch,
            "n": int(pooled.size),
            "delta": tolerance,
            "stability": stability,
        }
    )
    return summary


def _stability(batch_rows, pooled, digits):
    def standard_error(key):
        values = [row[key] for row in batch_rows]
        count = len(values)
        mean = sum(values) / count
        return math.sqrt(sum((value - mean) ** 2 for value in values) / (count * (count - 1)))

    stability = {key: standard_error(key) for key in ("mean", "sd", "low", "high")}
    standard = float(np.std(pooled, ddof=1))
    if standard == 0.0:
        stabilized = all(value == 0.0 for value in stability.values())
        return 0.0, stability, stabilized
    tolerance = numerical_tolerance(standard, digits)
    stabilized = all(2.0 * value < tolerance for value in stability.values())
    return tolerance, stability, stabilized


def _warnings(inputs, summary, gum_y, gum_uc):
    warnings = []
    if any(item["sample"]["kind"] == "scaled_t" and item["sample"]["df"] is not None and item["sample"]["df"] < 3 for item in inputs):
        warnings.append("有 A 类自由度小于 3。JCGM 101 指出此时输出的期望或标准差可能不存在，覆盖区间仍可报告，但标准差不宜单独解读。")
    if any(item["sample"]["kind"] == "scaled_t" for item in inputs):
        warnings.append(
            "A 类 Monte Carlo 按 JCGM 101:2008 第6.4.9.5节抽样 ξ = x + s_scale·Tν。"
            "ν>2 时该分布的标准差是 GUM 标准不确定度乘以 sqrt(ν/(ν-2))，所以 MC 的标准差可以系统地不同于一阶 uc。"
        )
    if summary.get("adaptive") and summary.get("stabilized") is False:
        warnings.append("在设定的样本上限内，JCGM 101 第7.9.4节的自适应停止条件没有满足。下面的数值是已完成样本的结果，不能写成已经达到数值容差。")
    if gum_uc and summary.get("sd") is not None and abs(summary["sd"] - gum_uc) > 0.05 * max(gum_uc, 1e-18):
        warnings.append("Monte Carlo 标准差与一阶合成标准不确定度相差超过 5%。这不一定是程序错误；非线性或非正态时本应不同。")
    if abs(summary["mean"] - gum_y) > 0.05 * max(abs(gum_y), gum_uc or 0.0, 1e-18):
        warnings.append("Monte Carlo 均值与 f(x) 相差明显。JCGM 101 的估计是输出样本均值，GUM 的估计是输入估计处的函数值，二者可以不同。")
    return warnings


def _trace(summary, gum_y, gum_uc):
    lines = [
        "Monte Carlo 按 JCGM 101:2008 实施。",
        f"生成器 numpy PCG64，种子 {summary['seed']}，样本数 {summary['n']}，覆盖概率 {fmt(summary['p'])}。",
        f"覆盖区间定义：{summary['interval']}（第7.7.2节的顺序统计量，不是把样本标准差乘 k）。",
        f"MC 均值 = {fmt(summary['mean'])}，MC 标准差 = {fmt(summary['sd'])}（式(17)，除以 M-1）。",
        f"区间端点 = [{fmt(summary['low'])}, {fmt(summary['high'])}]。",
        f"对照的 GUM f(x) = {fmt(gum_y)}，uc = {fmt(gum_uc)}。",
    ]
    if summary.get("adaptive"):
        state = "已满足" if summary.get("stabilized") else "未满足"
        lines.append(
            f"自适应过程：每批 {summary['batch_size']}，批数 {summary['batches']}，数值容差 δ={fmt(summary.get('delta'))}，停止条件{state}。"
        )
    else:
        lines.append("本次使用固定样本数，没有声称完成第7.9节的自适应终止判定。")
    if summary.get("d_low") is not None:
        lines.append(f"与 GUM 端点的绝对差 d_low={fmt(summary['d_low'])}，d_high={fmt(summary['d_high'])}（第8.1.3节的比较量，本次不自动宣布 GUM 已被验证）。")
    return lines
