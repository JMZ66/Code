from __future__ import annotations

import math
from typing import Optional

from chem_wh.db.database import Database
from chem_wh.services.audit import AuditService
from chem_wh.services.auth import AuthService, UserSession
from chem_wh.services.exceptions import StockError, ValidationError
from chem_wh.utils.codes import next_code
from chem_wh.utils.integrity import GENESIS_HASH, chain_hash
from chem_wh.utils.timeutil import now_iso

TX_EFFECTS = {
    "inbound": +1,
    "issue": -1,
    "return": +1,
    "transfer": 0,
    "dispose": -1,
    "adjust_pos": +1,
    "adjust_neg": -1,
    "reversal": 0,  # sign derived from related tx
}

# Any quantity/location changing op on controlled chemicals requires dual control.
DUAL_CONTROL_TX_TYPES = {
    "issue",
    "dispose",
    "transfer",
    "adjust_pos",
    "adjust_neg",
    "reversal",
    "return",  # controlled return also dual-controlled for完整流向
}

ALLOWED_STATUS_TRANSITIONS = {
    "in_stock": {"in_stock", "issued", "disposed", "empty"},
    "issued": {"issued", "in_stock", "disposed", "empty"},
    "empty": {"empty", "in_stock", "disposed"},
    "disposed": {"disposed"},
}


def _validate_quantity(quantity: float, *, allow_zero: bool = False) -> float:
    if isinstance(quantity, bool) or not isinstance(quantity, (int, float)):
        raise ValidationError("数量必须为数值")
    q = float(quantity)
    if math.isnan(q) or math.isinf(q):
        raise ValidationError("数量不能为 NaN 或无穷大")
    if q < 0:
        raise ValidationError("数量不能为负")
    if not allow_zero and q == 0:
        raise ValidationError("数量必须大于 0")
    return q


