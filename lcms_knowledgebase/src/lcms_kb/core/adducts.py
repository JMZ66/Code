"""常见加合离子和源内丢失提示。

这些只是 m/z 对照，帮助分析人员核对，不是化合物鉴定。
"""

from __future__ import annotations

from dataclasses import dataclass

from lcms_kb.core.masscalc import da_error, ion_mz, ppm_error


@dataclass(frozen=True)
class AdductSpec:
    name: str
    polarity: str
    charge: int
    multiplier: int
    loss_formula: str
    carrier: str
    kind: str  # adduct | in_source_loss
    note: str


# 电荷载体写法与 pyteomics.mass.calculate_mass 的 charge_carrier 一致。
ADDUCTS: tuple[AdductSpec, ...] = (
    AdductSpec("[M+H]+", "positive", 1, 1, "", "H+", "adduct", "质子加合"),
    AdductSpec("[M+Na]+", "positive", 1, 1, "", "Na+", "adduct", "钠加合"),
    AdductSpec("[M+NH4]+", "positive", 1, 1, "", "NH4+", "adduct", "铵加合"),
    AdductSpec("[M+K]+", "positive", 1, 1, "", "K+", "adduct", "钾加合"),
    AdductSpec("[M+H-H2O]+", "positive", 1, 1, "H2O", "H+", "in_source_loss", "源内失水提示"),
    AdductSpec("[M+H-NH3]+", "positive", 1, 1, "NH3", "H+", "in_source_loss", "源内失氨提示"),
    AdductSpec("[M+H-CO]+", "positive", 1, 1, "CO", "H+", "in_source_loss", "源内失 CO 提示"),
    AdductSpec("[M+H-CO2]+", "positive", 1, 1, "CO2", "H+", "in_source_loss", "源内失 CO2 提示"),
    AdductSpec("[M+H-HCOOH]+", "positive", 1, 1, "CH2O2", "H+", "in_source_loss", "源内失甲酸提示"),
    AdductSpec("[2M+H]+", "positive", 1, 2, "", "H+", "adduct", "二聚体质子加合"),
    AdductSpec("[2M+Na]+", "positive", 1, 2, "", "Na+", "adduct", "二聚体钠加合"),
    AdductSpec("[M-H]-", "negative", -1, 1, "", "H+", "adduct", "去质子"),
    AdductSpec("[M+Cl]-", "negative", -1, 1, "", "Cl-", "adduct", "氯加合"),
    AdductSpec("[M+HCOO]-", "negative", -1, 1, "", "HCOO-", "adduct", "甲酸根加合"),
    AdductSpec("[M+CH3COO]-", "negative", -1, 1, "", "CH3COO-", "adduct", "乙酸根加合"),
    AdductSpec("[M-H-H2O]-", "negative", -1, 1, "H2O", "H+", "in_source_loss", "源内失水提示"),
    AdductSpec("[M-H-CO2]-", "negative", -1, 1, "CO2", "H+", "in_source_loss", "源内失 CO2 提示"),
    AdductSpec("[2M-H]-", "negative", -1, 2, "", "H+", "adduct", "二聚体去质子"),
)

ASSISTANCE_BANNER = "辅助参考，不是化合物鉴定。高相似度和很小的 ppm 误差都不能当作定性结论。"


def adduct_by_name(name: str) -> AdductSpec:
    for item in ADDUCTS:
        if item.name == name:
            return item
    raise KeyError(name)


def theoretical_mz(formula: str, adduct: AdductSpec) -> float:
    return ion_mz(
        formula,
        charge=adduct.charge,
        charge_carrier=adduct.carrier,
        multiplier=adduct.multiplier,
        loss_formula=adduct.loss_formula,
    )


@dataclass(frozen=True)
class AdductRow:
    name: str
    polarity: str
    kind: str
    note: str
    theoretical_mz: float
    nearest_observed_mz: float | None
    ppm_error: float | None
    da_error: float | None
    banner: str = ASSISTANCE_BANNER


def adduct_table(formula: str, observed_peaks: list[tuple[float, float]] | None = None,
                 *, polarity: str | None = None) -> list[AdductRow]:
    """给出各加合离子的理论 m/z。若提供了实测 MS1 峰，附上最近峰和 ppm。

    最近峰只是数值上最近的点，不代表该峰就是这个加合离子。
    """
    rows: list[AdductRow] = []
    peaks = observed_peaks or []
    for spec in ADDUCTS:
        if polarity and spec.polarity != polarity:
            continue
        theo = theoretical_mz(formula, spec)
        nearest = None
        ppm = None
        da = None
        if peaks:
            nearest = min(peaks, key=lambda item: abs(item[0] - theo))[0]
            ppm = ppm_error(nearest, theo)
            da = da_error(nearest, theo)
        rows.append(AdductRow(
            name=spec.name,
            polarity=spec.polarity,
            kind=spec.kind,
            note=spec.note,
            theoretical_mz=theo,
            nearest_observed_mz=nearest,
            ppm_error=ppm,
            da_error=da,
        ))
    return rows
