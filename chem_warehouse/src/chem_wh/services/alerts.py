from __future__ import annotations

from datetime import datetime, timezone

from chem_wh.db.database import Database


class AlertService:
    def __init__(self, db: Database):
        self.db = db

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def expired_containers(self) -> list:
        today = self._today()
        return self.db.fetchall(
            """
            SELECT c.container_code, c.expiry_date, c.quantity, c.unit, ch.name
            FROM containers c
            JOIN chemicals ch ON ch.id = c.chemical_id
            WHERE c.expiry_date IS NOT NULL AND c.expiry_date <> ''
              AND c.expiry_date < ?
              AND c.status IN ('in_stock','issued')
            ORDER BY c.expiry_date
            """,
            (today,),
        )

    def low_stock(self) -> list:
        return self.db.fetchall(
            """
            SELECT ch.name, ch.cas_no, SUM(c.quantity) AS total_qty, sl.min_qty, sl.unit
            FROM stock_limits sl
            JOIN chemicals ch ON ch.id = sl.chemical_id
            LEFT JOIN containers c ON c.chemical_id = ch.id AND c.status='in_stock'
            GROUP BY sl.id
            HAVING total_qty IS NULL OR total_qty < sl.min_qty
            """
        )

    def over_approved_stock(self) -> list:
        return self.db.fetchall(
            """
            SELECT ch.name, ch.cas_no, SUM(c.quantity) AS total_qty,
                   sl.approved_max_qty, sl.unit
            FROM stock_limits sl
            JOIN chemicals ch ON ch.id = sl.chemical_id
            LEFT JOIN containers c ON c.chemical_id = ch.id AND c.status='in_stock'
            WHERE sl.approved_max_qty IS NOT NULL
            GROUP BY sl.id
            HAVING total_qty > sl.approved_max_qty
            """
        )

    def missing_sds(self) -> list:
        return self.db.fetchall(
            """
            SELECT ch.id, ch.name, ch.cas_no
            FROM chemicals ch
            WHERE NOT EXISTS (
                SELECT 1 FROM sds_documents s
                WHERE s.chemical_id = ch.id AND s.review_status='approved'
            )
            ORDER BY ch.name
            """
        )

    def all_alerts(self) -> dict:
        return {
            "expired": [dict(r) for r in self.expired_containers()],
            "low_stock": [dict(r) for r in self.low_stock()],
            "over_stock": [dict(r) for r in self.over_approved_stock()],
            "missing_sds": [dict(r) for r in self.missing_sds()],
        }
