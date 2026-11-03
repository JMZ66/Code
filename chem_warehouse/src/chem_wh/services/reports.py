from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from chem_wh.db.database import Database
from chem_wh.services.auth import AuthService, UserSession
from chem_wh.utils.timeutil import now_iso


class ReportService:
    def __init__(self, db: Database, auth: AuthService):
        self.db = db
        self.auth = auth

    def stock_summary(self) -> list:
        return self.db.fetchall(
            """
            SELECT ch.name, ch.cas_no, ch.concentration, ch.specification,
                   COUNT(c.id) AS bottle_count,
                   SUM(CASE WHEN c.status='in_stock' THEN c.quantity ELSE 0 END) AS stock_qty,
                   COALESCE(MAX(c.unit), 'mL') AS unit
            FROM chemicals ch
            LEFT JOIN containers c ON c.chemical_id = ch.id
            GROUP BY ch.id
            ORDER BY ch.name
            """
        )

    def export_stock_excel(self, operator: UserSession, path: str | Path) -> Path:
        self.auth.require(operator, "report.read")
        wb = Workbook()
        ws = wb.active
        ws.title = "库存汇总"
        ws.append(
            ["名称", "CAS", "浓度", "规格", "瓶数", "在库数量", "单位"]
        )
        for row in self.stock_summary():
            ws.append(
                [
                    row["name"],
                    row["cas_no"],
                    row["concentration"],
                    row["specification"],
                    row["bottle_count"],
                    row["stock_qty"],
                    row["unit"],
                ]
            )
        out = Path(path)
        wb.save(out)
        return out

    def export_stock_pdf(self, operator: UserSession, path: str | Path) -> Path:
        self.auth.require(operator, "report.read")
        out = Path(path)
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        c = canvas.Canvas(str(out), pagesize=A4)
        c.setFont("STSong-Light", 14)
        c.drawString(40, 800, "危化品库存汇总报表")
        c.setFont("STSong-Light", 10)
        c.drawString(40, 780, f"生成时间(UTC): {now_iso()}")
        y = 750
        for row in self.stock_summary():
            line = (
                f"{row['name']} | CAS:{row['cas_no'] or '-'} | "
                f"在库:{row['stock_qty'] or 0}{row['unit']} | 瓶数:{row['bottle_count']}"
            )
            c.drawString(40, y, line[:90])
            y -= 16
            if y < 50:
                c.showPage()
                c.setFont("STSong-Light", 10)
                y = 800
        c.save()
        return out

    def import_chemicals_excel(self, rows: list[dict]) -> int:
        """Low-level import helper used by UI; returns inserted count.

        Expected keys: name, cas_no, concentration, specification, manufacturer
        """
        # Kept here for packaging; actual permission-checked import is in app layer.
        count = 0
        from chem_wh.utils.timeutil import now_iso as _now

        for r in rows:
            name = (r.get("name") or "").strip()
            if not name:
                continue
            ts = _now()
            self.db.execute(
                """
                INSERT INTO chemicals(
                    name, cas_no, concentration, specification, manufacturer,
                    hazard_review_status, controlled_flags, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'draft', '', '', ?, ?)
                """,
                (
                    name,
                    r.get("cas_no", ""),
                    r.get("concentration", ""),
                    r.get("specification", ""),
                    r.get("manufacturer", ""),
                    ts,
                    ts,
                ),
            )
            count += 1
        return count
