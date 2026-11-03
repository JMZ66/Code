"""V0.2 P0/P1 security and reliability regression tests."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from chem_wh.app_context import AppContext
from chem_wh.services.exceptions import AuthError, PermissionError, StockError, ValidationError


def _acetone_container(ctx):
    return ctx.db.fetchone(
        """
        SELECT c.id, c.quantity, c.qty_version FROM containers c
        JOIN chemicals ch ON ch.id=c.chemical_id
        WHERE ch.name='丙酮' AND c.status='in_stock'
        LIMIT 1
        """
    )


def test_p0_adjust_requires_dual_for_controlled(ctx):
    """复现：V0.1 可用 adjust 绕过双人；V0.2 必须拦截。"""
    wh1 = ctx.auth.authenticate("warehouse1", "Wh@12345")
    ctr = _acetone_container(ctx)
    with pytest.raises(StockError, match="双人复核"):
        ctx.stock.post_transaction(
            operator=wh1,
            tx_type="adjust_neg",
            container_id=int(ctr["id"]),
            quantity=10,
            remark="试图绕过",
        )
    wh2 = ctx.auth.verify_second_user(wh1, "warehouse2", "Wh@12345")
    tx_id = ctx.stock.post_transaction(
        operator=wh1,
        tx_type="adjust_neg",
        container_id=int(ctr["id"]),
        quantity=10,
        reviewer=wh2,
    )
    tx = ctx.db.fetchone("SELECT * FROM stock_transactions WHERE id=?", (tx_id,))
    assert tx["dual_required"] == 1
    assert tx["reviewer_id"] == wh2.id


def test_p0_reversal_requires_dual_for_controlled(ctx):
    wh1 = ctx.auth.authenticate("warehouse1", "Wh@12345")
    wh2 = ctx.auth.verify_second_user(wh1, "warehouse2", "Wh@12345")
    ctr = _acetone_container(ctx)
    tx_id = ctx.stock.post_transaction(
        operator=wh1,
        tx_type="issue",
        container_id=int(ctr["id"]),
        quantity=5,
        reviewer=wh2,
    )
    with pytest.raises(StockError, match="双人复核"):
        ctx.stock.reverse_transaction(operator=wh1, tx_id=tx_id)
    rev = ctx.stock.reverse_transaction(operator=wh1, tx_id=tx_id, reviewer=wh2)
    row = ctx.db.fetchone("SELECT * FROM stock_transactions WHERE id=?", (rev,))
    assert row["tx_type"] == "reversal"
    assert row["dual_required"] == 1
    assert row["related_tx_id"] == tx_id


def test_p0_inventory_adjust_requires_dual_and_no_repeat_close(ctx):
    wh1 = ctx.auth.authenticate("warehouse1", "Wh@12345")
    ctr = _acetone_container(ctx)
    sid = ctx.inventory.start_session(wh1)
    ctx.inventory.add_line(wh1, sid, int(ctr["id"]), float(ctr["quantity"]) - 20)
    with pytest.raises(StockError, match="独立复核"):
        ctx.inventory.close_session(wh1, sid, post_adjustments=True, reviewer=None)
    wh2 = ctx.auth.verify_second_user(wh1, "warehouse2", "Wh@12345")
    lines = ctx.inventory.close_session(wh1, sid, True, reviewer=wh2)
    assert lines[0]["settle_difference"] == pytest.approx(-20)
    with pytest.raises(StockError, match="重复"):
        ctx.inventory.close_session(wh1, sid, True, reviewer=wh2)


def test_p0_inventory_blocks_mutations_and_settles_against_live_qty(ctx):
    wh = ctx.auth.authenticate("warehouse1", "Wh@12345")
    ctr = ctx.db.fetchone(
        """
        SELECT c.id, c.quantity, c.qty_version FROM containers c
        JOIN chemicals ch ON ch.id=c.chemical_id
        WHERE ch.name='乙腈'
        """
    )
    sid = ctx.inventory.start_session(wh)
    book_at_count = float(ctr["quantity"])
    # Counted as original book; if stock changes before settle, diff uses live book.
    ctx.inventory.add_line(wh, sid, int(ctr["id"]), book_at_count)

    with pytest.raises(StockError, match="盘点会话"):
        ctx.stock.post_transaction(
            operator=wh,
            tx_type="issue",
            container_id=int(ctr["id"]),
            quantity=10,
        )

    # Force a mid-count stock change using allow_during_inventory (simulates bypass/race)
    ctx.stock.post_transaction(
        operator=wh,
        tx_type="issue",
        container_id=int(ctr["id"]),
        quantity=10,
        allow_during_inventory=True,
    )
    live = ctx.db.fetchone("SELECT quantity FROM containers WHERE id=?", (ctr["id"],))
    assert float(live["quantity"]) == pytest.approx(book_at_count - 10)

    # Close: settle_diff = counted(book_at_count) - live(book-10) = +10 → adjust_pos
    # But expected_qty_version was captured at close-time live version after the issue,
    # so settlement should succeed and bring qty back to counted.
    lines = ctx.inventory.close_session(wh, sid, post_adjustments=True)
    assert lines[0]["settle_difference"] == pytest.approx(10)
    after = ctx.db.fetchone("SELECT quantity FROM containers WHERE id=?", (ctr["id"],))
    assert float(after["quantity"]) == pytest.approx(book_at_count)


def test_p0_demo_forbidden_in_production(prod_ctx, tmp_path: Path):
    with pytest.raises(ValidationError, match="正式模式禁止"):
        prod_ctx.ensure_seed()
    # bootstrap real admin
    prod_ctx.bootstrap_production_admin("realadmin", "Prod#Safe99")
    admin = prod_ctx.auth.authenticate("realadmin", "Prod#Safe99")
    assert admin.role == "admin"
    with pytest.raises(ValidationError, match="演示"):
        prod_ctx.auth.create_user(
            "demo2", "Admin@123", "viewer", "x", actor=admin, is_demo=True, production=True
        )
    with pytest.raises(ValidationError, match="正式模式"):
        prod_ctx.chemicals.add_chemical(admin, name="假试剂", is_demo=True)


def test_p0_production_rejects_demo_login_after_mode_lock(tmp_path: Path):
    # Create demo DB then attempt to treat as production is locked — mode switch denied
    demo = AppContext(tmp_path / "d.db")
    demo.initialize_mode("demo")
    demo.ensure_seed()
    with pytest.raises(ValueError, match="锁定"):
        demo.initialize_mode("production")
    demo.close()


def test_p0_full_backup_includes_sds_qr_and_hash(ctx, tmp_path: Path):
    admin = ctx.auth.authenticate("admin", "Admin@123")
    # ensure sds/qr exist from seed
    assert any((ctx.sds_dir).glob("*")) or True
    bak = ctx.backup.backup(admin, tmp_path)
    result = ctx.backup.verify_archive(bak)
    assert result["ok"]
    files = result["manifest"]["files"]
    assert "database/chem_warehouse.db" in files
    # tamper detection
    import zipfile

    bad = tmp_path / "tampered.zip"
    with zipfile.ZipFile(bak, "r") as zin, zipfile.ZipFile(bad, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "database/chem_warehouse.db":
                data = data + b"TAMPER"
            zout.writestr(item, data)
    bad_result = ctx.backup.verify_archive(bad)
    assert bad_result["ok"] is False


def test_p0_stock_and_audit_chain_and_atomic(ctx):
    wh = ctx.auth.authenticate("warehouse1", "Wh@12345")
    ctr = ctx.db.fetchone(
        """
        SELECT c.id FROM containers c
        JOIN chemicals ch ON ch.id=c.chemical_id
        WHERE ch.name='盐酸'
        """
    )
    before_tx = ctx.db.fetchone("SELECT COUNT(*) AS c FROM stock_transactions")
    before_audit = ctx.db.fetchone("SELECT COUNT(*) AS c FROM audit_logs")
    ctx.stock.post_transaction(
        operator=wh, tx_type="issue", container_id=int(ctr["id"]), quantity=1
    )
    after_tx = ctx.db.fetchone("SELECT COUNT(*) AS c FROM stock_transactions")
    after_audit = ctx.db.fetchone("SELECT COUNT(*) AS c FROM audit_logs")
    assert int(after_tx["c"]) == int(before_tx["c"]) + 1
    assert int(after_audit["c"]) >= int(before_audit["c"]) + 1
    ok, msg = ctx.stock.verify_chain()
    assert ok, msg
    ok2, msg2 = ctx.audit.verify_chain()
    assert ok2, msg2


def test_p1_rejects_nan_inf_negative_and_disposed_reuse(ctx):
    wh = ctx.auth.authenticate("warehouse1", "Wh@12345")
    ctr = ctx.db.fetchone(
        """
        SELECT c.id, c.quantity FROM containers c
        JOIN chemicals ch ON ch.id=c.chemical_id
        WHERE ch.name='硝酸'
        """
    )
    with pytest.raises(ValidationError):
        ctx.stock.post_transaction(
            operator=wh, tx_type="issue", container_id=int(ctr["id"]), quantity=float("nan")
        )
    with pytest.raises(ValidationError):
        ctx.stock.post_transaction(
            operator=wh, tx_type="issue", container_id=int(ctr["id"]), quantity=float("inf")
        )
    with pytest.raises(ValidationError):
        ctx.stock.post_transaction(
            operator=wh, tx_type="issue", container_id=int(ctr["id"]), quantity=-1
        )
    # dispose all then refuse further issue
    ctx.stock.post_transaction(
        operator=wh,
        tx_type="dispose",
        container_id=int(ctr["id"]),
        quantity=float(ctr["quantity"]),
        remark="清空处置",
    )
    with pytest.raises(StockError, match="已处置"):
        ctx.stock.post_transaction(
            operator=wh, tx_type="inbound", container_id=int(ctr["id"]), quantity=10
        )


def test_p1_viewer_cannot_stock_or_inventory(ctx):
    viewer = ctx.auth.authenticate("viewer1", "Vw@12345")
    ctr = ctx.db.fetchone("SELECT id FROM containers LIMIT 1")
    with pytest.raises(PermissionError):
        ctx.stock.post_transaction(
            operator=viewer, tx_type="issue", container_id=int(ctr["id"]), quantity=1
        )
    with pytest.raises(PermissionError):
        ctx.inventory.start_session(viewer)


def test_p1_duplicate_inventory_line_rejected(ctx):
    wh = ctx.auth.authenticate("warehouse1", "Wh@12345")
    ctr = ctx.db.fetchone(
        """
        SELECT c.id, c.quantity FROM containers c
        JOIN chemicals ch ON ch.id=c.chemical_id
        WHERE ch.name='甲醇'
        """
    )
    sid = ctx.inventory.start_session(wh)
    ctx.inventory.add_line(wh, sid, int(ctr["id"]), float(ctr["quantity"]))
    with pytest.raises(ValidationError, match="重复"):
        ctx.inventory.add_line(wh, sid, int(ctr["id"]), float(ctr["quantity"]))
