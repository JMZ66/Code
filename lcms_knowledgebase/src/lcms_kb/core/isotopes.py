"""理论同位素分布。峰位置和丰度来自 pyteomics，再叠到实测 MS1 上。

分布是理论值，图例必须写成理论分布，不能写成采集到的同位素峰。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from pyteomics import mass

from lcms_kb.core.adducts import AdductSpec, theoretical_mz
from lcms_kb.core.masscalc import FormulaError


@dataclass(frozen=True)
class IsotopePeak:
    mz: float
    relative_abundance: float  # 最强理论峰为 100
    composition: str


@dataclass(frozen=True)
class IsotopePattern:
    formula: str
    adduct: str
    peaks: tuple[IsotopePeak, ...]
    banner: str = "理论同位素分布（计算值），不是从数据文件里读出的峰。"


def _ion_composition(formula: str, adduct: AdductSpec) -> mass.Composition:
    """中性原子组成：分子式 × 倍数 − 丢失 + 电荷载体里的原子。"""
    composition = mass.Composition(formula=formula) * adduct.multiplier
    if adduct.loss_formula:
        composition -= mass.Composition(formula=adduct.loss_formula)
    carrier_atoms = _carrier_atoms(adduct.carrier)
    if carrier_atoms:
        composition += mass.Composition(formula=carrier_atoms)
    return composition


def _carrier_atoms(carrier: str) -> str:
    """``NH4+`` → ``NH4``，``Cl-`` → ``Cl``，``Fe+2`` → ``Fe``。"""
    text = carrier.strip()
    for sign in ("+", "-"):
        if sign in text:
            atoms, _, _count = text.partition(sign)
            return atoms
    return text


def theoretical_isotope_pattern(formula: str, adduct: AdductSpec, *,
                                overall_threshold: float = 1e-4,
                                max_peaks: int = 12) -> IsotopePattern:
    """按标称质量合并后的理论同位素簇，丰度归一化到 100。

    单同位素峰的 m/z 与 :func:`theoretical_mz` 对齐，其余峰用质量差平移，
    这样加合离子的理论质量和同位素间距来自同一套 NIST 质量。
    """
    try:
        composition = _ion_composition(formula, adduct)
        mono_mz = theoretical_mz(formula, adduct)
        mono_mass = float(mass.calculate_mass(composition=composition))
    except Exception as exc:
        raise FormulaError(f"无法计算 {formula} {adduct.name} 的同位素分布：{exc}") from exc

    grouped: dict[int, list[tuple[float, float, str]]] = {}
    for comp, abundance in mass.isotopologues(
        composition=composition,
        report_abundance=True,
        overall_threshold=overall_threshold,
    ):
        exact = float(mass.calculate_mass(composition=comp))
        nominal = int(round(exact))
        grouped.setdefault(nominal, []).append((exact, float(abundance), str(comp)))

    merged: list[tuple[float, float, str]] = []
    for _nominal, items in grouped.items():
        total = sum(item[1] for item in items)
        if total <= 0:
            continue
        center = sum(item[0] * item[1] for item in items) / total
        label = max(items, key=lambda item: item[1])[2]
        merged.append((center, total, label))
    if not merged:
        raise FormulaError(f"{formula} 没有可用的同位素峰")
    merged.sort(key=lambda item: item[0])
    base_mass = min(merged, key=lambda item: abs(item[0] - mono_mass))[0]
    strongest = max(item[1] for item in merged)
    peaks: list[IsotopePeak] = []
    for center, abundance, label in merged:
        mz = mono_mz + (center - base_mass) / abs(adduct.charge)
        peaks.append(IsotopePeak(
            mz=mz,
            relative_abundance=100.0 * abundance / strongest,
            composition=label,
        ))
    peaks.sort(key=lambda peak: peak.mz)
    if len(peaks) > max_peaks:
        peaks = sorted(peaks, key=lambda peak: peak.relative_abundance, reverse=True)[:max_peaks]
        peaks.sort(key=lambda peak: peak.mz)
    return IsotopePattern(formula=formula, adduct=adduct.name, peaks=tuple(peaks))


def overlay_on_spectrum(pattern: IsotopePattern, mz: np.ndarray, intensity: np.ndarray,
                        *, window_da: float = 0.02) -> list[dict]:
    """在实测峰里寻找每个理论同位素峰附近的点。找不到就观测强度为 None。"""
    rows = []
    mz_arr = np.asarray(mz, dtype=float)
    inten = np.asarray(intensity, dtype=float)
    for peak in pattern.peaks:
        observed = None
        observed_i = None
        if mz_arr.size:
            delta = np.abs(mz_arr - peak.mz)
            index = int(np.argmin(delta))
            if delta[index] <= window_da:
                observed = float(mz_arr[index])
                observed_i = float(inten[index])
        rows.append({
            "theoretical_mz": peak.mz,
            "theoretical_relative": peak.relative_abundance,
            "observed_mz": observed,
            "observed_intensity": observed_i,
            "layer": "algorithm_result",
            "banner": pattern.banner,
        })
    return rows
