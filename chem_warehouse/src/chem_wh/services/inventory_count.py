from __future__ import annotations

from typing import Optional

from chem_wh.db.database import Database
from chem_wh.services.audit import AuditService
from chem_wh.services.auth import AuthService, UserSession
from chem_wh.services.exceptions import StockError, ValidationError
from chem_wh.services.stock import StockService, _validate_quantity
from chem_wh.utils.codes import next_code
from chem_wh.utils.timeutil import now_iso


class InventoryCountService:
    def __init__(
        self,
        db: Database,
        auth: AuthService,
        audit: AuditService,
        stock: StockService,
    ):
        self.db = db
        self.auth = auth
        self.audit = audit
        self.stock = stock

    def start_session(
        self, operator: UserSession, location_id: Optional[int] = None
    ) -> int:
        self.auth.require(operator, "inventory.count")
        row = self.db.fetchone("SELECT COUNT(*) AS c FROM inventory_sessions")
        session_no = next_code("INV", int(row["c"]) + 1)
        cur = self.db.execute(
            """
            INSERT INTO inventory_sessions(
                session_no, location_id, operator_id, status, adjustments_posted, created_at
            ) VALUES (?, ?, ?, 'open', 0, ?)
            """,
            (session_no, location_id, operator.id, now_iso()),
        )
        sid = int(cur.lastrowid)
        self.audit.log(operator.id, "inventory.start", "inventory_sessions", sid, None)
        return sid

    def add_line(
        self,
        operator: UserSession,
        session_id: int,
        container_id: int,
        counted_qty: float,
        remark: str = "",
    ) -> int:
        self.auth.require(operator, "inventory.count")
        counted_qty = _validate_quantity(counted_qty, allow_zero=True)
        session = self.db.fetchone(
            "SELECT * FROM inventory_sessions WHERE id=?", (session_id,)
        )
        if not session:
            raise ValidationError("盘点会话不存在")
        if session["status"] != "open":
            raise ValidationError("仅开放中的盘点会话可录入实盘")
        ctr = self.db.fetchone("SELECT * FROM containers WHERE id=?", (container_id,))
        if not ctr:
            raise ValidationError("容器不存在")
        book = float(ctr["quantity"])
        version = int(ctr["qty_version"] or 0)
        diff = counted_qty - book
        try:
            cur = self.db.execute(
                """
                INSERT INTO inventory_lines(
                    session_id, container_id, book_qty, book_qty_version,
                    counted_qty, difference, remark
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, container_id, book, version, counted_qty, diff, remark),
            )
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(f"无法添加盘点行（可能重复）: {exc}") from exc
        return int(cur.lastrowid)

    def _is_controlled_container(self, container_id: int) -> bool:
        row = self.db.fetchone(
            """
            SELECT ch.controlled_flags
            FROM containers c
            JOIN chemicals ch ON ch.id = c.chemical_id
            WHERE c.id=?
            """,
            (container_id,),
        )
        if not row:
            raise ValidationError("容器不存在")
        return bool((row["controlled_flags"] or "").strip())

    def close_session(
        self,
        operator: UserSession,
        session_id: int,
        post_adjustments: bool = True,
        reviewer: Optional[UserSession] = None,
    ) -> list:
        """Close session once; settle against live stock; dual-control when needed."""
        self.auth.require(operator, "inventory.count")

        session = self.db.fetchone(
            "SELECT * FROM inventory_sessions WHERE id=?", (session_id,)
        )
        if not session:
            raise ValidationError("盘点会话不存在")
        if session["status"] == "closed" or int(session["adjustments_posted"] or 0) == 1:
            raise StockError("盘点会话已关闭或已过账，禁止重复关闭/重复调整")
        if session["status"] != "open":
            raise ValidationError(f"盘点会话状态不可关闭: {session['status']}")

        lines = self.db.fetchall(
            "SELECT * FROM inventory_lines WHERE session_id=?", (session_id,)
        )

        # Precompute settlement and whether dual control is required before any posting.
        plans = []
        needs_dual = False
        for line in lines:
            ctr = self.db.fetchone(
                "SELECT * FROM containers WHERE id=?", (line["container_id"],)
            )
            if not ctr:
                raise ValidationError(f"容器 {line['container_id']} 不存在")
            live_book = float(ctr["quantity"])
            live_version = int(ctr["qty_version"] or 0)
            counted = float(line["counted_qty"])
            settle_diff = counted - live_book
            controlled = self._is_controlled_container(int(line["container_id"]))
            if post_adjustments and abs(settle_diff) > 1e-9 and controlled:
                needs_dual = True
            plans.append(
                {
                    "line": line,
                    "live_book": live_book,
                    "live_version": live_version,
                    "settle_diff": settle_diff,
                    "controlled": controlled,
                }
            )

        if needs_dual:
            if reviewer is None:
                raise StockError(
                    "盘点差异涉及管制/特殊化学品，关闭并调整时必须提供独立复核账户"
                )
            if reviewer.id == operator.id:
                raise StockError("双人复核账户必须相互独立")
            self.auth.require(reviewer, "stock.dual_review")

        # Mark closing to reduce duplicate close races
        marked = self.db.execute(
            """
            UPDATE inventory_sessions SET status='closing'
            WHERE id=? AND status='open' AND adjustments_posted=0
            """,
            (session_id,),
        )
        if marked.rowcount != 1:
            raise StockError("盘点关闭失败：会话状态已被并发修改或已关闭")

        adjustments: list[int] = []
        settled_rows = []
        try:
            for plan in plans:
                line = plan["line"]
                self.db.execute(
                    """
                    UPDATE inventory_lines
                    SET settle_book_qty=?, settle_difference=?
                    WHERE id=?
                    """,
                    (plan["live_book"], plan["settle_diff"], line["id"]),
                )
                tx_id = None
                if post_adjustments and abs(plan["settle_diff"]) > 1e-9:
                    tx_type = "adjust_pos" if plan["settle_diff"] > 0 else "adjust_neg"
                    tx_id = self.stock.post_transaction(
                        operator=operator,
                        tx_type=tx_type,
                        container_id=int(line["container_id"]),
                        quantity=abs(plan["settle_diff"]),
                        remark=f"盘点差异调整 session={session_id}",
                        reviewer=reviewer if plan["controlled"] else None,
                        allow_during_inventory=True,
                        expected_qty_version=plan["live_version"],
                    )
                    adjustments.append(tx_id)
                    self.db.execute(
                        "UPDATE inventory_lines SET adjustment_tx_id=? WHERE id=?",
                        (tx_id, line["id"]),
                    )
                settled_rows.append(
                    {
                        **dict(line),
                        "settle_book_qty": plan["live_book"],
                        "settle_difference": plan["settle_diff"],
                        "adjustment_tx_id": tx_id,
                    }
                )

            updated = self.db.execute(
                """
                UPDATE inventory_sessions
                SET status='closed', closed_at=?, adjustments_posted=?
                WHERE id=? AND status='closing' AND adjustments_posted=0
                """,
                (now_iso(), 1 if post_adjustments else 0, session_id),
            )
            if updated.rowcount != 1:
                raise StockError("盘点关闭失败：会话状态已被并发修改或已关闭")
        except Exception:
            # Best-effort reopen if close aborted before final mark.
            self.db.execute(
                """
                UPDATE inventory_sessions SET status='open'
                WHERE id=? AND status='closing' AND adjustments_posted=0
                """,
                (session_id,),
            )
            raise

        self.audit.log(
            operator.id,
            "inventory.close",
            "inventory_sessions",
            session_id,
            {"adjustments": adjustments, "post_adjustments": post_adjustments},
        )
        return settled_rows

    def variance_report(self, session_id: int) -> list:
        return self.db.fetchall(
            """
            SELECT l.*, c.container_code, ch.name AS chemical_name
            FROM inventory_lines l
            JOIN containers c ON c.id = l.container_id
            JOIN chemicals ch ON ch.id = c.chemical_id
            WHERE l.session_id=?
            ORDER BY ABS(COALESCE(l.settle_difference, l.difference)) DESC
            """,
            (session_id,),
        )
