from __future__ import annotations

from typing import Optional

from chem_wh.db.database import Database
from chem_wh.services.audit import AuditService
from chem_wh.services.auth import AuthService, UserSession
from chem_wh.services.exceptions import StockError, ValidationError
from chem_wh.utils.codes import next_code
from chem_wh.utils.timeutil import now_iso

TX_EFFECTS = {
    "inbound": +1,
    "issue": -1,
    "return": +1,
    "transfer": 0,  # location only unless qty change
    "dispose": -1,
    "adjust_pos": +1,
    "adjust_neg": -1,
}


class StockService:
    def __init__(self, db: Database, auth: AuthService, audit: AuditService):
        self.db = db
        self.auth = auth
        self.audit = audit

    def _next_tx_no(self) -> str:
        row = self.db.fetchone("SELECT COUNT(*) AS c FROM stock_transactions")
        return next_code("TX", int(row["c"]) + 1)

    def _is_controlled(self, chemical_id: int) -> bool:
        row = self.db.fetchone(
            "SELECT controlled_flags FROM chemicals WHERE id=?", (chemical_id,)
        )
        if not row:
            raise ValidationError("化学品不存在")
        flags = (row["controlled_flags"] or "").strip()
        return bool(flags)

    def _container(self, container_id: int):
        row = self.db.fetchone("SELECT * FROM containers WHERE id=?", (container_id,))
        if not row:
            raise ValidationError("容器不存在")
        return row

    def post_transaction(
        self,
        *,
        operator: UserSession,
        tx_type: str,
        container_id: int,
        quantity: float,
        remark: str = "",
        to_location_id: Optional[int] = None,
        reviewer: Optional[UserSession] = None,
        human_confirmed_compatibility: bool = False,
    ) -> int:
        self.auth.require(operator, "stock.write")
        if tx_type not in TX_EFFECTS:
            raise ValidationError(f"无效事务类型: {tx_type}")
        if quantity < 0:
            raise ValidationError("数量不能为负")
        if tx_type != "transfer" and quantity == 0:
            raise ValidationError("数量必须大于 0")

        ctr = self._container(container_id)
        chemical_id = int(ctr["chemical_id"])
        dual_required = self._is_controlled(chemical_id) and tx_type in {
            "issue",
            "dispose",
            "transfer",
        }

        if dual_required:
            if reviewer is None:
                raise StockError("管制/特殊化学品该操作需要双人复核")
            if reviewer.id == operator.id:
                raise StockError("双人复核账户必须相互独立")
            self.auth.require(reviewer, "stock.dual_review")

        # Transfer between locations: never auto-judge mix storage.
        if tx_type == "transfer":
            if to_location_id is None:
                raise ValidationError("调拨必须指定目标位置")
            if not human_confirmed_compatibility:
                raise StockError(
                    "调拨前须由授权人员人工确认储存相容性；"
                    "系统不会自动判定是否可安全混储"
                )

        qty_before = float(ctr["quantity"])
        sign = TX_EFFECTS[tx_type]
        if tx_type == "transfer":
            qty_after = qty_before
            qty_delta = 0.0
        else:
            qty_delta = sign * float(quantity)
            qty_after = qty_before + qty_delta
            if qty_after < -1e-9:
                raise StockError(
                    f"库存不足：当前 {qty_before}{ctr['unit']}，请求变更 {qty_delta}"
                )
            if qty_after < 0:
                qty_after = 0.0

        new_status = ctr["status"]
        new_location = ctr["location_id"]
        if tx_type == "inbound":
            new_status = "in_stock"
            if to_location_id:
                new_location = to_location_id
        elif tx_type == "issue":
            new_status = "issued" if qty_after == 0 else "in_stock"
        elif tx_type == "return":
            new_status = "in_stock"
            if to_location_id:
                new_location = to_location_id
        elif tx_type == "transfer":
            new_location = to_location_id
            new_status = "in_stock"
        elif tx_type == "dispose":
            new_status = "disposed" if qty_after == 0 else ctr["status"]
        elif qty_after == 0 and tx_type in {"adjust_neg", "issue"}:
            new_status = "empty"

        tx_no = self._next_tx_no()
        # Single connection transaction
        try:
            self.db.conn.execute("BEGIN")
            cur = self.db.conn.execute(
                """
                INSERT INTO stock_transactions(
                    tx_no, tx_type, container_id, chemical_id,
                    qty_delta, qty_before, qty_after, unit,
                    from_location_id, to_location_id,
                    operator_id, reviewer_id, dual_required, remark, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tx_no,
                    tx_type,
                    container_id,
                    chemical_id,
                    qty_delta,
                    qty_before,
                    qty_after,
                    ctr["unit"],
                    ctr["location_id"],
                    to_location_id if to_location_id is not None else new_location,
                    operator.id,
                    reviewer.id if reviewer else None,
                    1 if dual_required else 0,
                    remark,
                    now_iso(),
                ),
            )
            self.db.conn.execute(
                """
                UPDATE containers
                SET quantity=?, location_id=?, status=?, updated_at=?
                WHERE id=?
                """,
                (qty_after, new_location, new_status, now_iso(), container_id),
            )
            self.db.conn.commit()
        except Exception:
            self.db.conn.rollback()
            raise

        tx_id = int(cur.lastrowid)
        self.audit.log(
            operator.id,
            f"stock.{tx_type}",
            "stock_transactions",
            tx_id,
            {
                "tx_no": tx_no,
                "container_id": container_id,
                "qty_delta": qty_delta,
                "reviewer_id": reviewer.id if reviewer else None,
            },
        )
        return tx_id

    def delete_transaction(self, _tx_id: int) -> None:
        raise StockError("禁止删除历史出入库流水；请使用冲正事务纠错")

    def list_transactions(self, limit: int = 200) -> list:
        return self.db.fetchall(
            """
            SELECT t.*, c.container_code, ch.name AS chemical_name,
                   u.username AS operator_name
            FROM stock_transactions t
            JOIN containers c ON c.id = t.container_id
            JOIN chemicals ch ON ch.id = t.chemical_id
            JOIN users u ON u.id = t.operator_id
            ORDER BY t.id DESC
            LIMIT ?
            """,
            (limit,),
        )

    def monthly_consumption(self, year_month: str) -> list:
        """year_month format YYYY-MM; issue+dispose absolute qty."""
        return self.db.fetchall(
            """
            SELECT ch.name, ch.cas_no, SUM(ABS(t.qty_delta)) AS consumed, t.unit
            FROM stock_transactions t
            JOIN chemicals ch ON ch.id = t.chemical_id
            WHERE t.tx_type IN ('issue','dispose')
              AND substr(t.created_at, 1, 7) = ?
            GROUP BY ch.id, t.unit
            ORDER BY consumed DESC
            """,
            (year_month,),
        )
