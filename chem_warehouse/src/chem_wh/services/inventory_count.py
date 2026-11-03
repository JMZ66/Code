from __future__ import annotations

from typing import Optional

from chem_wh.db.database import Database
from chem_wh.services.audit import AuditService
from chem_wh.services.auth import AuthService, UserSession
from chem_wh.services.exceptions import ValidationError
from chem_wh.services.stock import StockService
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
            INSERT INTO inventory_sessions(session_no, location_id, operator_id, status, created_at)
            VALUES (?, ?, ?, 'open', ?)
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
        session = self.db.fetchone(
            "SELECT * FROM inventory_sessions WHERE id=?", (session_id,)
        )
        if not session or session["status"] != "open":
            raise ValidationError("盘点会话不存在或已关闭")
        ctr = self.db.fetchone("SELECT * FROM containers WHERE id=?", (container_id,))
        if not ctr:
            raise ValidationError("容器不存在")
        book = float(ctr["quantity"])
        diff = counted_qty - book
        cur = self.db.execute(
            """
            INSERT INTO inventory_lines(
                session_id, container_id, book_qty, counted_qty, difference, remark
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, container_id, book, counted_qty, diff, remark),
        )
        return int(cur.lastrowid)

    def close_session(
        self, operator: UserSession, session_id: int, post_adjustments: bool = True
    ) -> list:
        """Close session; optionally post adjust transactions for differences."""
        self.auth.require(operator, "inventory.count")
        lines = self.db.fetchall(
            "SELECT * FROM inventory_lines WHERE session_id=?", (session_id,)
        )
        adjustments = []
        if post_adjustments:
            for line in lines:
                diff = float(line["difference"])
                if abs(diff) < 1e-9:
                    continue
                tx_type = "adjust_pos" if diff > 0 else "adjust_neg"
                tx_id = self.stock.post_transaction(
                    operator=operator,
                    tx_type=tx_type,
                    container_id=int(line["container_id"]),
                    quantity=abs(diff),
                    remark=f"盘点差异调整 session={session_id}",
                )
                adjustments.append(tx_id)
        self.db.execute(
            """
            UPDATE inventory_sessions SET status='closed', closed_at=? WHERE id=?
            """,
            (now_iso(), session_id),
        )
        self.audit.log(
            operator.id,
            "inventory.close",
            "inventory_sessions",
            session_id,
            {"adjustments": adjustments},
        )
        return [dict(x) for x in lines]

    def variance_report(self, session_id: int) -> list:
        return self.db.fetchall(
            """
            SELECT l.*, c.container_code, ch.name AS chemical_name
            FROM inventory_lines l
            JOIN containers c ON c.id = l.container_id
            JOIN chemicals ch ON ch.id = c.chemical_id
            WHERE l.session_id=?
            ORDER BY ABS(l.difference) DESC
            """,
            (session_id,),
        )
