from __future__ import annotations

import numpy as np


def nominal_subtract(mz, intensity, background_mz, background_i) -> tuple[np.ndarray, np.ndarray]:
    """按四舍五入后的标称质量扣除背景。负值丢弃。"""
    totals: dict[int, float] = {}
    mz = np.asarray(mz, dtype=float)
    intensity = np.asarray(intensity, dtype=float)
    background_mz = np.asarray(background_mz, dtype=float)
    background_i = np.asarray(background_i, dtype=float)
    for mass, value in zip(mz, intensity):
        if not np.isfinite(mass) or not np.isfinite(value):
            continue
        key = int(np.rint(mass))
        totals[key] = totals.get(key, 0.0) + float(value)
    for mass, value in zip(background_mz, background_i):
        if not np.isfinite(mass) or not np.isfinite(value):
            continue
        key = int(np.rint(mass))
        totals[key] = totals.get(key, 0.0) - float(value)
    kept = sorted((key, value) for key, value in totals.items() if value > 0)
    if not kept:
        return np.array([], dtype=float), np.array([], dtype=float)
    return (
        np.array([key for key, _value in kept], dtype=float),
        np.array([value for _key, value in kept], dtype=float),
    )


def average_nominal(spectra: list[tuple[np.ndarray, np.ndarray]]) -> tuple[np.ndarray, np.ndarray]:
    if not spectra:
        return np.array([], dtype=float), np.array([], dtype=float)
    totals: dict[int, float] = {}
    for mz, intensity in spectra:
        for mass, value in zip(np.asarray(mz, dtype=float), np.asarray(intensity, dtype=float)):
            if not np.isfinite(mass) or not np.isfinite(value):
                continue
            key = int(np.rint(mass))
            totals[key] = totals.get(key, 0.0) + float(value)
    scale = float(len(spectra))
    kept = sorted((key, value / scale) for key, value in totals.items() if value > 0)
    if not kept:
        return np.array([], dtype=float), np.array([], dtype=float)
    return (
        np.array([key for key, _value in kept], dtype=float),
        np.array([value for _key, value in kept], dtype=float),
    )


def spectrum_at(run, rt: float, *, background: bool) -> tuple[np.ndarray, np.ndarray, int, bool]:
    """取最接近 rt 的 MS1 谱。背景扣除使用左右两侧 TIC 较低的扫描。"""
    if run.n_scans == 0:
        return np.array([]), np.array([]), -1, False
    index = int(np.argmin(np.abs(run.rt - float(rt))))
    mz, inten = run.scan(index)
    if not background or run.n_scans < 5:
        return mz, inten, index, False
    left = range(max(0, index - 15), max(0, index - 2))
    right = range(min(run.n_scans - 1, index + 2), min(run.n_scans, index + 16))
    if not left or not right:
        return mz, inten, index, False
    left_i = min(left, key=lambda i: float(run.tic[i]))
    right_i = min(right, key=lambda i: float(run.tic[i]))
    background_mz, background_i = average_nominal([run.scan(left_i), run.scan(right_i)])
    clean_mz, clean_i = nominal_subtract(mz, inten, background_mz, background_i)
    return clean_mz, clean_i, index, True
