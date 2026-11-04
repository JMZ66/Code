"""MSP / MGF 读写。峰列表原样交给 matchms，不补峰。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from matchms import Spectrum
from matchms.exporting import save_as_mgf, save_as_msp
from matchms.importing import load_from_mgf, load_from_msp


@dataclass(frozen=True)
class LibrarySpectrum:
    name: str
    formula: str | None
    adduct: str | None
    polarity: str | None
    retention_time_min: float | None
    precursor_mz: float | None
    collision_energy: float | None
    activation: str | None
    mz: np.ndarray
    intensity: np.ndarray
    comments: str


def _to_matchms(spec: LibrarySpectrum) -> Spectrum:
    metadata = {
        "compound_name": spec.name or "",
        "precursor_mz": None if spec.precursor_mz is None else float(spec.precursor_mz),
        "formula": spec.formula or "",
        "adduct": spec.adduct or "",
        "ionmode": spec.polarity or "",
        "retention_time": "" if spec.retention_time_min is None else spec.retention_time_min,
        "collision_energy": "" if spec.collision_energy is None else spec.collision_energy,
        "activation": spec.activation or "",
        "comments": spec.comments or "",
    }
    # matchms 会丢掉值为 None 的前体；没有前体就不要写这个键。
    if metadata["precursor_mz"] is None:
        metadata.pop("precursor_mz")
    return Spectrum(
        mz=np.asarray(spec.mz, dtype=float),
        intensities=np.asarray(spec.intensity, dtype=float),
        metadata=metadata,
    )


def _from_matchms(spec: Spectrum) -> LibrarySpectrum:
    meta = dict(spec.metadata)
    def _text(key: str) -> str | None:
        value = meta.get(key)
        if value is None or value == "":
            return None
        return str(value)

    def _float(key: str) -> float | None:
        value = meta.get(key)
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    peaks_mz = np.asarray(spec.peaks.mz, dtype=float)
    peaks_i = np.asarray(spec.peaks.intensities, dtype=float)
    return LibrarySpectrum(
        name=_text("compound_name") or _text("name") or "",
        formula=_text("formula"),
        adduct=_text("adduct"),
        polarity=_text("ionmode") or _text("polarity"),
        retention_time_min=_float("retention_time"),
        precursor_mz=_float("precursor_mz"),
        collision_energy=_float("collision_energy"),
        activation=_text("activation"),
        mz=peaks_mz,
        intensity=peaks_i,
        comments=_text("comments") or "",
    )


def write_msp(path: Path, spectra: list[LibrarySpectrum]) -> None:
    save_as_msp([_to_matchms(item) for item in spectra], str(path), mode="w")


def write_mgf(path: Path, spectra: list[LibrarySpectrum]) -> None:
    save_as_mgf([_to_matchms(item) for item in spectra], str(path), file_mode="w")


def read_msp(path: Path) -> list[LibrarySpectrum]:
    return [_from_matchms(item) for item in load_from_msp(str(path), metadata_harmonization=False)]


def read_mgf(path: Path) -> list[LibrarySpectrum]:
    return [_from_matchms(item) for item in load_from_mgf(str(path), metadata_harmonization=False)]
