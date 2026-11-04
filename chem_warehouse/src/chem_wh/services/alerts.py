from __future__ import annotations

from datetime import datetime, timedelta

from chem_wh.db.database import Database
from chem_wh.utils.timeutil import today_local


class AlertService:
    def __init__(self, db: Database):
        self.db = db

    def warn_days(self) -> int:
        row = self.db.fetchone(
            "SELECT value FROM app_settings WHERE key='expiry_warn_days'"
        )
        if not row:
            return 30
        try:
            days = int(row["value"])
        except (TypeError, ValueError):
            return 30
        return min(max(days, 1), 3650)

    def _today(self) -> str:
        return today_local()

    def _sum_qty(self, chemical_id: int, unit: str, location_id: int | None) -> float:
        if location_id is None:
            row = self.db.fetchone(
                """
                SELECT COALESCE(SUM(quantity), 0) AS q
                FROM containers
                WHERE chemical_id=? AND status='in_stock' AND unit=?
                """,
                (chemical_id, unit),
            )
        else:
            row = self.db.fetchone(
                """
                WITH RECURSIVE tree(id) AS (
                    SELECT id FROM locations WHERE id=?
                    UNION ALL
                    SELECT l.id FROM locations l JOIN tree t ON l.parent_id = t.id
                )
                SELECT COALESCE(SUM(c.quantity), 0) AS q
                FROM containers c
                WHERE c.chemical_id=? AND c.status='in_stock' AND c.unit=?
                  AND c.location_id IN (SELECT id FROM tree)
                """,
                (location_id, chemical_id, unit),
            )
        return float(row["q"] or 0)

    def _location_name(self, location_id: int | None) -> str:
        if location_id is None:
            return "全库"
        row = self.db.fetchone("SELECT name, code FROM locations WHERE id=?", (location_id,))
        if not row:
            return str(location_id)
        return f"{row['name']} ({row['code']})"

    def expired_containers(self) -> list[dict]:
        today = self._today()
        rows = self.db.fetchall(
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
        return [dict(r) for r in rows]

    def expiring_containers(self) -> list[dict]:
        today = datetime.fromisoformat(self._today()).date()
        end = (today + timedelta(days=self.warn_days())).isoformat()
        start = today.isoformat()
        rows = self.db.fetchall(
            """
            SELECT c.container_code, c.expiry_date, c.quantity, c.unit, ch.name
            FROM containers c
            JOIN chemicals ch ON ch.id = c.chemical_id
            WHERE c.expiry_date IS NOT NULL AND c.expiry_date <> ''
              AND c.expiry_date >= ? AND c.expiry_date <= ?
              AND c.status IN ('in_stock','issued')
            ORDER BY c.expiry_date
            """,
            (start, end),
        )
        return [dict(r) for r in rows]

    def _limit_rows(self, kind: str) -> list[dict]:
        limits = self.db.fetchall(
            """
            SELECT sl.*, ch.name, ch.cas_no
            FROM stock_limits sl
            JOIN chemicals ch ON ch.id = sl.chemical_id
            """
        )
        found = []
        for sl in limits:
            total = self._sum_qty(int(sl["chemical_id"]), sl["unit"], sl["location_id"])
            location_name = self._location_name(sl["location_id"])
            if kind == "low" and total < float(sl["min_qty"]):
                found.append(
                    {
                        "name": sl["name"],
                        "cas_no": sl["cas_no"],
                        "total_qty": total,
                        "min_qty": sl["min_qty"],
                        "unit": sl["unit"],
                        "location_name": location_name,
                    }
                )
            if (
                kind == "over"
                and sl["approved_max_qty"] is not None
                and total > float(sl["approved_max_qty"])
            ):
                found.append(
                    {
                        "name": sl["name"],
                        "cas_no": sl["cas_no"],
                        "total_qty": total,
                        "approved_max_qty": sl["approved_max_qty"],
                        "unit": sl["unit"],
                        "location_name": location_name,
                    }
                )
        return found

    def low_stock(self) -> list[dict]:
        return self._limit_rows("low")

    def over_approved_stock(self) -> list[dict]:
        return self._limit_rows("over")

    def missing_sds(self) -> list[dict]:
        rows = self.db.fetchall(
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
        return [dict(r) for r in rows]

    def all_alerts(self) -> dict:
        return {
            "expired": self.expired_containers(),
            "expiring": self.expiring_containers(),
            "low_stock": self.low_stock(),
            "over_stock": self.over_approved_stock(),
            "missing_sds": self.missing_sds(),
        }
