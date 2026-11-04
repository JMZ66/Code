from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from chem_wh.app_context import AppContext

SRC = Path(__file__).resolve().parents[1] / "src"
WORKER = Path(__file__).resolve().parent / "crash_worker.py"


def _hcl(ctx: AppContext):
    return ctx.db.fetchone(
        """
        SELECT c.id, c.quantity FROM containers c
        JOIN chemicals ch ON ch.id=c.chemical_id
        WHERE ch.name='盐酸' AND c.status='in_stock'
        """
    )


def _spawn(mode: str, db: Path, cid: int, ready: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            str(WORKER),
            mode,
            str(SRC),
            str(db),
            str(cid),
            str(ready),
            "warehouse1",
            "Wh@12345",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _wait_ready(proc: subprocess.Popen, ready: Path) -> None:
    deadline = time.time() + 20
    while time.time() < deadline:
        if ready.exists():
            text = ready.read_text(encoding="utf-8")
            if text.startswith("ERROR"):
                proc.kill()
                raise AssertionError(text)
            if text == "ready":
                return
        if proc.poll() is not None:
            err = proc.stderr.read().decode("utf-8", errors="replace")
            raise AssertionError(err or "worker exited before ready")
        time.sleep(0.1)
    proc.kill()
    raise AssertionError("worker did not reach the crash point")


def _reopen(db: Path) -> AppContext:
    last = None
    for _ in range(20):
        try:
            return AppContext(db)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.25)
    raise AssertionError(last)


def test_kill_during_uncommitted_transaction_keeps_stock(tmp_path: Path):
    db = tmp_path / "crash.db"
    ctx = AppContext(db)
    ctx.initialize_mode("demo")
    ctx.ensure_seed()
    row = _hcl(ctx)
    cid = int(row["id"])
    before_qty = float(row["quantity"])
    before_tx = int(ctx.db.fetchone("SELECT COUNT(*) AS c FROM stock_transactions")["c"])
    ctx.close()

    ready = tmp_path / "ready.txt"
    proc = _spawn("open-tx", db, cid, ready)
    try:
        _wait_ready(proc, ready)
        proc.kill()
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()

    again = _reopen(db)
    try:
        qty = again.db.fetchone("SELECT quantity FROM containers WHERE id=?", (cid,))
        txs = again.db.fetchone("SELECT COUNT(*) AS c FROM stock_transactions")
        assert float(qty["quantity"]) == pytest.approx(before_qty)
        assert float(qty["quantity"]) != pytest.approx(12345)
        assert int(txs["c"]) == before_tx
        assert again.db.integrity_check() == "ok"
        assert again.db.foreign_key_violations() == []
    finally:
        again.close()


def test_kill_after_commit_keeps_the_posted_issue(tmp_path: Path):
    db = tmp_path / "crash2.db"
    ctx = AppContext(db)
    ctx.initialize_mode("demo")
    ctx.ensure_seed()
    row = _hcl(ctx)
    cid = int(row["id"])
    before_qty = float(row["quantity"])
    ctx.close()

    ready = tmp_path / "ready2.txt"
    proc = _spawn("commit-then-sleep", db, cid, ready)
    try:
        _wait_ready(proc, ready)
        proc.kill()
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()

    again = _reopen(db)
    try:
        qty = again.db.fetchone("SELECT quantity FROM containers WHERE id=?", (cid,))
        assert float(qty["quantity"]) == pytest.approx(before_qty - 1)
        assert again.db.integrity_check() == "ok"
        ok, msg = again.stock.verify_chain()
        assert ok, msg
    finally:
        again.close()
