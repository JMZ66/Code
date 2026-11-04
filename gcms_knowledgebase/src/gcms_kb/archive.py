from __future__ import annotations

from pathlib import Path

import numpy as np

from gcms_kb.mzml_io import RunData


def save_run(path: Path, run: RunData) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        rt=run.rt,
        tic=run.tic,
        bpc=run.bpc,
        offsets=run.offsets,
        mz=run.mz,
        intensity=run.intensity,
        file_hint=np.array(run.file_hint),
        instrument=np.array(run.instrument),
        is_synthetic=np.array(1 if run.is_synthetic else 0),
    )


def _text(value) -> str:
    if isinstance(value, np.ndarray):
        if value.shape == ():
            item = value.item()
            return "" if item is None else str(item)
        if value.size == 0:
            return ""
    return "" if value is None else str(value)


def load_run(path: Path) -> RunData:
    with np.load(path, allow_pickle=False) as data:
        return RunData(
            rt=np.asarray(data["rt"], dtype=float),
            tic=np.asarray(data["tic"], dtype=float),
            bpc=np.asarray(data["bpc"], dtype=float),
            offsets=np.asarray(data["offsets"], dtype=np.int64),
            mz=np.asarray(data["mz"], dtype=float),
            intensity=np.asarray(data["intensity"], dtype=float),
            file_hint=_text(data["file_hint"]),
            instrument=_text(data["instrument"]),
            is_synthetic=bool(int(data["is_synthetic"])),
            n_scans=int(len(data["rt"])),
        )
