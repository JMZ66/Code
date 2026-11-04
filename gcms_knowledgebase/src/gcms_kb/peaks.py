from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks, savgol_filter


@dataclass(frozen=True)
class Peak:
    rt: float
    rt_start: float
    rt_end: float
    height: float
    area: float
    apex_index: int
    start_index: int
    end_index: int
    baseline_start: float
    baseline_end: float


def _bounds(y: np.ndarray, apex: int, floor: float) -> tuple[int, int]:
    left = apex
    while left > 0 and y[left - 1] <= y[left] and y[left] > floor:
        left -= 1
    right = apex
    last = len(y) - 1
    while right < last and y[right + 1] <= y[right] and y[right] > floor:
        right += 1
    return left, right


def detect_peaks(
    rt: np.ndarray,
    intensity: np.ndarray,
    *,
    snr: float = 5.0,
    min_height: float = 0.0,
    smooth_window: int = 9,
    smooth_poly: int = 2,
    min_width_points: int = 3,
) -> list[Peak]:
    """在一条色谱上找峰并积分。

    平滑和找峰使用 scipy（Savitzky-Golay 与 find_peaks）。
    面积是边界之间扣除线性基线后的梯形积分，单位为强度 × 保留时间单位。
    """
    rt = np.asarray(rt, dtype=float)
    y = np.asarray(intensity, dtype=float)
    if rt.size != y.size:
        raise ValueError("保留时间与强度长度不一致")
    if y.size < 3 or not np.any(np.isfinite(y)):
        return []
    y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
    y_s = y
    window = int(smooth_window)
    if y.size >= window >= 5 and window % 2 == 1 and window > smooth_poly:
        y_s = savgol_filter(y, window, int(smooth_poly), mode="interp")
    residual = y - y_s
    mad = float(np.median(np.abs(residual - np.median(residual))))
    noise = 1.4826 * mad
    ymax = float(np.max(y_s))
    if noise > 1e-12:
        height = max(float(min_height), float(snr) * noise)
    else:
        height = max(float(min_height), 0.01 * ymax if ymax > 0 else 0.0)
    if ymax <= 0 or height < 0:
        return []
    indices, _props = find_peaks(y_s, height=height, distance=max(1, int(min_width_points)))
    peaks: list[Peak] = []
    for apex0 in indices:
        apex0 = int(apex0)
        floor = max(height * 0.2, float(y_s[apex0]) * 0.005)
        left, right = _bounds(y_s, apex0, floor)
        if right - left + 1 < min_width_points:
            continue
        rt_seg = rt[left : right + 1]
        y_seg = y[left : right + 1]
        if rt_seg.size < 2 or float(rt_seg[-1]) <= float(rt_seg[0]):
            continue
        baseline = np.linspace(float(y_seg[0]), float(y_seg[-1]), y_seg.size)
        corrected = np.clip(y_seg - baseline, 0, None)
        area = float(np.trapezoid(corrected, rt_seg))
        local = int(np.argmax(corrected))
        apex = left + local
        peaks.append(
            Peak(
                rt=float(rt[apex]),
                rt_start=float(rt[left]),
                rt_end=float(rt[right]),
                height=float(corrected[local]),
                area=area,
                apex_index=apex,
                start_index=left,
                end_index=right,
                baseline_start=float(y_seg[0]),
                baseline_end=float(y_seg[-1]),
            )
        )
    return peaks
