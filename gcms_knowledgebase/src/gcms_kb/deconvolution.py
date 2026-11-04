from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import nnls

from gcms_kb.peaks import detect_peaks


@dataclass(frozen=True)
class ComponentResult:
    rt: float
    rt_start: float
    rt_end: float
    height: float
    area: float
    mz: np.ndarray
    intensity: np.ndarray


def deconvolve(
    rt: np.ndarray,
    scans_mz: list[np.ndarray],
    scans_i: list[np.ndarray],
    *,
    apex_tol: float = 0.05,
    mz_bin: float = 1.0,
    min_relative_height: float = 0.02,
    max_channels: int = 4000,
) -> tuple[list[ComponentResult], str]:
    """共流出组分的 ADAP 风格解卷积。

    1. 按标称质量（或给定 bin）抽出离子色谱。
    2. 用与色谱峰相同的 scipy 找峰。
    3. 按峰顶保留时间聚类。强峰先成为组分中心，时间差不超过 apex_tol 的离子并入。
    4. 每个组分的模型形状优先来自只属于该组分的离子。
    5. 对每个质量通道用 scipy.optimize.nnls 把重叠强度分到各组分。

    这不是 MS-DIAL，也不是 AMDIS。输出是算法层的纯化谱，没有化合物名称。
    """
    rt = np.asarray(rt, dtype=float)
    n = len(rt)
    if n == 0 or len(scans_mz) != n or len(scans_i) != n:
        raise ValueError("扫描数量不一致")
    if mz_bin <= 0:
        raise ValueError("质量 bin 必须为正")
    note = ""
    channels: dict[float, np.ndarray] = {}
    for index in range(n):
        mz = np.asarray(scans_mz[index], dtype=float)
        inten = np.asarray(scans_i[index], dtype=float)
        if mz.size == 0:
            continue
        keys = np.rint(mz / mz_bin) * mz_bin
        uniq, inverse = np.unique(np.round(keys, 6), return_inverse=True)
        summed = np.zeros(len(uniq), dtype=float)
        np.add.at(summed, inverse, np.clip(inten, 0, None))
        for key, value in zip(uniq, summed):
            column = channels.get(float(key))
            if column is None:
                column = np.zeros(n, dtype=float)
                channels[float(key)] = column
            column[index] += float(value)
    if not channels:
        return [], "没有可用于解卷积的离子。"
    if len(channels) > max_channels:
        ranked = sorted(channels.items(), key=lambda item: float(np.max(item[1])), reverse=True)
        channels = dict(ranked[:max_channels])
        note = f"离子通道过多，仅保留强度最高的 {max_channels} 个质量通道。"

    @dataclass
    class Member:
        mz: float
        rt: float
        height: float
        profile: np.ndarray

    members: list[Member] = []
    for mass, column in channels.items():
        found = detect_peaks(rt, column, snr=3.0, min_height=0.0, min_width_points=3)
        for peak in found:
            if peak.height <= 0:
                continue
            profile = np.zeros(n, dtype=float)
            segment = column[peak.start_index : peak.end_index + 1].astype(float)
            baseline = np.linspace(segment[0], segment[-1], segment.size)
            corrected = np.clip(segment - baseline, 0, None)
            profile[peak.start_index : peak.end_index + 1] = corrected
            members.append(Member(mz=mass, rt=peak.rt, height=peak.height, profile=profile))
    if not members:
        return [], note or "离子色谱上没有检测到峰。"

    @dataclass
    class Cluster:
        rt: float
        members: list[Member]

    clusters: list[Cluster] = []
    for member in sorted(members, key=lambda item: item.height, reverse=True):
        placed = False
        for cluster in clusters:
            if abs(member.rt - cluster.rt) <= apex_tol:
                cluster.members.append(member)
                placed = True
                break
        if not placed:
            clusters.append(Cluster(rt=member.rt, members=[member]))
    clusters.sort(key=lambda cluster: cluster.rt)

    shapes = []
    for cluster in clusters:
        counts: dict[float, int] = {}
        for other in clusters:
            for member in other.members:
                counts[member.mz] = counts.get(member.mz, 0) + 1
        pure = [member for member in cluster.members if counts.get(member.mz, 0) == 1]
        donors = pure or [max(cluster.members, key=lambda item: item.height)]
        accum = np.zeros(n, dtype=float)
        used = 0
        for member in donors:
            peak = float(np.max(member.profile))
            if peak <= 0:
                continue
            accum += member.profile / peak
            used += 1
        if used == 0:
            continue
        shape = accum / used
        peak = float(np.max(shape))
        if peak <= 0:
            continue
        shapes.append(shape / peak)
    if not shapes:
        return [], note or "未能建立组分模型。"
    design = np.column_stack(shapes)
    spectra: list[dict[float, float]] = [dict() for _ in shapes]
    global_max = max(float(np.max(column)) for column in channels.values())
    floor = max(1e-6, min_relative_height * global_max * 0.05)
    for mass, column in channels.items():
        if float(np.max(column)) < floor:
            continue
        coeff, _residual = nnls(design, column)
        for index, value in enumerate(coeff):
            if value > 0:
                spectra[index][float(mass)] = float(value)

    results: list[ComponentResult] = []
    for shape, spectrum in zip(shapes, spectra):
        if not spectrum:
            continue
        masses = np.array(sorted(spectrum), dtype=float)
        values = np.array([spectrum[mass] for mass in masses], dtype=float)
        keep = values >= max(float(np.max(values)) * 0.01, floor)
        masses = masses[keep]
        values = values[keep]
        if masses.size == 0:
            continue
        order = np.argsort(masses)
        masses = masses[order]
        values = values[order]
        apex = int(np.argmax(shape))
        support = np.flatnonzero(shape > 0.02 * float(shape[apex]))
        start = int(support[0]) if support.size else apex
        end = int(support[-1]) if support.size else apex
        height = float(values.sum())
        area = float(np.trapezoid(shape, rt) * height)
        results.append(
            ComponentResult(
                rt=float(rt[apex]),
                rt_start=float(rt[start]),
                rt_end=float(rt[end]),
                height=height,
                area=area,
                mz=masses,
                intensity=values,
            )
        )
    results.sort(key=lambda item: item.rt)
    return results, note
