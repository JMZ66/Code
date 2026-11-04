from __future__ import annotations

from datetime import date, timedelta

import pytest

from chem_wh.services.exceptions import AuthError, PermissionError, StockError, ValidationError


def _user(ctx, name, password):
    return ctx.auth.authenticate(name, password)


def _bottle(ctx, name):
    return ctx.db.fetchone(
        """
        SELECT c.* FROM containers c
        JOIN chemicals ch ON ch.id=c.chemical_id
        WHERE ch.name=? AND c.status='in_stock'
        ORDER BY c.quantity DESC LIMIT 1
        """,
        (name,),
    )


def test_sqlite_is_wal_and_fully_synchronous(ctx):
    assert str(ctx.db.conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
    assert int(ctx.db.conn.execute("PRAGMA synchronous").fetchone()[0]) == 2
    assert int(ctx.db.conn.execute("PRAGMA user_version").fetchone()[0]) == 3


def test_idempotent_replay_posts_once(ctx):
    wh = _user(ctx, "warehouse1", "Wh@12345")
    row = _bottle(ctx, "盐酸")
    before = float(row["quantity"])
    key = "idem-acid-issue-0001"
    first = ctx.stock.post_transaction(
        operator=wh,
        tx_type="issue",
        container_id=int(row["id"]),
        quantity=4,
        remark="同一笔",
        idempotency_key=key,
    )
    second = ctx.stock.post_transaction(
        operator=wh,
        tx_type="issue",
        container_id=int(row["id"]),
        quantity=4,
        remark="同一笔",
        idempotency_key=key,
    )
    after = ctx.db.fetchone("SELECT quantity FROM containers WHERE id=?", (row["id"],))
    assert first == second
    assert float(after["quantity"]) == pytest.approx(before - 4)
    with pytest.raises(ValidationError, match="另一笔"):
        ctx.stock.post_transaction(
            operator=wh,
            tx_type="issue",
            container_id=int(row["id"]),
            quantity=5,
            remark="同一笔",
            idempotency_key=key,
        )
    after2 = ctx.db.fetchone("SELECT quantity FROM containers WHERE id=?", (row["id"],))
    assert float(after2["quantity"]) == pytest.approx(before - 4)


def test_every_controlled_operation_needs_a_different_authorized_user(ctx):
    wh1 = _user(ctx, "warehouse1", "Wh@12345")
    wh2 = ctx.auth.verify_second_user(wh1, "warehouse2", "Wh@12345")
    row = _bottle(ctx, "丙酮")
    cid = int(row["id"])
    admin = _user(ctx, "admin", "Admin@123")
    other = ctx.chemicals.add_location(
        admin, level="shelf", code="MOVE", name="调拨层", parent_id=row["location_id"]
    )
    plan = [
        ("issue", 1, {}),
        ("return", 1, {}),
        ("inbound", 1, {}),
        ("adjust_neg", 1, {}),
        ("adjust_pos", 1, {}),
        ("dispose", 1, {}),
        (
            "transfer",
            0,
            {"to_location_id": other, "human_confirmed_compatibility": True},
        ),
    ]
    for tx_type, qty, extra in plan:
        with pytest.raises(StockError, match="双人复核"):
            ctx.stock.post_transaction(
                operator=wh1,
                tx_type=tx_type,
                container_id=cid,
                quantity=qty,
                **extra,
            )
        ctx.stock.post_transaction(
            operator=wh1,
            tx_type=tx_type,
            container_id=cid,
            quantity=qty,
            reviewer=wh2,
            **extra,
        )
    issued = ctx.stock.post_transaction(
        operator=wh1, tx_type="issue", container_id=cid, quantity=1, reviewer=wh2
    )
    with pytest.raises(StockError, match="双人复核"):
        ctx.stock.reverse_transaction(operator=wh1, tx_id=issued)
    ctx.stock.reverse_transaction(operator=wh1, tx_id=issued, reviewer=wh2)
    with pytest.raises(PermissionError):
        ctx.auth.verify_second_user(wh1, "warehouse1", "Wh@12345")
    with pytest.raises(AuthError):
        ctx.auth.verify_second_user(wh1, "warehouse2", "wrong-password")
    with pytest.raises(PermissionError):
        ctx.auth.verify_second_user(wh1, "viewer1", "Vw@12345")
    qty = ctx.db.fetchone("SELECT quantity FROM containers WHERE id=?", (cid,))
    assert float(qty["quantity"]) >= 0


def test_inactive_category_stops_requiring_review_and_removal_needs_reviewer(ctx):
    admin = _user(ctx, "admin", "Admin@123")
    safety = _user(ctx, "safety1", "Sf@12345")
    wh = _user(ctx, "warehouse1", "Wh@12345")
    cat = ctx.chemicals.add_controlled_category(admin, "TEMP", "临时管制", "测试")
    chem = ctx.chemicals.add_chemical(admin, name="临时对照试剂")
    ctx.chemicals.set_chemical_controlled(admin, chem, [cat])
    loc = ctx.db.fetchone("SELECT id FROM locations LIMIT 1")
    received = ctx.receive_new_container(
        wh,
        chemical_id=chem,
        batch_no="T",
        expiry_date="2099-01-01",
        quantity=20,
        unit="mL",
        location_id=int(loc["id"]),
        reviewer=safety,
        idempotency_key="recv-temp-0001",
    )
    again = ctx.receive_new_container(
        wh,
        chemical_id=chem,
        batch_no="T",
        expiry_date="2099-01-01",
        quantity=20,
        unit="mL",
        location_id=int(loc["id"]),
        reviewer=safety,
        idempotency_key="recv-temp-0001",
    )
    assert again.replay is True
    assert again.container_id == received.container_id
    bottles = ctx.db.fetchone("SELECT COUNT(*) AS c FROM containers WHERE chemical_id=?", (chem,))
    assert int(bottles["c"]) == 1
    with pytest.raises(StockError):
        ctx.chemicals.set_chemical_controlled(admin, chem, [])
    ctx.chemicals.set_chemical_controlled(admin, chem, [], reviewer=safety)
    ctx.stock.post_transaction(
        operator=wh,
        tx_type="issue",
        container_id=received.container_id,
        quantity=1,
    )


def test_wrong_location_and_negative_paths(ctx):
    wh = _user(ctx, "warehouse1", "Wh@12345")
    row = _bottle(ctx, "甲醇")
    with pytest.raises(ValidationError, match="库位不存在"):
        ctx.stock.post_transaction(
            operator=wh,
            tx_type="transfer",
            container_id=int(row["id"]),
            quantity=0,
            to_location_id=987654,
            human_confirmed_compatibility=True,
        )
    with pytest.raises(StockError, match="库位"):
        ctx.stock.post_transaction(
            operator=wh,
            tx_type="issue",
            container_id=int(row["id"]),
            quantity=1,
            expected_location_id=987654,
        )
    before = float(row["quantity"])
    with pytest.raises(StockError, match="库存不足"):
        ctx.stock.post_transaction(
            operator=wh,
            tx_type="issue",
            container_id=int(row["id"]),
            quantity=before + 1,
        )
    after = ctx.db.fetchone("SELECT quantity FROM containers WHERE id=?", (row["id"],))
    assert float(after["quantity"]) == pytest.approx(before)


def test_stocktake_cancel_leaves_stock_and_confirm_is_once(ctx):
    wh = _user(ctx, "warehouse1", "Wh@12345")
    row = _bottle(ctx, "乙腈")
    before = float(row["quantity"])
    sid = ctx.inventory.start_session(wh)
    ctx.inventory.add_line(wh, sid, int(row["id"]), before - 8, "先记一笔")
    ctx.inventory.cancel_session(wh, sid)
    status = ctx.db.fetchone("SELECT status FROM inventory_sessions WHERE id=?", (sid,))
    qty = ctx.db.fetchone("SELECT quantity FROM containers WHERE id=?", (row["id"],))
    assert status["status"] == "cancelled"
    assert float(qty["quantity"]) == pytest.approx(before)
    with pytest.raises(StockError):
        ctx.inventory.close_session(wh, sid, True)
    ctx.stock.post_transaction(
        operator=wh, tx_type="issue", container_id=int(row["id"]), quantity=1
    )


def test_controlled_stocktake_confirm_requires_reviewer_even_without_diff(ctx):
    wh1 = _user(ctx, "warehouse1", "Wh@12345")
    wh2 = ctx.auth.verify_second_user(wh1, "warehouse2", "Wh@12345")
    row = _bottle(ctx, "丙酮")
    before = float(row["quantity"])
    sid = ctx.inventory.start_session(wh1)
    ctx.inventory.add_line(wh1, sid, int(row["id"]), before, "账实相符")
    with pytest.raises(StockError, match="独立复核"):
        ctx.inventory.close_session(wh1, sid, True)
    ctx.inventory.close_session(wh1, sid, True, reviewer=wh2)
    qty = ctx.db.fetchone("SELECT quantity FROM containers WHERE id=?", (row["id"],))
    assert float(qty["quantity"]) == pytest.approx(before)
    with pytest.raises(StockError):
        ctx.inventory.cancel_session(wh1, sid)


def test_failed_close_rolls_back_every_adjustment(ctx, monkeypatch):
    wh = _user(ctx, "warehouse1", "Wh@12345")
    rows = ctx.db.fetchall(
        """
        SELECT c.id, c.quantity FROM containers c
        JOIN chemicals ch ON ch.id=c.chemical_id
        WHERE ch.controlled_flags='' AND c.status='in_stock'
        ORDER BY c.id LIMIT 2
        """
    )
    assert len(rows) >= 2
    sid = ctx.inventory.start_session(wh)
    for row in rows:
        ctx.inventory.add_line(wh, sid, int(row["id"]), float(row["quantity"]) - 1)
    original = ctx.stock.post_transaction
    calls = {"n": 0}

    def wrapped(**kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise StockError("第二笔记账失败")
        return original(**kwargs)

    monkeypatch.setattr(ctx.stock, "post_transaction", wrapped)
    with pytest.raises(StockError, match="第二笔"):
        ctx.inventory.close_session(wh, sid, True)
    session = ctx.db.fetchone("SELECT status, adjustments_posted FROM inventory_sessions WHERE id=?", (sid,))
    assert session["status"] == "open"
    assert int(session["adjustments_posted"]) == 0
    for row in rows:
        qty = ctx.db.fetchone("SELECT quantity FROM containers WHERE id=?", (row["id"],))
        assert float(qty["quantity"]) == pytest.approx(float(row["quantity"]))


def test_role_permissions(ctx):
    admin = _user(ctx, "admin", "Admin@123")
    ctx.auth.create_user("ordinary1", "User#123456", "user", "普通用户", actor=admin)
    ctx.auth.create_user("auditonly", "Audit#12345", "auditor", "审计员", actor=admin)
    warehouse = _user(ctx, "warehouse1", "Wh@12345")
    safety = _user(ctx, "safety1", "Sf@12345")
    viewer = _user(ctx, "viewer1", "Vw@12345")
    ordinary = _user(ctx, "ordinary1", "User#123456")
    auditor = _user(ctx, "auditonly", "Audit#12345")
    bottle = _bottle(ctx, "盐酸")
    for person in (viewer, ordinary, auditor, safety):
        with pytest.raises(PermissionError):
            ctx.stock.post_transaction(
                operator=person, tx_type="issue", container_id=int(bottle["id"]), quantity=1
            )
    for person in (viewer, ordinary, auditor):
        with pytest.raises(PermissionError):
            ctx.auth.verify_second_user(warehouse, person.username, {
                "viewer1": "Vw@12345",
                "ordinary1": "User#123456",
                "auditonly": "Audit#12345",
            }[person.username])
    with pytest.raises(PermissionError):
        ctx.backup.backup(warehouse, "/tmp")
    with pytest.raises(PermissionError):
        ctx.auth.list_users(ordinary)
    assert auditor.has("audit.read")
    assert not auditor.has("stock.write")
    ctx.auth.list_users(auditor)
    with pytest.raises(PermissionError):
        ctx.auth.create_user("nope", "Nope#123456", "user", "不行", actor=warehouse)


def test_expiry_and_location_overstock(ctx):
    admin = _user(ctx, "admin", "Admin@123")
    soon = (date.today() + timedelta(days=5)).isoformat()
    row = _bottle(ctx, "甲醇")
    ctx.db.execute("UPDATE containers SET expiry_date=? WHERE id=?", (soon, row["id"]))
    ctx.settings.set_expiry_warn_days(admin, 30)
    alerts = ctx.alerts.all_alerts()
    assert any(item["container_code"] == row["container_code"] for item in alerts["expiring"])
    assert any(item["name"] == "过氧化氢" for item in alerts["expired"])
    ctx.chemicals.set_stock_limit(
        _user(ctx, "safety1", "Sf@12345"),
        int(row["chemical_id"]),
        0,
        1,
        row["unit"],
        int(row["location_id"]),
    )
    alerts = ctx.alerts.all_alerts()
    assert any(
        item["name"] == "甲醇" and "全库" not in item["location_name"]
        for item in alerts["over_stock"]
    )
    empty = ctx.chemicals.add_location(admin, level="shelf", code="EMPTY", name="空层")
    ctx.chemicals.set_stock_limit(
        _user(ctx, "safety1", "Sf@12345"),
        int(row["chemical_id"]),
        0,
        1,
        row["unit"],
        empty,
    )
    alerts = ctx.alerts.all_alerts()
    assert not any(item["location_name"].startswith("空层") for item in alerts["over_stock"])
