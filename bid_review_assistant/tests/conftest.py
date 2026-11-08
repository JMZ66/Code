from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture(scope="session")
def fixture_pack() -> Path:
    pack = ROOT / "testdata" / "complex_pack"
    if not (pack / "01_招标正文.docx").exists():
        runpy.run_path(str(ROOT / "scripts" / "build_fixture_pack.py"), run_name="__main__")
    assert (pack / "01_招标正文.docx").exists()
    return pack
