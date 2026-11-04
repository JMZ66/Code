"""读入内存的谱图对象。数组来自文件里真实存在的峰。"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


MODE_ZH = {
    "full_scan": "全扫描",
    "dda": "DDA",
    "dia": "DIA",
    "dia_aif": "DIA/AIF",
    "sim": "SIM",
    "srm": "SRM/MRM",
    "unknown": "未知",
}

POLARITY_ZH = {
    "positive": "正离子",
    "negative": "负离子",
    "unknown": "极性未知",
}

SAMPLE_TYPES = ("unknown", "sample", "blank", "qc", "standard")
SAMPLE_TYPE_ZH = {
    "unknown": "未标记",
    "sample": "样品",
    "blank": "空白",
    "qc": "QC",
    "standard": "标准品",
}


@dataclass
class RunHeader:
    """文件头部能直接读到的采集信息。缺失就保持空，不猜测厂商。"""

    format_name: str
    spectrum_count_declared: int | None
    instrument_terms: list[str] = field(default_factory=list)
    software_terms: list[str] = field(default_factory=list)
    source_file_terms: list[str] = field(default_factory=list)
    file_content_terms: list[str] = field(default_factory=list)
    acquisition_terms: list[str] = field(default_factory=list)
    vendors_inferred: list[str] = field(default_factory=list)
    test_only_synthetic: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class Scan:
    index_in_file: int
    scan_number: int
    ms_level: int | None
    polarity: str
    rt_min: float | None
    rt_unit: str | None
    scan_mode: str
    scan_mode_basis: str
    precursor_mz: float | None
    precursor_charge: int | None
    isolation_lower_offset: float | None
    isolation_upper_offset: float | None
    isolation_width: float | None
    collision_energy: float | None
    activation: str | None
    tic: float
    bpc: float
    bpc_mz: float | None
    reported_tic: float | None
    centroid: bool | None
    filter_string: str | None
    mz: np.ndarray
    intensity: np.ndarray
    cv_terms: tuple[str, ...] = ()

    @property
    def polarity_zh(self) -> str:
        return POLARITY_ZH.get(self.polarity, self.polarity)

    @property
    def scan_mode_zh(self) -> str:
        label = MODE_ZH.get(self.scan_mode, self.scan_mode)
        if self.scan_mode_basis.startswith("heuristic"):
            return f"{label}（推断）"
        return label
