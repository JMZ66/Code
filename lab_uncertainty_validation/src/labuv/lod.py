"""Detection and quantification limits for explicitly selected formulae.

A factor of 3 or 10 is never inserted unless the user supplies it or presses a
preset that also writes its source. No verification experiment means the
result stays unverified.
"""

from __future__ import annotations

import math

from labuv.errors import LabError
from labuv.numbers import fmt, parse_float

PRESET_EURACHEM = {
    "k_lod": 3.0,
    "k_loq": 10.0,
    "source": (
        "Eurachem《The Fitness for Purpose of Analytical Methods》第3版（2025）"
        "Quick Reference 3 和 4 的常用倍数。指南自己说明 3s′ 对验证通常只是近似，"
        "不是通用法定标准。只有所选程序采用该倍数时才能使用。"
    ),
}
PRESET_ICH = {
    "k_lod": 3.3,
    "k_loq": 10.0,
    "source": (
        "ICH Q2(R1) 常见写法 LOD=3.3σ/S、LOQ=10σ/S。用户必须确认所引用的版本仍被所选程序采用。"
        "本软件不把 3.3 和 10 当作通用法定阈值。"
    ),
}


def lod_loq(payload: dict) -> dict:
    method = str(payload.get("method") or "")
    scope = str(payload.get("scope") or "")
    if scope not in ("instrument", "method"):
        raise LabError("必须标明这是仪器检出限还是方法检出限。试剂空白未走完整前处理时只能标成仪器检出限。", code="lod")
    if method == "blank_sd":
        result = _blank(payload)
    elif method == "calibration":
        result = _calibration(payload)
    else:
        raise LabError("检出限方法只能是 blank_sd 或 calibration。", code="lod")
    result["scope"] = "仪器检出限" if scope == "instrument" else "方法检出限"
    result["verified"] = False
    result["verification_note"] = "没有验证实验，状态为未验证。计算本身不能宣布方法合格。"
    checks = payload.get("verification_values") or []
    if checks:
        values = [parse_float(value, what="验证测定值") for value in checks]
        lod = result["lod"]
        above = sum(value > lod for value in values) if lod is not None else None
        result["verified"] = False
        result["verification_note"] = (
            f"已记录 {len(values)} 个验证测定值，其中 {above} 个大于本次 LOD。"
            "这只是计数，不是合格判定；合格准则必须另由用户录入。"
        )
        result["verification_values"] = values
    result["warnings"] = result.get("warnings") or []
    if scope == "instrument":
        result["warnings"].append("本次标为仪器检出限。它不能直接改称为方法检出限。")
    result["trace"] = result["scope"] + "。\n" + result["trace"] + "\n" + result["verification_note"]
    return result


