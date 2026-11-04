"""Locate bundled files in source checkouts and in a frozen Windows build."""

from __future__ import annotations

import os
import sys
from pathlib import Path

FONT_FILENAME = "DroidSansFallbackFull.ttf"


def source_root() -> Path:
    """chem_warehouse directory when running from a source tree."""
    return Path(__file__).resolve().parents[3]


def meipass_root() -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return None


def font_path() -> Path:
    env = os.environ.get("CHEM_WH_FONT", "").strip()
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))
    frozen = meipass_root()
    if frozen is not None:
        candidates.append(frozen / "assets" / "fonts" / FONT_FILENAME)
    exe_dir = Path(sys.executable).resolve().parent
    candidates.append(exe_dir / "assets" / "fonts" / FONT_FILENAME)
    candidates.append(exe_dir / "_internal" / "assets" / "fonts" / FONT_FILENAME)
    candidates.append(source_root() / "assets" / "fonts" / FONT_FILENAME)
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "未找到中文字体 DroidSansFallbackFull.ttf，无法生成含中文的 PDF。"
    )


def docs_search_paths() -> list[Path]:
    paths: list[Path] = []
    exe_dir = Path(sys.executable).resolve().parent
    paths.append(exe_dir / "docs")
    frozen = meipass_root()
    if frozen is not None:
        paths.append(frozen / "docs")
    paths.append(source_root() / "docs")
    return paths


def find_doc(*names: str) -> Path | None:
    for folder in docs_search_paths():
        for name in names:
            candidate = folder / name
            if candidate.is_file():
                return candidate
    return None
