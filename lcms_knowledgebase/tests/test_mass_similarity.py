"""质量、同位素、加合离子、相似度和 MSP/MGF。"""

import numpy as np
import pytest

from lcms_kb.core.adducts import ADDUCTS, adduct_by_name, adduct_table, theoretical_mz
from lcms_kb.core.isotopes import theoretical_isotope_pattern
from lcms_kb.core.library_io import LibrarySpectrum, read_mgf, read_msp, write_mgf, write_msp
from lcms_kb.core.masscalc import da_error, ion_mz, neutral_mass, ppm_error, within_tolerance
from lcms_kb.core.similarity import modified_cosine
from lcms_kb.errors import EnergyMismatch, PolarityMismatch

# pyteomics.nist_mass 使用的 NIST 同位素质量。这里写成字面量，避免测试只是自己和自己比。
C12 = 12.0
H1 = 1.00782503207
N14 = 14.0030740048
O16 = 15.99491461956
NA23 = 22.9897692809
ELECTRON = 0.00054857990943
PROTON = H1 - ELECTRON


def _caffeine() -> float:
    return 8 * C12 + 10 * H1 + 4 * N14 + 2 * O16


def _glucose() -> float:
    return 6 * C12 + 12 * H1 + 6 * O16


def test_neutral_and_protonated_mass_against_nist_arithmetic():
    assert neutral_mass("C8H10N4O2") == pytest.approx(_caffeine(), abs=1e-6)
    assert neutral_mass("C6H12O6") == pytest.approx(_glucose(), abs=1e-6)
    caffeine_h = ion_mz("C8H10N4O2", charge=1, charge_carrier="H+")
    assert caffeine_h == pytest.approx(_caffeine() + PROTON, abs=1e-6)
    glucose_h = ion_mz("C6H12O6", charge=1)
    assert glucose_h == pytest.approx(_glucose() + PROTON, abs=1e-6)
    # 公开常用的咖啡因 [M+H]+ 约 195.08765
    assert caffeine_h == pytest.approx(195.08765, abs=5e-5)
    assert ppm_error(caffeine_h + 0.001, caffeine_h) == pytest.approx(0.001 / caffeine_h * 1e6)
    assert da_error(100.002, 100.0) == pytest.approx(0.002)
    assert within_tolerance(100.0004, 100.0, 5, "ppm")
    assert not within_tolerance(100.01, 100.0, 5, "ppm")


def test_adduct_table_covers_required_ions():
    names = {item.name for item in ADDUCTS}
    for required in ("[M+H]+", "[M+Na]+", "[M+NH4]+", "[M-H]-", "[M+HCOO]-"):
        assert required in names
    glucose = _glucose()
    assert theoretical_mz("C6H12O6", adduct_by_name("[M+Na]+")) == pytest.approx(glucose + NA23 - ELECTRON, abs=1e-5)
    assert theoretical_mz("C6H12O6", adduct_by_name("[M-H]-")) == pytest.approx(glucose - PROTON, abs=1e-5)
    # 甲酸根 HCOO 质量 = H + C + 2O，负离子再加一个电子。
    formate = H1 + C12 + 2 * O16
    assert theoretical_mz("C6H12O6", adduct_by_name("[M+HCOO]-")) == pytest.approx(glucose + formate + ELECTRON, abs=1e-4)
    rows = adduct_table("C6H12O6", [(181.0707, 1000.0)], polarity="positive")
    assert all(row.banner.startswith("辅助参考") for row in rows)
    proton = next(row for row in rows if row.name == "[M+H]+")
    assert proton.ppm_error is not None
    assert abs(proton.ppm_error) < 5


def test_isotope_pattern_matches_binomial_carbon():
    pattern = theoretical_isotope_pattern("C6", adduct_by_name("[M+H]+"), overall_threshold=1e-6)
    mono = pattern.peaks[0]
    plus = pattern.peaks[1]
    expected_ratio = 6 * (0.0107 / 0.9893)
    assert plus.relative_abundance / mono.relative_abundance == pytest.approx(expected_ratio, rel=0.02)
    glucose = theoretical_isotope_pattern("C6H12O6", adduct_by_name("[M+H]+"))
    assert glucose.peaks[0].mz == pytest.approx(theoretical_mz("C6H12O6", adduct_by_name("[M+H]+")), abs=1e-6)
    assert glucose.banner.startswith("理论同位素分布")
    assert glucose.peaks[0].relative_abundance == pytest.approx(100)


def test_modified_cosine_reference_and_guards():
    identical = modified_cosine([50, 80], [3, 4], 100, [50, 80], [3, 4], 100,
                                polarity_a="positive", polarity_b="positive",
                                energy_a=20, energy_b=20)
    assert identical.score == pytest.approx(1.0, abs=1e-9)
    assert identical.matches == 2
    # 只匹配 80：点积 16，范数 5 和 4，得分 0.8。这是 matchms 用全部峰范数归一的定义。
    partial = modified_cosine([50, 80], [3, 4], 100, [80], [4], 100, tolerance_da=0.05)
    assert partial.score == pytest.approx(0.8, abs=1e-9)
    assert partial.matches == 1
    none = modified_cosine([50], [3], 100, [90], [4], 100, tolerance_da=0.01)
    assert none.score == pytest.approx(0.0, abs=1e-12)
    assert none.matches == 0
    # 前体差 10，碎片也差 10，修正余弦应为 1。
    shifted = modified_cosine([50, 80], [3, 4], 100, [60, 90], [3, 4], 110, tolerance_da=0.05)
    assert shifted.score == pytest.approx(1.0, abs=1e-9)
    with pytest.raises(PolarityMismatch):
        modified_cosine([50], [1], 100, [50], [1], 100, polarity_a="positive", polarity_b="negative")
    allowed = modified_cosine([50], [1], 100, [50], [1], 100,
                              polarity_a="positive", polarity_b="negative",
                              allow_polarity_mismatch=True)
    assert allowed.allow_polarity_mismatch
    with pytest.raises(EnergyMismatch):
        modified_cosine([50], [1], 100, [50], [1], 100, energy_a=10, energy_b=30)
    mixed = modified_cosine([50], [1], 100, [50], [1], 100, energy_a=10, energy_b=30,
                            allow_energy_mismatch=True)
    assert mixed.allow_energy_mismatch


def test_msp_mgf_roundtrip(tmp_path):
    spec = LibrarySpectrum(
        name="测试化合物",
        formula="C6H12O6",
        adduct="[M+H]+",
        polarity="positive",
        retention_time_min=1.25,
        precursor_mz=181.07066,
        collision_energy=20,
        activation="collision-induced dissociation",
        mz=np.array([50.0, 80.0, 120.0]),
        intensity=np.array([5.0, 9.0, 2.0]),
        comments="TEST ONLY SYNTHETIC",
    )
    msp = tmp_path / "lib.msp"
    mgf = tmp_path / "lib.mgf"
    write_msp(msp, [spec])
    write_mgf(mgf, [spec])
    back_msp = read_msp(msp)
    back_mgf = read_mgf(mgf)
    assert len(back_msp) == 1 and len(back_mgf) == 1
    for back in (back_msp[0], back_mgf[0]):
        assert list(back.mz) == pytest.approx([50, 80, 120])
        assert list(back.intensity) == pytest.approx([5, 9, 2])
        assert back.precursor_mz == pytest.approx(181.07066, rel=1e-6)
        assert back.name == "测试化合物"
        assert back.formula == "C6H12O6"
        assert back.polarity == "positive"
        assert back.collision_energy == pytest.approx(20)
