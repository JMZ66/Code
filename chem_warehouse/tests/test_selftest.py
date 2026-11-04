from __future__ import annotations

import json
from pathlib import Path

from chem_wh.selftest import run_self_test


def test_self_test_on_a_new_database(tmp_path: Path):
    db = tmp_path / "self.db"
    report = tmp_path / "report.json"
    code = run_self_test(str(db), str(report))
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert code == 0, payload
    assert payload["ok"] is True
    for name in ("pragma", "receive", "idempotency", "dual_rejected", "dual_accepted", "stocktake_cancel", "reports", "backup", "integrity"):
        assert name in payload["checks"]
    assert "不能替代" in payload["disclaimer"]
    assert not (tmp_path / "self.db").joinpath("nope").exists()


def test_self_test_refuses_an_existing_database(tmp_path: Path):
    db = tmp_path / "already.db"
    db.write_bytes(b"do-not-touch")
    report = tmp_path / "report.json"
    code = run_self_test(str(db), str(report))
    assert code == 1
    assert db.read_bytes() == b"do-not-touch"
