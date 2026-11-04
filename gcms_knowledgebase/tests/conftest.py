import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

from pathlib import Path

import pytest

from gcms_kb.service import KnowledgeBase


@pytest.fixture
def kb(tmp_path):
    return KnowledgeBase(tmp_path / "data")


PUBLIC_MZML = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "gcms_kb"
    / "resources"
    / "testdata"
    / "public"
    / "small.pwiz.1.1.mzML"
)