def _blank(payload):
    values = [parse_float(value, what="空白或低浓度测定值") for value in payload.get("values") or []]
    if len(values) < 2:
        raise LabError("空白重复法至少需要 2 个测定值。", code="lod")
    k_lod = parse_float(payload.get("k_lod"), what="LOD 倍数")
    k_loq = parse_float(payload.get("k_loq"), what="LOQ 倍数")
    if k_lod <= 0 or k_loq <= 0:
        raise LabError("LOD 和 LOQ 的倍数必须为正，软件不默认填 3 和 10。", code="lod")
    source = str(payload.get("source") or "").strip()
    if not source:
        raise LabError("必须填写倍数的出处。没有出处就不计算。", code="lod")
    n_report = int(payload.get("n_averaged", 1))
    n_blank = int(payload.get("n_blank", 1))
    if n_report < 1 or n_blank < 1:
        raise LabError("报告均值的重复次数和空白均值的个数都必须至少为 1。", code="lod")
    corrected = bool(payload.get("blank_corrected"))
    count = len(values)
    mean = sum(values) / count
    variance = sum((value - mean) ** 2 for value in values) / (count - 1)
    s0 = math.sqrt(variance)
    if corrected:
        factor = math.sqrt(1.0 / n_report + 1.0 / n_blank)
        formula = "s′ = s0·sqrt(1/n + 1/nb)，对应 Eurachem 2025 第5.3.2节在重复性条件下做空白校正的情形"
    else:
        factor = math.sqrt(1.0 / n_report)
        formula = "不做空白校正时 s′ = s0/sqrt(n)"
    s_prime = s0 * factor
    include_mean = bool(payload.get("add_blank_mean"))
    if include_mean:
        lod = mean + k_lod * s_prime
        loq = mean + k_loq * s_prime
        expression = "LOD = 空白均值 + k_LOD·s′，LOQ = 空白均值 + k_LOQ·s′。这不是 Eurachem Quick Reference 的默认 3s′ 写法。"
    else:
        lod = k_lod * s_prime
        loq = k_loq * s_prime
        expression = "LOD = k_LOD·s′，LOQ = k_LOQ·s′。空白均值不加入，除非用户明确改选加均值的公式。"
    unit = str(payload.get("unit") or "").strip()
    if not unit:
        raise LabError("必须填写结果单位。", code="lod")
    trace = (
        f"空白重复法。m={count}，均值={fmt(mean)}，s0={fmt(s0)}，自由度 {count - 1}。\n"
        f"{formula}。n={n_report}，nb={n_blank}，s′={fmt(s_prime)} {unit}。\n"
        f"{expression}\n"
        f"k_LOD={fmt(k_lod)}，k_LOQ={fmt(k_loq)}。出处：{source}\n"
        f"LOD={fmt(lod)} {unit}，LOQ={fmt(loq)} {unit}。"
    )
    return {
        "method": "blank_sd",
        "n": count,
        "df": count - 1,
        "mean_blank": mean,
        "s0": s0,
        "s_prime": s_prime,
        "lod": lod,
        "loq": loq,
        "unit": unit,
        "source": source,
        "trace": trace,
        "warnings": [],
    }


def _calibration(payload):
    k_lod = parse_float(payload.get("k_lod"), what="LOD 倍数")
    k_loq = parse_float(payload.get("k_loq"), what="LOQ 倍数")
    if k_lod <= 0 or k_loq <= 0:
        raise LabError("校准法的倍数必须为正。", code="lod")
    source = str(payload.get("source") or "").strip()
    if not source:
        raise LabError("必须填写校准法倍数的出处。", code="lod")
    slope = parse_float(payload.get("slope"), what="斜率")
    if slope == 0.0:
        raise LabError("斜率为 0，不能把信号标准差除以斜率。", code="division_by_zero")
    residual = parse_float(payload.get("residual_sd"), what="响应残差标准差")
    if residual < 0:
        raise LabError("残差标准差不能为负。", code="lod")
    if str(payload.get("residual_domain") or "") != "signal":
        raise LabError(
            "校准法只接受信号域（响应）的残差标准差或空白响应标准差。浓度域的标准差不能再除以斜率。",
            code="lod",
        )
    lod = k_lod * residual / abs(slope)
    loq = k_loq * residual / abs(slope)
    unit = str(payload.get("unit") or "").strip()
    if not unit:
        raise LabError("必须填写校准浓度单位。", code="lod")
    n = payload.get("n")
    df = payload.get("df")
    trace = (
        "条件校准法：LOD = k_LOD·s_signal / |斜率|，LOQ = k_LOQ·s_signal / |斜率|。\n"
        f"s_signal={fmt(residual)}，斜率={fmt(slope)}，k_LOD={fmt(k_lod)}，k_LOQ={fmt(k_loq)}。\n"
        f"n={n if n not in (None, '') else '未提供'}，自由度={df if df not in (None, '') else '未提供'}。\n"
        f"出处：{source}\n"
        f"LOD={fmt(lod)} {unit}，LOQ={fmt(loq)} {unit}。斜率使用绝对值，符号单独由校准结果保留。"
    )
    return {
        "method": "calibration",
        "n": None if n in (None, "") else int(n),
        "df": None if df in (None, "") else parse_float(df, what="自由度"),
        "residual_sd": residual,
        "slope": slope,
        "lod": lod,
        "loq": loq,
        "unit": unit,
        "source": source,
        "trace": trace,
        "warnings": ["校准法 LOD 依赖所选 σ 的含义和斜率单位。它不是 3σ/10σ 的空白浓度公式。"],
    }
