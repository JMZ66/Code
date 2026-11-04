from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from chem_wh.app_context import AppContext
from chem_wh.main import _resolve_db
from chem_wh.ui.login_dialog import LoginDialog
from chem_wh.ui.main_window import MainWindow
from chem_wh.ui.wizard import FirstRunWizard


def test_default_paths_keep_demo_away_from_production():
    class Args:
        demo = False
        mode = None
        db_path = None

    prod, demo = _resolve_db(Args())
    Args.demo = True
    demo_path, is_demo = _resolve_db(Args())
    assert demo is False and is_demo is True
    assert prod.endswith("chem_warehouse.db")
    assert demo_path.endswith("chem_warehouse_demo.db")
    assert prod != demo_path


def test_wizard_creates_only_the_real_admin(qtbot, tmp_path):
    ctx = AppContext(tmp_path / "prod.db")
    ctx.initialize_mode("production")
    wizard = FirstRunWizard(ctx)
    qtbot.addWidget(wizard)
    wizard.username.setText("labadmin")
    wizard.display_name.setText("张三")
    wizard.password.setText("LabAdmin#2026")
    wizard.password2.setText("LabAdmin#2026")
    wizard.location_name.setText("试剂库")
    wizard.submit()
    assert "声明" in wizard.error_label.text()
    wizard.agree.setChecked(True)
    wizard.password.setText("short")
    wizard.password2.setText("short")
    wizard.submit()
    assert wizard.error_label.text()
    wizard.password.setText("LabAdmin#2026")
    wizard.password2.setText("LabAdmin#2026")
    wizard.submit()
    assert ctx.current_user is not None
    assert ctx.current_user.username == "labadmin"
    users = ctx.db.fetchall("SELECT username, is_demo FROM users")
    assert [row["username"] for row in users] == ["labadmin"]
    assert int(users[0]["is_demo"]) == 0
    login = LoginDialog(ctx)
    qtbot.addWidget(login)
    assert "Admin@123" not in login.tip.text()
    window = MainWindow(ctx)
    qtbot.addWidget(window)
    titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    for name in ("工作台", "出入库", "盘点", "报表", "SDS"):
        assert name in titles
    assert window.demo_banner.isHidden()
    assert "不能替代" in window.banner.text()
    assert "delete_log" not in Path_text()
    ctx.close()


def Path_text() -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / "src" / "chem_wh" / "ui" / "main_window.py").read_text(
        encoding="utf-8"
    )


def test_gui_scan_and_idempotent_issue(qtbot, ctx, monkeypatch):
    def fail_if_warning(*args, **kwargs):
        raise AssertionError(args)

    monkeypatch.setattr(QMessageBox, "warning", fail_if_warning)
    ctx.login("warehouse1", "Wh@12345")
    window = MainWindow(ctx)
    qtbot.addWidget(window)
    assert not window.demo_banner.isHidden()
    row = ctx.db.fetchone(
        """
        SELECT c.id, c.container_code, c.quantity FROM containers c
        JOIN chemicals ch ON ch.id=c.chemical_id
        WHERE ch.name='盐酸'
        """
    )
    window.scan_edit.setText(row["container_code"])
    window.lookup_scan()
    assert row["container_code"] in window.scan_result.text()
    window.tx_code.setText(row["container_code"])
    window.tx_type.setCurrentIndex(window.tx_type.findData("issue"))
    window.tx_qty.setValue(2)
    window.tx_key = "gui-idem-key-0001"
    window.submit_tx()
    mid = ctx.db.fetchone("SELECT quantity FROM containers WHERE id=?", (row["id"],))
    assert float(mid["quantity"]) == float(row["quantity"]) - 2
    window.tx_key = "gui-idem-key-0001"
    window.tx_qty.setValue(2)
    window.submit_tx()
    after = ctx.db.fetchone("SELECT quantity FROM containers WHERE id=?", (row["id"],))
    assert float(after["quantity"]) == float(mid["quantity"])
    assert "未重复记账" in window.tx_status.text()