class StockService:
    def __init__(self, db: Database, auth: AuthService, audit: AuditService):
        self.db = db
        self.auth = auth
        self.audit = audit

    def _next_tx_no(self, conn) -> str:
        row = conn.execute("SELECT COUNT(*) AS c FROM stock_transactions").fetchone()
        return next_code("TX", int(row["c"]) + 1)

    def _is_controlled(self, chemical_id: int, conn=None) -> bool:
        c = conn or self.db.conn
        row = c.execute(
            "SELECT controlled_flags FROM chemicals WHERE id=?", (chemical_id,)
        ).fetchone()
        if not row:
            raise ValidationError("化学品不存在")
        flags = (row["controlled_flags"] or "").strip()
        return bool(flags)

    def _container(self, container_id: int, conn=None):
        c = conn or self.db.conn
        row = c.execute(
            "SELECT * FROM containers WHERE id=?", (container_id,)
        ).fetchone()
        if not row:
            raise ValidationError("容器不存在")
        return row

    def _open_inventory_blocks(self, container_id: int, conn) -> None:
        row = conn.execute(
            """
            SELECT s.session_no FROM inventory_lines l
            JOIN inventory_sessions s ON s.id = l.session_id
            WHERE l.container_id=? AND s.status IN ('open','closing')
            LIMIT 1
            """,
            (container_id,),
        ).fetchone()
        if row:
            raise StockError(
                f"容器处于未关闭盘点会话 {row['session_no']}，禁止直接变更库存；"
                "请先完成或取消盘点结算"
            )

    def _last_tx_hash(self, conn) -> str:
        row = conn.execute(
            "SELECT content_hash FROM stock_transactions "
            "WHERE content_hash IS NOT NULL AND content_hash <> '' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row or not row[0]:
            return GENESIS_HASH
        return row[0]

    def _ensure_dual(
        self,
        *,
        chemical_id: int,
        tx_type: str,
        operator: UserSession,
        reviewer: Optional[UserSession],
        conn,
    ) -> bool:
        controlled = self._is_controlled(chemical_id, conn)
        dual_required = controlled and tx_type in DUAL_CONTROL_TX_TYPES
        if not dual_required:
            return False
        if reviewer is None:
            raise StockError(
                "管制/特殊化学品的领用、归还、调拨、处置、库存调整、冲正与盘点差异调整"
                "均需双人复核，不可绕过"
            )
        if reviewer.id == operator.id:
            raise StockError("双人复核账户必须相互独立")
        if reviewer.username == operator.username:
            raise StockError("禁止使用共享账户代替双人复核")
        self.auth.require(reviewer, "stock.dual_review")
        return True

    def _apply_status(
        self, current: str, tx_type: str, qty_after: float, to_location_id
    ) -> str:
        if current == "disposed" and tx_type != "reversal":
            raise StockError("已处置容器不可再出入库（请使用冲正）")
        new_status = current
        if tx_type == "inbound":
            new_status = "in_stock"
        elif tx_type == "issue":
            new_status = "issued" if qty_after == 0 else "in_stock"
        elif tx_type == "return":
            new_status = "in_stock"
        elif tx_type == "transfer":
            new_status = "in_stock"
        elif tx_type == "dispose":
            new_status = "disposed" if qty_after == 0 else current
        elif tx_type in {"adjust_neg", "adjust_pos", "reversal"}:
            if qty_after == 0:
                new_status = "empty" if current != "disposed" else "disposed"
            else:
                new_status = "in_stock"
        allowed = ALLOWED_STATUS_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            raise StockError(f"非法状态转换: {current} -> {new_status}")
        return new_status

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
        related_tx_id: Optional[int] = None,
        allow_during_inventory: bool = False,
        expected_qty_version: Optional[int] = None,
    ) -> int:
        self.auth.require(operator, "stock.write")
        if tx_type not in TX_EFFECTS:
            raise ValidationError(f"无效事务类型: {tx_type}")
        allow_zero = tx_type == "transfer"
        quantity = _validate_quantity(quantity, allow_zero=allow_zero)

        conn = self.db.conn
        try:
            conn.execute("BEGIN IMMEDIATE")
            ctr = self._container(container_id, conn)
            chemical_id = int(ctr["chemical_id"])

            if not allow_during_inventory and tx_type != "transfer":
                # transfers also blocked during inventory for consistency
                pass
            if not allow_during_inventory:
                self._open_inventory_blocks(container_id, conn)

            if expected_qty_version is not None:
                current_ver = int(ctr["qty_version"] or 0)
                if current_ver != expected_qty_version:
                    raise StockError(
                        f"库存版本冲突：期望 version={expected_qty_version}，"
                        f"当前 version={current_ver}（盘点期间库存已变化）"
                    )

            dual_required = self._ensure_dual(
                chemical_id=chemical_id,
                tx_type=tx_type,
                operator=operator,
                reviewer=reviewer,
                conn=conn,
            )

            if tx_type == "transfer":
                if to_location_id is None:
                    raise ValidationError("调拨必须指定目标位置")
                if not human_confirmed_compatibility:
                    raise StockError(
                        "调拨前须由授权人员人工确认储存相容性；"
                        "系统不会自动判定是否可安全混储"
                    )

            if tx_type == "reversal":
                if related_tx_id is None:
                    raise ValidationError("冲正必须指定原事务 related_tx_id")
                orig = conn.execute(
                    "SELECT * FROM stock_transactions WHERE id=?", (related_tx_id,)
                ).fetchone()
                if not orig:
                    raise ValidationError("原事务不存在")
                if int(orig["container_id"]) != container_id:
                    raise ValidationError("冲正容器与原事务不一致")
                # reverse the original delta
                qty_delta = -float(orig["qty_delta"])
                quantity = abs(qty_delta) if qty_delta != 0 else 0.0
            else:
                sign = TX_EFFECTS[tx_type]
                qty_delta = 0.0 if tx_type == "transfer" else sign * quantity

            qty_before = float(ctr["quantity"])
            qty_after = qty_before + qty_delta
            if qty_after < -1e-9:
                raise StockError(
                    f"库存不足：当前 {qty_before}{ctr['unit']}，请求变更 {qty_delta}"
                )
            if qty_after < 0:
                qty_after = 0.0

            new_status = self._apply_status(
                ctr["status"], tx_type, qty_after, to_location_id
            )
            new_location = ctr["location_id"]
            if tx_type in {"inbound", "return"} and to_location_id:
                new_location = to_location_id
            elif tx_type == "transfer":
                new_location = to_location_id

            tx_no = self._next_tx_no(conn)
            created_at = now_iso()
            prev_hash = self._last_tx_hash(conn)
            payload = {
                "tx_no": tx_no,
                "tx_type": tx_type,
                "container_id": container_id,
                "chemical_id": chemical_id,
                "qty_delta": qty_delta,
                "qty_before": qty_before,
                "qty_after": qty_after,
                "unit": ctr["unit"],
                "from_location_id": ctr["location_id"],
                "to_location_id": to_location_id if to_location_id is not None else new_location,
                "operator_id": operator.id,
                "reviewer_id": reviewer.id if reviewer else None,
                "dual_required": 1 if dual_required else 0,
                "related_tx_id": related_tx_id,
                "remark": remark,
                "created_at": created_at,
            }
            content_hash = chain_hash(prev_hash, payload)

            cur = conn.execute(
                """
                INSERT INTO stock_transactions(
                    tx_no, tx_type, container_id, chemical_id,
                    qty_delta, qty_before, qty_after, unit,
                    from_location_id, to_location_id,
                    operator_id, reviewer_id, dual_required, related_tx_id,
                    remark, content_hash, prev_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    related_tx_id,
                    remark,
                    content_hash,
                    prev_hash,
                    created_at,
                ),
            )
            tx_id = int(cur.lastrowid)
            new_version = int(ctr["qty_version"] or 0) + 1
            conn.execute(
                """
                UPDATE containers
                SET quantity=?, location_id=?, status=?, qty_version=?, updated_at=?
                WHERE id=?
                """,
                (qty_after, new_location, new_status, new_version, now_iso(), container_id),
            )
            # Audit in same transaction
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
                    "content_hash": content_hash,
                },
                conn=conn,
                commit=False,
            )
            conn.commit()
            return tx_id
        except Exception:
            conn.rollback()
            raise

    def reverse_transaction(
        self,
        *,
        operator: UserSession,
        tx_id: int,
        reviewer: Optional[UserSession] = None,
        remark: str = "",
    ) -> int:
        """Create an immutable reversal; never delete original."""
        orig = self.db.fetchone(
            "SELECT * FROM stock_transactions WHERE id=?", (tx_id,)
        )
        if not orig:
            raise ValidationError("原事务不存在")
        return self.post_transaction(
            operator=operator,
            tx_type="reversal",
            container_id=int(orig["container_id"]),
            quantity=abs(float(orig["qty_delta"])) or 0.0,
            remark=remark or f"冲正原事务 {orig['tx_no']}",
            reviewer=reviewer,
            related_tx_id=int(orig["id"]),
        )

    def delete_transaction(self, _tx_id: int) -> None:
        raise StockError("禁止删除历史出入库流水；请使用冲正事务纠错")

    def verify_chain(self, limit: int = 10_000) -> tuple[bool, str]:
        rows = self.db.fetchall(
            "SELECT * FROM stock_transactions ORDER BY id ASC LIMIT ?", (limit,)
        )
        prev = GENESIS_HASH
        for row in rows:
            if not row["content_hash"]:
                continue
            payload = {
                "tx_no": row["tx_no"],
                "tx_type": row["tx_type"],
                "container_id": row["container_id"],
                "chemical_id": row["chemical_id"],
                "qty_delta": row["qty_delta"],
                "qty_before": row["qty_before"],
                "qty_after": row["qty_after"],
                "unit": row["unit"],
                "from_location_id": row["from_location_id"],
                "to_location_id": row["to_location_id"],
                "operator_id": row["operator_id"],
                "reviewer_id": row["reviewer_id"],
                "dual_required": row["dual_required"],
                "related_tx_id": row["related_tx_id"],
                "remark": row["remark"],
                "created_at": row["created_at"],
            }
            expected = chain_hash(prev, payload)
            if row["prev_hash"] and row["prev_hash"] != prev:
                return False, f"tx id={row['id']} prev_hash mismatch"
            if row["content_hash"] != expected:
                return False, f"tx id={row['id']} content_hash mismatch"
            prev = row["content_hash"]
        return True, "ok"

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
