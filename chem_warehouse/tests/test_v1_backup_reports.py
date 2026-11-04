from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from openpyxl import load_workbook
from pypdf import PdfReader

from chem_wh.app_context import AppContext
from chem_wh.db.database import CURRENT_SCHEMA_VERSION
from chem_wh.docpdf import render_markdown_pdf
from chem_wh.services.exceptions import PermissionError, ValidationError
from chem_wh.utils.resources import source_root


def test_restore_requires_confirmation_and_rejects_corrupt_files(ctx, tmp_path: Path):
    admin = ctx.auth.authenticate("admin", "Admin@123")
    ctx.db.execute("UPDATE chemicals SET notes='changed-before-restore' WHERE name='盐酸'")
    original = ctx.db.fetchone("SELECT notes FROM chemicals WHERE name='盐酸'")["notes"]
    with pytest.raises(ValidationError, match="确认"):
        ctx.backup.restore(admin, tmp_path / "missing.zip", confirmed=False)
    assert ctx.db.fetchone("SELECT notes FROM chemicals WHERE name='盐酸'")["notes"] == original

    good = ctx.backup.backup(admin, tmp_path)
    bad = tmp_path / "bad-hash.zip"
    with zipfile.ZipFile(good, "r") as zin, zipfile.ZipFile(bad, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "database/chem_warehouse.db":
                data = data + b"TAMPER"
            zout.writestr(item, data)
    with pytest.raises(ValidationError, match="校验失败"):
        ctx.backup.restore(admin, bad, confirmed=True)
    assert ctx.db.fetchone("SELECT notes FROM chemicals WHERE name='盐酸'")["notes"] == original

    raw = b"SQLite format 3\x00" + b"not-a-database" * 20
    digest = hashlib.sha256(raw).hexdigest()
    manifest = {
        "created_at": "2026-01-01T00:00:00+00:00",
        "app": "chem_warehouse",
        "version": "1.0.0",
        "files": {"database/chem_warehouse.db": {"sha256": digest, "size": len(raw)}},
    }
    corrupt = tmp_path / "corrupt-db.zip"
    with zipfile.ZipFile(corrupt, "w") as zout:
        zout.writestr("database/chem_warehouse.db", raw)
        zout.writestr("manifest.json", json.dumps(manifest))
    with pytest.raises(ValidationError, match="完整性|无法"):
        ctx.backup.restore(admin, corrupt, confirmed=True)
    assert ctx.db.fetchone("SELECT notes FROM chemicals WHERE name='盐酸'")["notes"] == original


def test_restore_round_trip_keeps_a_pre_backup(ctx, tmp_path: Path):
    admin = ctx.auth.authenticate("admin", "Admin@123")
    snap = ctx.backup.backup(admin, tmp_path)
    ctx.db.execute("UPDATE chemicals SET notes='after-backup' WHERE name='盐酸'")
    pre = ctx.backup.restore(admin, snap, confirmed=True)
    assert pre.is_file()
    assert "演示" in (ctx.db.fetchone("SELECT notes FROM chemicals WHERE name='盐酸'")["notes"] or "")
    checked = ctx.backup.verify_archive(pre)
    assert checked["ok"]
    with zipfile.ZipFile(pre) as zf, tmp_path.joinpath("pre.db").open("wb") as handle:
        handle.write(zf.read("database/chem_warehouse.db"))
    conn = sqlite3.connect(tmp_path / "pre.db")
    note = conn.execute("SELECT notes FROM chemicals WHERE name='盐酸'").fetchone()[0]
    conn.close()
    assert note == "after-backup"
    assert ctx.db.integrity_check() == "ok"


def test_audit_is_append_only_and_detects_tampering(ctx):
    with pytest.raises(PermissionError):
        ctx.audit.delete_log(1)
    ok, _msg = ctx.audit.verify_chain()
    assert ok
    ctx.db.execute(
        "UPDATE audit_logs SET detail_json='tampered' WHERE id=(SELECT MAX(id) FROM audit_logs)"
    )
    ok, msg = ctx.audit.verify_chain()
    assert ok is False
    assert "mismatch" in msg
    with pytest.raises(Exception):
        ctx.stock.delete_transaction(1)


def test_reports_excel_and_chinese_pdf(ctx, tmp_path: Path):
    admin = ctx.auth.authenticate("admin", "Admin@123")
    wh = ctx.auth.authenticate("warehouse1", "Wh@12345")
    wh2 = ctx.auth.verify_second_user(wh, "warehouse2", "Wh@12345")
    bottle = ctx.db.fetchone(
        """
        SELECT c.id FROM containers c
        JOIN chemicals ch ON ch.id=c.chemical_id
        WHERE ch.name='丙酮' LIMIT 1
        """
    )
    sid = ctx.inventory.start_session(wh)
    qty = ctx.db.fetchone("SELECT quantity FROM containers WHERE id=?", (bottle["id"],))
    ctx.inventory.add_line(wh, sid, int(bottle["id"]), float(qty["quantity"]), "相符")
    ctx.inventory.close_session(wh, sid, True, reviewer=wh2)

    files = {
        "stock.xlsx": ctx.reports.export_stock_excel(admin, tmp_path / "stock.xlsx"),
        "stock.pdf": ctx.reports.export_stock_pdf(admin, tmp_path / "stock.pdf"),
        "tx.xlsx": ctx.reports.export_transactions_excel(admin, tmp_path / "tx.xlsx"),
        "tx.pdf": ctx.reports.export_transactions_pdf(admin, tmp_path / "tx.pdf"),
        "exp.xlsx": ctx.reports.export_expiry_excel(admin, tmp_path / "exp.xlsx"),
        "exp.pdf": ctx.reports.export_expiry_pdf(admin, tmp_path / "exp.pdf"),
        "ctrl.xlsx": ctx.reports.export_controlled_excel(admin, tmp_path / "ctrl.xlsx"),
        "ctrl.pdf": ctx.reports.export_controlled_pdf(admin, tmp_path / "ctrl.pdf"),
        "count.xlsx": ctx.reports.export_stocktake_excel(admin, tmp_path / "count.xlsx", sid),
        "count.pdf": ctx.reports.export_stocktake_pdf(admin, tmp_path / "count.pdf", sid),
        "label.pdf": ctx.reports.export_labels_pdf(admin, tmp_path / "label.pdf", [int(bottle["id"])]),
    }
    stock = load_workbook(files["stock.xlsx"]).active
    assert stock["A1"].value == "名称"
    assert any(cell.value == "盐酸" for row in stock.iter_rows(min_row=2, max_col=1) for cell in row)
    tx = load_workbook(files["tx.xlsx"]).active
    assert tx["A1"].value == "单号"
    ctrl = load_workbook(files["ctrl.xlsx"]).active
    assert any((cell.value or "") == "丙酮" for row in ctrl.iter_rows(min_row=2, max_col=1) for cell in row)
    for name in ("stock.pdf", "tx.pdf", "exp.pdf", "ctrl.pdf", "count.pdf"):
        text = "\n".join((page.extract_text() or "") for page in PdfReader(files[name]).pages)
        assert "不能替代" in text
    label_text = "\n".join((page.extract_text() or "") for page in PdfReader(files["label.pdf"]).pages)
    assert "丙酮" in label_text
    count_text = "\n".join((page.extract_text() or "") for page in PdfReader(files["count.pdf"]).pages)
    assert "盘点" in count_text


def test_manual_pdf_contains_chinese(tmp_path: Path):
    manual = source_root() / "docs" / "用户手册.md"
    pdf = render_markdown_pdf(manual, tmp_path / "manual.pdf")
    text = "\n".join((page.extract_text() or "") for page in PdfReader(pdf).pages)
    assert "入库" in text
    assert "双人复核" in text
    assert "不能替代" in text


def test_fresh_database_has_no_migration_backup_and_legacy_does(tmp_path: Path):
    db = tmp_path / "fresh.db"
    ctx = AppContext(db)
    assert int(ctx.db.conn.execute("PRAGMA user_version").fetchone()[0]) == CURRENT_SCHEMA_VERSION
    assert list(tmp_path.glob("*.bak-migrate-*")) == []
    ctx.initialize_mode("production")
    ctx.bootstrap_production_admin("realadmin", "Prod#Safe99", "管理员")
    ctx.close()

    conn = sqlite3.connect(db)
    conn.execute("PRAGMA user_version=2")
    conn.commit()
    conn.close()
    again = AppContext(db)
    try:
        backups = list(tmp_path.glob("*.bak-migrate-*"))
        assert backups
        row = again.db.fetchone("SELECT username FROM users WHERE username='realadmin'")
        assert row["username"] == "realadmin"
        assert int(again.db.conn.execute("PRAGMA user_version").fetchone()[0]) == 3
    finally:
        again.close()


def test_source_has_no_network_client():
    root = Path(__file__).resolve().parents[1] / "src"
    text = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    for banned in (
        "import requests",
        "import httpx",
        "urllib.request",
        "QNetworkAccessManager",
        "socket.create_connection",
    ):
        assert banned not in text
