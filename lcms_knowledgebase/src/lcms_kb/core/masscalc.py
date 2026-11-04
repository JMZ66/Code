"""分子式质量、加合离子 m/z 和 ppm。计算交给 pyteomics.mass。"""

from __future__ import annotations

from pyteomics import mass

from lcms_kb.errors import LCMSError


class FormulaError(LCMSError):
    """分子式无法被 pyteomics 解析。"""


def neutral_mass(formula: str) -> float:
    """单同位素中性分子质量。"""
    try:
        return float(mass.calculate_mass(formula=formula))
    except Exception as exc:  # pyteomics 对非法分子式抛出多种异常
        raise FormulaError(f"无法计算分子式 {formula!r} 的质量：{exc}") from exc


def ion_mz(formula: str, *, charge: int, charge_carrier: str = "H+", multiplier: int = 1,
           loss_formula: str = "") -> float:
    """由中性分子式、聚体倍数、中性丢失和电荷载体计算离子 m/z。

    质子加合和去质子走 pyteomics 的默认载体，用的是质子质量而不是氢原子质量。
    其他载体（Na+、NH4+、Cl-、HCOO- 等）在 pyteomics 里按中性原子加入，
    这里再补上或减去电子质量，使结果等于离子质量。
    """
    if charge == 0:
        raise FormulaError("离子电荷不能为 0")
    if multiplier < 1:
        raise FormulaError("分子倍数至少为 1")
    proton_carrier = charge_carrier in {"", "H+", "H-"}
    try:
        composition = mass.Composition(formula=formula) * multiplier
        if loss_formula:
            composition -= mass.Composition(formula=loss_formula)
        kwargs = {"composition": composition, "charge": charge, "absolute": True}
        if not proton_carrier:
            kwargs["charge_carrier"] = charge_carrier
        value = float(mass.calculate_mass(**kwargs))
    except Exception as exc:
        raise FormulaError(
            f"无法计算 {formula} 的离子质量（载体 {charge_carrier}，电荷 {charge}）：{exc}"
        ) from exc
    if not proton_carrier:
        electron = float(mass.nist_mass["e-"][0][0])
        signed = value if charge > 0 else -value
        value = abs(signed - electron)
    return value


def ppm_error(observed_mz: float, theoretical_mz: float) -> float:
    """(观测 − 理论) / 理论 × 10^6。正值表示观测偏高。"""
    if theoretical_mz == 0:
        raise FormulaError("理论 m/z 为 0，不能计算 ppm")
    return (observed_mz - theoretical_mz) / theoretical_mz * 1e6


def da_error(observed_mz: float, theoretical_mz: float) -> float:
    return observed_mz - theoretical_mz


def tolerance_window(target_mz: float, tolerance: float, unit: str) -> tuple[float, float]:
    """返回闭区间 [low, high]。``unit`` 为 ``ppm`` 或 ``da``。"""
    unit_norm = unit.strip().lower()
    if unit_norm == "ppm":
        delta = abs(target_mz) * abs(tolerance) * 1e-6
    elif unit_norm == "da":
        delta = abs(tolerance)
    else:
        raise FormulaError("容差单位只能是 ppm 或 da")
    return target_mz - delta, target_mz + delta


def within_tolerance(observed_mz: float, target_mz: float, tolerance: float, unit: str) -> bool:
    low, high = tolerance_window(target_mz, tolerance, unit)
    return low <= observed_mz <= high
