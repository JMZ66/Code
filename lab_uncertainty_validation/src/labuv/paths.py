"""Locate bundled fonts, examples and manuals in development and in a frozen build."""

from __future__ import annotations

import sys
from pathlib import Path


def bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def font_path() -> Path:
    path = bundle_root() / "assets" / "fonts" / "wqy-microhei.ttc"
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def docs_dir() -> Path:
    if getattr(sys, "frozen", False):
        beside = Path(sys.executable).resolve().parent / "docs"
        if beside.is_dir():
            return beside
    return bundle_root() / "docs"


def examples_dir() -> Path:
    if getattr(sys, "frozen", False):
        bundled = bundle_root() / "examples"
        if bundled.is_dir():
            return bundled
    packaged = Path(__file__).resolve().parent / "data" / "examples"
    if packaged.is_dir():
        return packaged
    bundled = bundle_root() / "examples"
    if bundled.is_dir():
        return bundled
    raise FileNotFoundError("examples")
