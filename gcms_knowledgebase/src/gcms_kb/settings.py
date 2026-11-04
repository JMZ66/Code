from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class Settings:
    user_name: str = ""
    first_run: bool = True
    thermo_parser_path: str = ""
    msconvert_path: str = ""
    msdial_console_path: str = ""
    amdis_path: str = ""
    mz_tolerance: float = 0.5
    rt_tolerance: float = 0.05
    ri_tolerance: float = 20.0
    similarity_min: float = 0.0
    similarity_top_k: int = 10
    mz_power: float = 1.0
    intensity_power: float = 0.5
    cosine_tolerance: float = 0.1
    background_subtract: bool = True
    deconv_apex_tol: float = 0.05
    deconv_mz_bin: float = 1.0
    convert_timeout_sec: int = 3600

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Settings":
        path = Path(path)
        if not path.is_file():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        known = {item.name for item in fields(cls)}
        values = {key: value for key, value in raw.items() if key in known}
        return cls(**values)
