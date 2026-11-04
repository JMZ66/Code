from __future__ import annotations

import sys
from pathlib import Path


def app_data_dir() -> Path:
    override = __import__("os").environ.get("GCMS_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(__import__("os").environ.get("LOCALAPPDATA", str(Path.home())))
    else:
        base = Path(__import__("os").environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return base / "GCMS_KnowledgeBase"


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS"))
        candidates = [
            base.joinpath("gcms_kb", "resources", *parts),
            base.joinpath("resources", *parts),
            base.joinpath(*parts),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]
    return package_dir().joinpath("resources", *parts)


def locate_doc(filename: str) -> Path | None:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / filename)
        candidates.append(Path(getattr(sys, "_MEIPASS")) / filename)
    candidates.append(package_dir().parents[1] / filename)
    candidates.append(package_dir() / "resources" / "docs" / filename)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def assert_under(root: Path, path: Path) -> Path:
    from gcms_kb.errors import UnsafePath

    root_r = root.resolve()
    path_r = path.resolve()
    if path_r != root_r and root_r not in path_r.parents:
        raise UnsafePath(f"路径不在数据目录内，已拒绝写入：{path}")
    return path_r
