"""空白、QC 和重复样品的数值比较。输出一律是算法结果，不是鉴定。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from lcms_kb.core.chromatogram import Chromatogram, trace_apex


@dataclass(frozen=True)
class BlankFlag:
    sample_apex_rt: float | None
    sample_apex_intensity: float | None
    blank_apex_rt: float | None
    blank_apex_intensity: float | None
    ratio_blank_over_sample: float | None
    flagged: bool
    threshold: float
    layer: str = "algorithm_result"
    label: str = "空白比对（算法结果，不是鉴定）"


def blank_flag(sample: Chromatogram, blank: Chromatogram, *, ratio_threshold: float = 0.3) -> BlankFlag:
    """空白峰强度 / 样品峰强度 ≥ 阈值时标记为疑似空白污染。

    使用各自 EIC 的最高点。极性必须相同。
    """
    if sample.polarity != blank.polarity:
        raise ValueError("空白比对不能混合不同极性")
    s_rt, s_i = trace_apex(sample)
    b_rt, b_i = _intensity_at(blank, s_rt)
    ratio = None
    flagged = False
    if s_i is not None and s_i > 0 and b_i is not None:
        ratio = b_i / s_i
        flagged = ratio >= ratio_threshold
    elif (s_i is None or s_i <= 0) and b_i is not None and b_i > 0:
        ratio = None
        flagged = True
    label = "疑似空白污染" if flagged else "未超过空白阈值"
    return BlankFlag(
        sample_apex_rt=s_rt,
        sample_apex_intensity=s_i,
        blank_apex_rt=b_rt,
        blank_apex_intensity=b_i,
        ratio_blank_over_sample=ratio,
        flagged=flagged,
        threshold=ratio_threshold,
        label=f"{label}（算法结果，不是鉴定）",
    )


@dataclass(frozen=True)
class DriftReport:
    name: str
    n: int
    rt_min: tuple[float, ...]
    intensity: tuple[float, ...]
    rt_span: float | None
    intensity_rsd: float | None
    rt_flag: bool
    rsd_flag: bool
    rt_limit: float
    rsd_limit: float
    layer: str = "algorithm_result"
    label: str = "漂移/重复性（算法结果，不是鉴定）"


def _intensity_at(trace: Chromatogram, rt_min: float | None) -> tuple[float | None, float | None]:
    """取与给定保留时间最近的点。时间对不上时不插值。"""
    if rt_min is None or trace.rt_min.size == 0:
        return None, None
    index = int(np.argmin(np.abs(trace.rt_min - rt_min)))
    return float(trace.rt_min[index]), float(trace.intensity[index])


def _rsd(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    arr = np.asarray(values, dtype=float)
    mean = float(arr.mean())
    if mean == 0:
        return None
    return float(arr.std(ddof=1) / mean)


def drift_report(points: list[tuple[float, float]], *, name: str,
                 rt_limit: float = 0.1, rsd_limit: float = 0.2) -> DriftReport:
    """``points`` 是按进样顺序排列的 (保留时间, 强度)。"""
    rts = [item[0] for item in points]
    intensities = [item[1] for item in points]
    span = (max(rts) - min(rts)) if rts else None
    rsd = _rsd(intensities)
    return DriftReport(
        name=name,
        n=len(points),
        rt_min=tuple(rts),
        intensity=tuple(intensities),
        rt_span=span,
        intensity_rsd=rsd,
        rt_flag=span is not None and span > rt_limit,
        rsd_flag=rsd is not None and rsd > rsd_limit,
        rt_limit=rt_limit,
        rsd_limit=rsd_limit,
    )


def pearson(left: np.ndarray, right: np.ndarray) -> float | None:
    """两条等长曲线的皮尔逊相关。常数曲线无法计算时返回 None。"""
    a = np.asarray(left, dtype=float)
    b = np.asarray(right, dtype=float)
    if a.shape != b.shape or a.size < 2:
        return None
    if float(a.std()) == 0 or float(b.std()) == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])
