from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from chem_wh.app_context import AppContext  # noqa: E402


@pytest.fixture()
def ctx(tmp_path: Path) -> AppContext:
    db = tmp_path / "test.db"
    app = AppContext(db)
    app.ensure_seed()
    yield app
    app.close()
