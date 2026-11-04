from __future__ import annotations

from pathlib import Path

import numpy as np
from matchms.exporting import save_as_msp
from matchms.importing import load_from_msp

from gcms_kb.similarity import to_spectrum


def _cas_from_metadata(metadata: dict) -> str:
    for key in ("cas", "casno", "cas_number", "related_cas#", "cas#"):
        value = metadata.get(key)
        if value:
            return str(value).strip()
    return ""


def _float_or_none(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_msp(path: Path) -> list[dict]:
    """用 matchms 读取 MSP。返回的记录只是谱库条目，不是样品鉴定。"""
    records = []
    for spectrum in load_from_msp(str(path)):
        metadata = dict(spectrum.metadata)
        name = str(metadata.get("compound_name") or metadata.get("name") or "").strip()
        if not name:
            name = "未命名谱图"
        records.append(
            {
                "name": name,
                "cas": _cas_from_metadata(metadata),
                "formula": str(metadata.get("formula") or "").strip(),
                "ri": _float_or_none(metadata.get("retention_index")),
                "rt": _float_or_none(metadata.get("retention_time")),
                "comment": str(metadata.get("comment") or ""),
                "mz": np.asarray(spectrum.peaks.mz, dtype=float),
                "intensity": np.asarray(spectrum.peaks.intensities, dtype=float),
            }
        )
    return records


def write_msp(path: Path, records: list[dict]) -> None:
    """用 matchms 按 NIST 风格写出 MSP。"""
    spectra = []
    for record in records:
        metadata = {"compound_name": record.get("name") or "未命名谱图"}
        if record.get("cas"):
            metadata["cas"] = str(record["cas"])
        if record.get("formula"):
            metadata["formula"] = str(record["formula"])
        if record.get("ri") is not None:
            metadata["retention_index"] = float(record["ri"])
        if record.get("rt") is not None:
            metadata["retention_time"] = float(record["rt"])
        comment = record.get("comment") or ""
        metadata["comment"] = comment
        spectrum = to_spectrum(record.get("mz", []), record.get("intensity", []), metadata)
        if spectrum is not None:
            spectra.append(spectrum)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    if not spectra:
        path.write_text("", encoding="utf-8")
        return
    save_as_msp(spectra, str(path), mode="w", style="nist")
