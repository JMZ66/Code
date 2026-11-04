from __future__ import annotations

from pathlib import Path

import pytest

from chem_wh.services.exceptions import PermissionError, ValidationError


def test_alerts_cover_expiry_low_missing_sds(ctx):
    alerts = ctx.alerts.all_alerts()
    # 过氧化氢演示数据过期且缺已审核 SDS
    assert any(a["name"] == "过氧化氢" for a in alerts["expired"])
    assert any(a["name"] == "过氧化氢" for a in alerts["missing_sds"])
    assert "low_stock" in alerts
    assert "over_stock" in alerts


def test_audit_log_on_login_and_stock(ctx):
    wh = ctx.login("warehouse1", "Wh@12345")
    row = ctx.db.fetchone(
        """
        SELECT c.id FROM containers c
        JOIN chemicals ch ON ch.id=c.chemical_id
        WHERE ch.name='乙腈'
        """
    )
    ctx.stock.post_transaction(
        operator=wh, tx_type="issue", container_id=int(row["id"]), quantity=5
    )
    logs = ctx.audit.list_recent(50)
    actions = {r["action"] for r in logs}
    assert "auth.login" in actions
    assert "stock.issue" in actions


def test_backup_and_restore(ctx, tmp_path: Path):
    admin = ctx.auth.authenticate("admin", "Admin@123")
    bak = ctx.backup.backup(admin, tmp_path)
    assert bak.exists()
    assert bak.suffix == ".zip"
    verified = ctx.backup.verify_archive(bak)
    assert verified["ok"] is True

    # mutate
    ctx.db.execute("UPDATE chemicals SET notes='changed' WHERE name='盐酸'")
    note = ctx.db.fetchone("SELECT notes FROM chemicals WHERE name='盐酸'")
    assert note["notes"] == "changed"

    ctx.backup.restore(admin, bak, confirmed=True)
    note2 = ctx.db.fetchone("SELECT notes FROM chemicals WHERE name='盐酸'")
    assert "演示" in (note2["notes"] or "")


def test_viewer_cannot_backup(ctx, tmp_path: Path):
    viewer = ctx.auth.authenticate("viewer1", "Vw@12345")
    with pytest.raises(PermissionError):
        ctx.backup.backup(viewer, tmp_path)


def test_inventory_variance_posts_adjustment(ctx):
    wh = ctx.auth.authenticate("warehouse1", "Wh@12345")
    ctr = ctx.db.fetchone(
        """
        SELECT c.id, c.quantity FROM containers c
        JOIN chemicals ch ON ch.id=c.chemical_id
        WHERE ch.name='乙腈'
        """
    )
    sid = ctx.inventory.start_session(wh)
    book = float(ctr["quantity"])
    counted = book - 15
    ctx.inventory.add_line(wh, sid, int(ctr["id"]), counted, "少了15")
    lines = ctx.inventory.close_session(wh, sid, post_adjustments=True)
    assert len(lines) == 1
    assert lines[0]["settle_difference"] == pytest.approx(-15)
    after = ctx.db.fetchone("SELECT quantity FROM containers WHERE id=?", (ctr["id"],))
    assert float(after["quantity"]) == pytest.approx(counted)


def test_hazard_must_be_approved(ctx):
    admin = ctx.auth.authenticate("admin", "Admin@123")
    safety = ctx.auth.authenticate("safety1", "Sf@12345")
    hid = ctx.chemicals.add_hazard_class(safety, "TMP", "未审核类", "x")
    chem_id = ctx.chemicals.add_chemical(admin, name="临时试剂")
    with pytest.raises(ValidationError):
        ctx.chemicals.attach_approved_hazard(admin, chem_id, hid, "no")
    ctx.chemicals.review_hazard_class(safety, hid, "approved")
    ctx.chemicals.attach_approved_hazard(admin, chem_id, hid, "单位制度")
