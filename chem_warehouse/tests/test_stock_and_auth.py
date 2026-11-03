from __future__ import annotations

import pytest

from chem_wh.services.exceptions import AuthError, PermissionError, StockError


def test_login_and_permission(ctx):
    admin = ctx.auth.authenticate("admin", "Admin@123")
    assert admin.role == "admin"
    viewer = ctx.auth.authenticate("viewer1", "Vw@12345")
    with pytest.raises(PermissionError):
        ctx.auth.require(viewer, "stock.write")
    with pytest.raises(AuthError):
        ctx.auth.authenticate("admin", "wrong")


def test_inbound_issue_quantity_tracking(ctx):
    wh = ctx.auth.authenticate("warehouse1", "Wh@12345")
    # pick HCl container
    row = ctx.db.fetchone(
        """
        SELECT c.id, c.quantity FROM containers c
        JOIN chemicals ch ON ch.id=c.chemical_id
        WHERE ch.name='盐酸' AND c.status='in_stock'
        """
    )
    before = float(row["quantity"])
    ctx.stock.post_transaction(
        operator=wh,
        tx_type="issue",
        container_id=int(row["id"]),
        quantity=50,
        remark="测试领用",
    )
    after = ctx.db.fetchone("SELECT quantity FROM containers WHERE id=?", (row["id"],))
    assert float(after["quantity"]) == pytest.approx(before - 50)

    # return
    ctx.stock.post_transaction(
        operator=wh,
        tx_type="return",
        container_id=int(row["id"]),
        quantity=20,
        remark="测试归还",
    )
    after2 = ctx.db.fetchone("SELECT quantity FROM containers WHERE id=?", (row["id"],))
    assert float(after2["quantity"]) == pytest.approx(before - 30)


def test_insufficient_stock(ctx):
    wh = ctx.auth.authenticate("warehouse1", "Wh@12345")
    row = ctx.db.fetchone(
        """
        SELECT c.id, c.quantity FROM containers c
        JOIN chemicals ch ON ch.id=c.chemical_id
        WHERE ch.name='硝酸'
        """
    )
    with pytest.raises(StockError):
        ctx.stock.post_transaction(
            operator=wh,
            tx_type="issue",
            container_id=int(row["id"]),
            quantity=float(row["quantity"]) + 10,
        )


def test_cannot_delete_transactions(ctx):
    wh = ctx.auth.authenticate("warehouse1", "Wh@12345")
    with pytest.raises(StockError):
        ctx.stock.delete_transaction(1)
    # ensure history remains
    n = ctx.db.fetchone("SELECT COUNT(*) AS c FROM stock_transactions")
    assert int(n["c"]) >= 1
    _ = wh


def test_dual_control_required_for_precursor(ctx):
    wh1 = ctx.auth.authenticate("warehouse1", "Wh@12345")
    acetone = ctx.db.fetchone(
        """
        SELECT c.id FROM containers c
        JOIN chemicals ch ON ch.id=c.chemical_id
        WHERE ch.name='丙酮' AND c.status='in_stock'
        LIMIT 1
        """
    )
    with pytest.raises(StockError):
        ctx.stock.post_transaction(
            operator=wh1,
            tx_type="issue",
            container_id=int(acetone["id"]),
            quantity=10,
        )

    # same user as reviewer rejected
    with pytest.raises(PermissionError):
        ctx.auth.verify_second_user(wh1, "warehouse1", "Wh@12345")

    wh2 = ctx.auth.verify_second_user(wh1, "warehouse2", "Wh@12345")
    tx_id = ctx.stock.post_transaction(
        operator=wh1,
        tx_type="issue",
        container_id=int(acetone["id"]),
        quantity=10,
        reviewer=wh2,
        remark="双人复核领用",
    )
    tx = ctx.db.fetchone("SELECT * FROM stock_transactions WHERE id=?", (tx_id,))
    assert tx["dual_required"] == 1
    assert tx["reviewer_id"] == wh2.id
    assert tx["operator_id"] != tx["reviewer_id"]


def test_transfer_requires_human_compat_confirm(ctx):
    wh = ctx.auth.authenticate("warehouse1", "Wh@12345")
    safety = ctx.auth.authenticate("safety1", "Sf@12345")
    row = ctx.db.fetchone(
        """
        SELECT c.id, c.location_id FROM containers c
        JOIN chemicals ch ON ch.id=c.chemical_id
        WHERE ch.name='甲醇'
        """
    )
    # create another shelf
    loc = ctx.chemicals.add_location(
        ctx.auth.authenticate("admin", "Admin@123"),
        level="shelf",
        code="S9",
        name="临时层",
        parent_id=row["location_id"],
    )
    with pytest.raises(StockError):
        ctx.stock.post_transaction(
            operator=wh,
            tx_type="transfer",
            container_id=int(row["id"]),
            quantity=0,
            to_location_id=loc,
            human_confirmed_compatibility=False,
        )
    ctx.stock.post_transaction(
        operator=wh,
        tx_type="transfer",
        container_id=int(row["id"]),
        quantity=0,
        to_location_id=loc,
        human_confirmed_compatibility=True,
        remark="人工确认后调拨",
    )
    _ = safety
