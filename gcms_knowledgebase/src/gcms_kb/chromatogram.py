from __future__ import annotations

import numpy as np


def tic_bpc(intensities: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """由每次扫描的强度数组计算 TIC 与 BPC。

    TIC 是该扫描全部强度之和。BPC 是该扫描的最大强度。空扫描两者都为 0。
    """
    tic = np.empty(len(intensities), dtype=float)
    bpc = np.empty(len(intensities), dtype=float)
    for i, values in enumerate(intensities):
        arr = np.asarray(values, dtype=float)
        if arr.size == 0:
            tic[i] = 0.0
            bpc[i] = 0.0
        else:
            finite = arr[np.isfinite(arr)]
            tic[i] = float(finite.sum()) if finite.size else 0.0
            bpc[i] = float(finite.max()) if finite.size else 0.0
    return tic, bpc


def eic(mz_list: list[np.ndarray], intensity_list: list[np.ndarray], target: float, tolerance: float) -> np.ndarray:
    """提取离子色谱。容差是绝对 m/z，强度在窗口内求和。"""
    if tolerance < 0:
        raise ValueError("m/z 容差不能为负")
    out = np.empty(len(mz_list), dtype=float)
    for i, (mz, inten) in enumerate(zip(mz_list, intensity_list)):
        mz_arr = np.asarray(mz, dtype=float)
        in_arr = np.asarray(inten, dtype=float)
        if mz_arr.size == 0:
            out[i] = 0.0
            continue
        mask = np.isfinite(mz_arr) & np.isfinite(in_arr) & (np.abs(mz_arr - target) <= tolerance)
        out[i] = float(in_arr[mask].sum()) if np.any(mask) else 0.0
    return out


def eic_from_flat(
    mz: np.ndarray,
    intensity: np.ndarray,
    offsets: np.ndarray,
    target: float,
    tolerance: float,
) -> np.ndarray:
    n = len(offsets) - 1
    out = np.empty(n, dtype=float)
    for i in range(n):
        a = int(offsets[i])
        b = int(offsets[i + 1])
        if b <= a:
            out[i] = 0.0
            continue
        mz_i = mz[a:b]
        in_i = intensity[a:b]
        mask = np.abs(mz_i - target) <= tolerance
        out[i] = float(in_i[mask].sum()) if np.any(mask) else 0.0
    return out
