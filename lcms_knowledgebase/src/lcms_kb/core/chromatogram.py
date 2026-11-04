"""TIC、BPC 和 EIC。数值只来自已经读出的峰，不补峰、不平滑。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from lcms_kb.core.masscalc import tolerance_window
from lcms_kb.core.models import Scan


@dataclass(frozen=True)
class Chromatogram:
    rt_min: np.ndarray
    intensity: np.ndarray
    kind: str  # tic | bpc | eic | blank_subtracted_eic
    polarity: str
    ms_level: int | None
    layer: str  # raw_signal | algorithm_result
    label: str
    extra_mz: np.ndarray | None = None


def _select(scans: list[Scan], *, polarity: str | None, ms_level: int | None,
           scan_modes: set[str] | None = None) -> list[Scan]:
    chosen = []
    for scan in scans:
        if polarity and scan.polarity != polarity:
            continue
        if ms_level is not None and scan.ms_level != ms_level:
            continue
        if scan_modes and scan.scan_mode not in scan_modes:
            continue
        if scan.rt_min is None:
            continue
        chosen.append(scan)
    chosen.sort(key=lambda scan: (scan.rt_min or 0.0, scan.index_in_file))
    return chosen


def tic(scans: list[Scan], *, polarity: str, ms_level: int = 1,
       scan_modes: set[str] | None = None) -> Chromatogram:
    chosen = _select(scans, polarity=polarity, ms_level=ms_level, scan_modes=scan_modes)
    rt = np.array([scan.rt_min for scan in chosen], dtype=float)
    intensity = np.array([scan.tic for scan in chosen], dtype=float)
    return Chromatogram(
        rt_min=rt,
        intensity=intensity,
        kind="tic",
        polarity=polarity,
        ms_level=ms_level,
        layer="raw_signal",
        label=f"TIC {_polarity_label(polarity)} MS{ms_level}",
    )


def bpc(scans: list[Scan], *, polarity: str, ms_level: int = 1,
       scan_modes: set[str] | None = None) -> Chromatogram:
    chosen = _select(scans, polarity=polarity, ms_level=ms_level, scan_modes=scan_modes)
    rt = np.array([scan.rt_min for scan in chosen], dtype=float)
    intensity = np.array([scan.bpc for scan in chosen], dtype=float)
    extra = np.array([np.nan if scan.bpc_mz is None else scan.bpc_mz for scan in chosen], dtype=float)
    return Chromatogram(
        rt_min=rt,
        intensity=intensity,
        kind="bpc",
        polarity=polarity,
        ms_level=ms_level,
        layer="raw_signal",
        label=f"BPC {_polarity_label(polarity)} MS{ms_level}",
        extra_mz=extra,
    )


def eic(scans: list[Scan], target_mz: float, tolerance: float, unit: str, *,
        polarity: str, ms_level: int = 1, scan_modes: set[str] | None = None) -> Chromatogram:
    """提取离子色谱。每个扫描只累加窗口内真实存在的强度。"""
    chosen = _select(scans, polarity=polarity, ms_level=ms_level, scan_modes=scan_modes)
    low, high = tolerance_window(target_mz, tolerance, unit)
    rt_values = []
    intensities = []
    for scan in chosen:
        if scan.mz.size == 0:
            total = 0.0
        else:
            mask = (scan.mz >= low) & (scan.mz <= high)
            total = float(scan.intensity[mask].sum()) if np.any(mask) else 0.0
        rt_values.append(scan.rt_min)
        intensities.append(total)
    return Chromatogram(
        rt_min=np.array(rt_values, dtype=float),
        intensity=np.array(intensities, dtype=float),
        kind="eic",
        polarity=polarity,
        ms_level=ms_level,
        layer="raw_signal",
        label=f"EIC m/z {target_mz:g} {tolerance:g} {unit} {_polarity_label(polarity)}",
    )


def subtract_trace(sample: Chromatogram, blank: Chromatogram) -> Chromatogram:
    """按保留时间对齐后做空白扣减。结果是算法结果，不是原始信号。

    两条曲线的时间点必须一致；否则拒绝，避免插值造出文件里没有的点。
    """
    if sample.polarity != blank.polarity:
        raise ValueError("空白扣减不能混合不同极性")
    if sample.rt_min.shape != blank.rt_min.shape or not np.allclose(sample.rt_min, blank.rt_min, equal_nan=True):
        raise ValueError("空白和样品的保留时间点不一致，不能直接相减")
    deducted = np.maximum(0.0, sample.intensity - blank.intensity)
    return Chromatogram(
        rt_min=sample.rt_min.copy(),
        intensity=deducted,
        kind="blank_subtracted_eic",
        polarity=sample.polarity,
        ms_level=sample.ms_level,
        layer="algorithm_result",
        label=f"空白扣减（算法结果） {sample.label}",
    )


def nearest_scan(scans: list[Scan], rt_min: float, *, polarity: str, ms_level: int = 1,
                 scan_modes: set[str] | None = None) -> Scan | None:
    """在指定极性和质谱级别中找离该保留时间最近的一张谱。"""
    chosen = _select(scans, polarity=polarity, ms_level=ms_level, scan_modes=scan_modes)
    if not chosen:
        return None
    return min(chosen, key=lambda scan: abs((scan.rt_min or 0) - rt_min))


def trace_apex(trace: Chromatogram) -> tuple[float | None, float | None]:
    """返回 (保留时间, 强度)。空曲线返回 (None, None)。"""
    if trace.intensity.size == 0:
        return None, None
    index = int(np.argmax(trace.intensity))
    return float(trace.rt_min[index]), float(trace.intensity[index])


def _polarity_label(polarity: str) -> str:
    return {"positive": "正离子", "negative": "负离子"}.get(polarity, polarity)
