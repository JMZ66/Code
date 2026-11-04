from __future__ import annotations

import logging

import numpy as np
from matchms import Spectrum
from matchms.similarity import CosineGreedy

logging.getLogger("matchms").setLevel(logging.ERROR)


def to_spectrum(mz, intensity, metadata: dict | None = None) -> Spectrum | None:
    mz_arr = np.asarray(mz, dtype=float)
    int_arr = np.asarray(intensity, dtype=float)
    if mz_arr.size == 0 or int_arr.size == 0 or mz_arr.size != int_arr.size:
        return None
    mask = np.isfinite(mz_arr) & np.isfinite(int_arr) & (mz_arr > 0) & (int_arr > 0)
    mz_arr = mz_arr[mask]
    int_arr = int_arr[mask]
    if mz_arr.size == 0:
        return None
    order = np.argsort(mz_arr)
    mz_arr = mz_arr[order]
    int_arr = int_arr[order]
    # 合并完全相同的 m/z，满足 matchms 的升序且不重复要求。
    unique_mz = []
    unique_i = []
    for mass, value in zip(mz_arr, int_arr):
        if unique_mz and abs(float(mass) - unique_mz[-1]) <= 1e-8:
            unique_i[-1] += float(value)
        else:
            unique_mz.append(float(mass))
            unique_i.append(float(value))
    meta = {"compound_name": "spectrum"}
    if metadata:
        meta.update(metadata)
    return Spectrum(
        mz=np.asarray(unique_mz, dtype=float),
        intensities=np.asarray(unique_i, dtype=float),
        metadata=meta,
    )


def _filter_query(query_mz, query_i, ref_mz, tolerance: float):
    query_mz = np.asarray(query_mz, dtype=float)
    query_i = np.asarray(query_i, dtype=float)
    ref_mz = np.asarray(ref_mz, dtype=float)
    if query_mz.size == 0 or ref_mz.size == 0:
        return np.array([]), np.array([])
    kept_mz = []
    kept_i = []
    for mass, value in zip(query_mz, query_i):
        if np.any(np.abs(ref_mz - mass) <= tolerance):
            kept_mz.append(mass)
            kept_i.append(value)
    return np.asarray(kept_mz, dtype=float), np.asarray(kept_i, dtype=float)


def cosine_scores(
    query_mz,
    query_i,
    ref_mz,
    ref_i,
    *,
    tolerance: float = 0.1,
    mz_power: float = 1.0,
    intensity_power: float = 0.5,
) -> tuple[float, int, float]:
    """返回 matchms 加权余弦、匹配峰数，以及反向分数。

    正向分数就是 CosineGreedy.pair(参考谱, 查询谱)，测试直接对照 matchms。
    反向分数先去掉查询谱里参考谱没有对应峰的离子，再用同一个 CosineGreedy。
    两个分数都只是候选排序，不是鉴定。
    """
    cosine = CosineGreedy(tolerance=float(tolerance), mz_power=float(mz_power), intensity_power=float(intensity_power))
    reference = to_spectrum(ref_mz, ref_i, {"compound_name": "reference"})
    query = to_spectrum(query_mz, query_i, {"compound_name": "query"})
    if reference is None or query is None:
        return 0.0, 0, 0.0
    forward, matched = _pair(cosine, reference, query)
    filtered_mz, filtered_i = _filter_query(query.peaks.mz, query.peaks.intensities, reference.peaks.mz, tolerance)
    reverse_query = to_spectrum(filtered_mz, filtered_i, {"compound_name": "query-reverse"})
    if reverse_query is None:
        reverse = 0.0
    else:
        reverse, _matched_reverse = _pair(cosine, reference, reverse_query)
    return float(forward), int(matched), float(reverse)


def _pair(cosine: CosineGreedy, reference: Spectrum, query: Spectrum) -> tuple[float, int]:
    result = cosine.pair(reference, query)
    if isinstance(result, np.ndarray):
        result = result.item()
    return float(result[0]), int(result[1])
