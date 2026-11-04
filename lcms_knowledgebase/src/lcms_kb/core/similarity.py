"""MS/MS 相似度。使用 matchms 的 ModifiedCosineGreedy，不自行实现打分。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from matchms import Spectrum
from matchms.similarity import ModifiedCosineGreedy

from lcms_kb.errors import EnergyMismatch, PolarityMismatch


@dataclass(frozen=True)
class SimilarityResult:
    score: float
    matches: int
    tolerance_da: float
    allow_polarity_mismatch: bool
    allow_energy_mismatch: bool
    banner: str = "谱图相似度是算法结果，不是化合物鉴定。"


def _spectrum(mz, intensity, precursor_mz: float) -> Spectrum:
    mz_arr = np.asarray(mz, dtype=float)
    inten = np.asarray(intensity, dtype=float)
    order = np.argsort(mz_arr)
    return Spectrum(
        mz=mz_arr[order],
        intensities=inten[order],
        metadata={"precursor_mz": float(precursor_mz)},
    )


def modified_cosine(mz_a, intensity_a, precursor_a: float,
                    mz_b, intensity_b, precursor_b: float, *,
                    tolerance_da: float = 0.05,
                    polarity_a: str | None = None,
                    polarity_b: str | None = None,
                    energy_a: float | None = None,
                    energy_b: float | None = None,
                    allow_polarity_mismatch: bool = False,
                    allow_energy_mismatch: bool = False) -> SimilarityResult:
    """比较两条已经采集到的 MS/MS。

    极性或碰撞能量不同时默认拒绝。只有调用方明确传入允许混合时才继续，
    并且结果里会记下这个选择。
    """
    if polarity_a and polarity_b and polarity_a != polarity_b and not allow_polarity_mismatch:
        raise PolarityMismatch(
            f"极性不同（{polarity_a} 与 {polarity_b}）。混合比较必须由用户明确选择。"
        )
    if energy_a is not None and energy_b is not None:
        if abs(float(energy_a) - float(energy_b)) > 1e-6 and not allow_energy_mismatch:
            raise EnergyMismatch(
                f"碰撞能量不同（{energy_a:g} 与 {energy_b:g} eV）。混合比较必须由用户明确选择。"
            )
    scorer = ModifiedCosineGreedy(tolerance=float(tolerance_da))
    left = _spectrum(mz_a, intensity_a, precursor_a)
    right = _spectrum(mz_b, intensity_b, precursor_b)
    raw = scorer.pair(left, right)
    score = float(raw["score"]) if hasattr(raw, "dtype") and raw.dtype.names else float(raw[0])
    matches = int(raw["matches"]) if hasattr(raw, "dtype") and raw.dtype.names else int(raw[1])
    return SimilarityResult(
        score=score,
        matches=matches,
        tolerance_da=float(tolerance_da),
        allow_polarity_mismatch=allow_polarity_mismatch,
        allow_energy_mismatch=allow_energy_mismatch,
    )
