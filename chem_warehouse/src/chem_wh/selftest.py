"""Headless self-test used by the packaged EXE and by CI.

It refuses to open an existing database so it cannot overwrite a real ledger.
Accounts created here exist only in the temporary file passed by the caller.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

from chem_wh import __version__
from chem_wh.constants import DISCLAIMER
from chem_wh.services.exceptions import AppError


def _guard_network():
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def blocked(self, address):  # noqa: ANN001
        raise RuntimeError(f"运行时禁止网络连接: {address}")

    socket.socket.connect = blocked  # type: ignore[method-assign]
    socket.socket.connect_ex = lambda self, address: blocked(self, address)  # type: ignore[method-assign]

    def restore() -> None:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]

    return restore


def run_self_test(db_path: str | None = None, report_path: str | None = None) -> int:
    restore = _guard_network()
    try:
        return _run(db_path, report_path)
    finally:
        restore()


def _run(db_path: str | None, report_path: str | None) -> int:
    from chem_wh.app_context import AppContext

    checks: list[str] = []
    payload: dict = {
        "ok": False,
        "version": __version__,
        "checks": checks,
        "disclaimer": DISCLAIMER,
        "network_policy": "socket.connect is rejected for this process",
    }
    ctx = None
    try:
        if not db_path:
            raise RuntimeError("self-test 必须显式传入一个尚不存在的 --db 路径")
        path = Path(db_path)
        if path.exists():
            raise RuntimeError("self-test 拒绝打开已存在的数据库，以免覆盖任何现有数据")
        path.parent.mkdir(parents=True, exist_ok=True)
        ctx = AppContext(path)
        if ctx.db.conn.execute("PRAGMA synchronous").fetchone()[0] != 2:
            raise RuntimeError("SQLite synchronous 不是 FULL")
        if str(ctx.db.conn.execute("PRAGMA journal_mode").fetchone()[0]).lower() != "wal":
            raise RuntimeError("SQLite 未处于 WAL 模式")
        checks.append("pragma")
        ctx.initialize_mode("production")
        ctx.bootstrap_production_admin("selftest_admin", "SelfTest#2026a", "自检管理员")
        admin = ctx.auth.authenticate("selftest_admin", "SelfTest#2026a")
        ctx.auth.create_user(
            "selftest_keeper",
            "SelfTest#2026b",
            "warehouse",
            "自检库管",
            actor=admin,
            production=True,
        )
        ctx.auth.create_user(
            "selftest_reviewer",
            "SelfTest#2026c",
            "safety",
            "自检复核",
            actor=admin,
            production=True,
        )
        keeper = ctx.auth.authenticate("selftest_keeper", "SelfTest#2026b")
        reviewer = ctx.auth.authenticate("selftest_reviewer", "SelfTest#2026c")
        checks.append("users")
        loc = ctx.chemicals.add_location(
            admin, level="warehouse", code="ST", name="自检库", storage_condition="阴凉"
        )
        shelf = ctx.chemicals.add_location(
            admin, level="shelf", code="S1", name="第1层", parent_id=loc
        )
        plain = ctx.chemicals.add_chemical(admin, name="自检试剂", cas_no="0000-00-0", specification="瓶")
        received = ctx.receive_new_container(
            keeper,
            chemical_id=plain,
            batch_no="LOT1",
            expiry_date="2099-01-01",
            quantity=100,
            unit="mL",
            location_id=shelf,
            remark="自检入库",
            idempotency_key="selftest-receive-0001",
        )
        again = ctx.receive_new_container(
            keeper,
            chemical_id=plain,
            batch_no="LOT1",
            expiry_date="2099-01-01",
            quantity=100,
            unit="mL",
            location_id=shelf,
            remark="自检入库",
            idempotency_key="selftest-receive-0001",
        )
        if not again.replay or again.container_id != received.container_id:
            raise RuntimeError("建瓶幂等重放失败")
        qty = ctx.db.fetchone(
            "SELECT quantity FROM containers WHERE id=?", (received.container_id,)
        )
        if float(qty["quantity"]) != 100:
            raise RuntimeError("入库数量不正确")
        checks.append("receive")
        ctx.stock.post_transaction(
            operator=keeper,
            tx_type="issue",
            container_id=received.container_id,
            quantity=30,
            remark="自检领用",
            idempotency_key="selftest-issue-0001",
        )
        ctx.stock.post_transaction(
            operator=keeper,
            tx_type="issue",
            container_id=received.container_id,
            quantity=30,
            remark="自检领用",
            idempotency_key="selftest-issue-0001",
        )
        qty = ctx.db.fetchone(
            "SELECT quantity FROM containers WHERE id=?", (received.container_id,)
        )
        if float(qty["quantity"]) != 70:
            raise RuntimeError("领用幂等失败，库存被重复扣减")
        checks.append("idempotency")
        cat = ctx.chemicals.add_controlled_category(
            admin, "STCTL", "自检管制类", "自检用，不是监管目录"
        )
        controlled = ctx.chemicals.add_chemical(admin, name="自检管制试剂", cas_no="0000-00-1")
        ctx.chemicals.set_chemical_controlled(admin, controlled, [cat])
        controlled_bottle = ctx.receive_new_container(
            keeper,
            chemical_id=controlled,
            batch_no="LOT2",
            expiry_date="2099-06-01",
            quantity=50,
            unit="mL",
            location_id=shelf,
            reviewer=reviewer,
            remark="管制入库",
            idempotency_key="selftest-ctrl-in-0001",
        )
        try:
            ctx.stock.post_transaction(
                operator=keeper,
                tx_type="issue",
                container_id=controlled_bottle.container_id,
                quantity=5,
            )
            raise RuntimeError("管制品领用在没有复核人时不应成功")
        except AppError:
            checks.append("dual_rejected")
        ctx.stock.post_transaction(
            operator=keeper,
            tx_type="issue",
            container_id=controlled_bottle.container_id,
            quantity=5,
            reviewer=reviewer,
            idempotency_key="selftest-ctrl-issue-01",
        )
        checks.append("dual_accepted")
        sid = ctx.inventory.start_session(keeper, shelf)
        ctx.inventory.add_line(keeper, sid, received.container_id, 70, "账实相符")
        ctx.inventory.cancel_session(keeper, sid)
        session = ctx.db.fetchone("SELECT status FROM inventory_sessions WHERE id=?", (sid,))
        qty = ctx.db.fetchone(
            "SELECT quantity FROM containers WHERE id=?", (received.container_id,)
        )
        if session["status"] != "cancelled" or float(qty["quantity"]) != 70:
            raise RuntimeError("取消盘点改变了库存或状态不对")
        checks.append("stocktake_cancel")
        out = path.parent
        xlsx = ctx.reports.export_stock_excel(admin, out / "selftest-stock.xlsx")
        pdf = ctx.reports.export_stock_pdf(admin, out / "selftest-stock.pdf")
        label = ctx.reports.export_labels_pdf(admin, out / "selftest-label.pdf", [received.container_id])
        if xlsx.stat().st_size < 100:
            raise RuntimeError("Excel 报表过小")
        for generated in (pdf, label):
            if generated.read_bytes()[:5] != b"%PDF-":
                raise RuntimeError(f"PDF 无效: {generated.name}")
        checks.append("reports")
        bak = ctx.backup.backup(admin, out)
        verified = ctx.backup.verify_archive(bak)
        if not verified["ok"]:
            raise RuntimeError(f"备份校验失败: {verified['errors']}")
        checks.append("backup")
        ok, msg = ctx.stock.verify_chain()
        if not ok:
            raise RuntimeError(msg)
        ok, msg = ctx.audit.verify_chain()
        if not ok:
            raise RuntimeError(msg)
        if ctx.db.integrity_check() != "ok":
            raise RuntimeError("完整性检查失败")
        checks.append("integrity")
        payload["ok"] = True
        payload["db"] = str(path)
        return _finish(report_path, payload, 0)
    except Exception as exc:  # noqa: BLE001
        payload["ok"] = False
        payload["error"] = str(exc)
        return _finish(report_path, payload, 1)
    finally:
        if ctx is not None:
            ctx.close()


def _finish(report_path: str | None, payload: dict, code: int) -> int:
    if report_path:
        Path(report_path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(payload, ensure_ascii=False))
    return code


if __name__ == "__main__":
    import sys

    db = sys.argv[1] if len(sys.argv) > 1 else None
    report = sys.argv[2] if len(sys.argv) > 2 else None
    raise SystemExit(run_self_test(db, report))
