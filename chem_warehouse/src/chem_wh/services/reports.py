from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from openpyxl import Workbook
from reportlab.graphics.barcode import code128, qr
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from chem_wh.constants import DISCLAIMER, STATUS_LABELS, TX_TYPE_LABELS
from chem_wh.db.database import Database
from chem_wh.services.auth import AuthService, UserSession
from chem_wh.services.exceptions import ValidationError
from chem_wh.utils.resources import font_path
from chem_wh.utils.timeutil import format_local, now_iso

FONT_NAME = "WHChinese"
_FONT_READY = False


def register_chinese_font() -> str:
    global _FONT_READY
    if not _FONT_READY:
        pdfmetrics.registerFont(TTFont(FONT_NAME, str(font_path())))
        _FONT_READY = True
    return FONT_NAME


class ReportService:
    def __init__(self, db: Database, auth: AuthService):
        self.db = db
        self.auth = auth

    def _require(self, operator: UserSession) -> None:
        self.auth.require(operator, "report.read")

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

    def _tx_rows(self, limit: int = 5000) -> list:
        return self.db.fetchall(
            """
            SELECT t.*, c.container_code, ch.name AS chemical_name,
                   u.display_name AS operator_name,
                   ru.display_name AS reviewer_name
            FROM stock_transactions t
            JOIN containers c ON c.id = t.container_id
            JOIN chemicals ch ON ch.id = t.chemical_id
            JOIN users u ON u.id = t.operator_id
            LEFT JOIN users ru ON ru.id = t.reviewer_id
            ORDER BY t.id DESC
            LIMIT ?
            """,
            (limit,),
        )

    def _controlled_rows(self) -> list:
        return self.db.fetchall(
            """
            SELECT ch.name, ch.cas_no, ch.controlled_flags,
                   (
                       SELECT group_concat(cat.name, '、')
                       FROM chemical_controlled cc
                       JOIN controlled_categories cat ON cat.id = cc.category_id
                       WHERE cc.chemical_id = ch.id AND cat.is_active = 1
                   ) AS controlled_names,
                   c.container_code, c.quantity, c.unit, c.status, c.expiry_date, c.batch_no,
                   l.name AS location_name
            FROM chemicals ch
            LEFT JOIN containers c ON c.chemical_id = ch.id
            LEFT JOIN locations l ON l.id = c.location_id
            WHERE TRIM(COALESCE(ch.controlled_flags, '')) <> ''
               OR EXISTS (
                    SELECT 1 FROM chemical_controlled cc
                    JOIN controlled_categories cat ON cat.id = cc.category_id
                    WHERE cc.chemical_id = ch.id AND cat.is_active = 1
               )
            ORDER BY ch.name, c.container_code
            """
        )

    def _label_rows(self, container_ids: list[int]) -> list:
        if not container_ids:
            raise ValidationError("请选择要打印的瓶子")
        marks = ",".join("?" for _ in container_ids)
        return self.db.fetchall(
            f"""
            SELECT c.*, ch.name AS chemical_name, ch.cas_no, ch.controlled_flags,
                   l.name AS location_name,
                   (
                       SELECT group_concat(cat.name, '、')
                       FROM chemical_controlled cc
                       JOIN controlled_categories cat ON cat.id = cc.category_id
                       WHERE cc.chemical_id = ch.id AND cat.is_active = 1
                   ) AS controlled_names
            FROM containers c
            JOIN chemicals ch ON ch.id = c.chemical_id
            LEFT JOIN locations l ON l.id = c.location_id
            WHERE c.id IN ({marks})
            ORDER BY c.container_code
            """,
            tuple(container_ids),
        )

    def export_stock_excel(self, operator: UserSession, path: str | Path) -> Path:
        self._require(operator)
        rows = [
            [
                r["name"],
                r["cas_no"],
                r["concentration"],
                r["specification"],
                r["bottle_count"],
                r["stock_qty"],
                r["unit"],
            ]
            for r in self.stock_summary()
        ]
        return _xlsx(
            path,
            "库存汇总",
            ["名称", "CAS", "浓度", "规格", "瓶数", "在库数量", "单位"],
            rows,
        )

    def export_stock_pdf(self, operator: UserSession, path: str | Path) -> Path:
        self._require(operator)
        rows = [
            [
                r["name"],
                r["cas_no"] or "",
                r["concentration"] or "",
                r["bottle_count"],
                r["stock_qty"] or 0,
                r["unit"],
            ]
            for r in self.stock_summary()
        ]
        return _pdf(
            path,
            "库存汇总",
            ["名称", "CAS", "浓度", "瓶数", "在库数量", "单位"],
            rows,
            operator.display_name,
        )

    def export_transactions_excel(self, operator: UserSession, path: str | Path) -> Path:
        self._require(operator)
        return _xlsx(path, "出入库流水", _TX_HEADERS, self._tx_matrix())

    def export_transactions_pdf(self, operator: UserSession, path: str | Path) -> Path:
        self._require(operator)
        return _pdf(path, "出入库流水", _TX_HEADERS, self._tx_matrix(), operator.display_name)

    def _tx_matrix(self) -> list[list]:
        rows = []
        for r in self._tx_rows():
            rows.append(
                [
                    r["tx_no"],
                    TX_TYPE_LABELS.get(r["tx_type"], r["tx_type"]),
                    r["container_code"],
                    r["chemical_name"],
                    r["qty_delta"],
                    r["qty_after"],
                    r["operator_name"],
                    r["reviewer_name"] or "",
                    format_local(r["created_at"]),
                    r["remark"] or "",
                ]
            )
        return rows

    def export_expiry_excel(self, operator: UserSession, path: str | Path) -> Path:
        self._require(operator)
        return _xlsx(path, "效期清单", _EXP_HEADERS, self._expiry_matrix())

    def export_expiry_pdf(self, operator: UserSession, path: str | Path) -> Path:
        self._require(operator)
        return _pdf(path, "效期清单", _EXP_HEADERS, self._expiry_matrix(), operator.display_name)

    def _expiry_matrix(self) -> list[list]:
        from chem_wh.services.alerts import AlertService

        alerts = AlertService(self.db)
        rows = []
        for kind, items in (("已过期", alerts.expired_containers()), ("即将到期", alerts.expiring_containers())):
            for item in items:
                rows.append(
                    [
                        kind,
                        item["name"],
                        item["container_code"],
                        item["expiry_date"],
                        item["quantity"],
                        item["unit"],
                    ]
                )
        return rows

    def export_controlled_excel(self, operator: UserSession, path: str | Path) -> Path:
        self._require(operator)
        return _xlsx(path, "管制品台账", _CTRL_HEADERS, self._controlled_matrix())

    def export_controlled_pdf(self, operator: UserSession, path: str | Path) -> Path:
        self._require(operator)
        return _pdf(
            path, "管制化学品台账", _CTRL_HEADERS, self._controlled_matrix(), operator.display_name
        )

    def _controlled_matrix(self) -> list[list]:
        rows = []
        for r in self._controlled_rows():
            flags = "、".join(
                part
                for part in [r["controlled_names"] or "", r["controlled_flags"] or ""]
                if part
            )
            rows.append(
                [
                    r["name"],
                    r["cas_no"] or "",
                    flags,
                    r["container_code"] or "",
                    r["batch_no"] or "",
                    r["quantity"] if r["quantity"] is not None else "",
                    r["unit"] or "",
                    STATUS_LABELS.get(r["status"], r["status"] or ""),
                    r["location_name"] or "",
                    r["expiry_date"] or "",
                ]
            )
        return rows

    def export_stocktake_excel(
        self, operator: UserSession, path: str | Path, session_id: int
    ) -> Path:
        self._require(operator)
        return _xlsx(path, "盘点报告", _COUNT_HEADERS, self._count_matrix(session_id))

    def export_stocktake_pdf(
        self, operator: UserSession, path: str | Path, session_id: int
    ) -> Path:
        self._require(operator)
        session = self.db.fetchone(
            "SELECT session_no, status FROM inventory_sessions WHERE id=?", (session_id,)
        )
        title = "盘点报告"
        if session:
            title = f"盘点报告 {session['session_no']}"
        return _pdf(path, title, _COUNT_HEADERS, self._count_matrix(session_id), operator.display_name)

    def _count_matrix(self, session_id: int) -> list[list]:
        rows = self.db.fetchall(
            """
            SELECT l.*, c.container_code, ch.name AS chemical_name
            FROM inventory_lines l
            JOIN containers c ON c.id = l.container_id
            JOIN chemicals ch ON ch.id = c.chemical_id
            WHERE l.session_id=?
            ORDER BY c.container_code
            """,
            (session_id,),
        )
        if not rows:
            raise ValidationError("盘点会话不存在或没有明细")
        matrix = []
        for r in rows:
            diff = r["settle_difference"] if r["settle_difference"] is not None else r["difference"]
            matrix.append(
                [
                    r["container_code"],
                    r["chemical_name"],
                    r["book_qty"],
                    r["counted_qty"],
                    diff,
                    r["remark"] or "",
                ]
            )
        return matrix

    def export_labels_pdf(
        self, operator: UserSession, path: str | Path, container_ids: list[int]
    ) -> Path:
        self._require(operator)
        rows = self._label_rows(container_ids)
        if not rows:
            raise ValidationError("没有可打印的瓶子")
        font = register_chinese_font()
        out = Path(path)
        from reportlab.pdfgen import canvas as pdfcanvas

        pdf = pdfcanvas.Canvas(str(out), pagesize=A4)
        width, height = A4
        cols, rows_n = 2, 4
        cell_w = width / cols
        cell_h = (height - 28) / rows_n
        for index, row in enumerate(rows):
            if index > 0 and index % (cols * rows_n) == 0:
                pdf.showPage()
            pos = index % (cols * rows_n)
            col = pos % cols
            line = pos // cols
            x = col * cell_w + 10
            y = height - (line + 1) * cell_h + 8
            _draw_label(pdf, font, x, y, cell_w - 20, cell_h - 16, row)
        pdf.save()
        return out

    def import_chemicals_excel(self, rows: list[dict]) -> int:
        """Low-level import helper. Callers must already have checked permission."""
        count = 0
        for r in rows:
            name = (r.get("name") or "").strip()
            if not name:
                continue
            ts = now_iso()
            self.db.execute(
                """
                INSERT INTO chemicals(
                    name, cas_no, concentration, specification, manufacturer,
                    hazard_review_status, controlled_flags, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'draft', '', '', ?, ?)
                """,
                (
                    name,
                    str(r.get("cas_no") or ""),
                    str(r.get("concentration") or ""),
                    str(r.get("specification") or ""),
                    str(r.get("manufacturer") or ""),
                    ts,
                    ts,
                ),
            )
            count += 1
        return count


_TX_HEADERS = ["单号", "类型", "容器", "品名", "变动", "结余", "操作人", "复核人", "时间", "备注"]
_EXP_HEADERS = ["类型", "品名", "容器", "有效期", "数量", "单位"]
_CTRL_HEADERS = ["品名", "CAS", "管制类别", "容器", "批号", "数量", "单位", "状态", "库位", "有效期"]
_COUNT_HEADERS = ["容器", "品名", "账面", "实盘", "差异", "备注"]


def _xlsx(path: str | Path, title: str, headers: list[str], rows: list[list]) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append(headers)
    for row in rows:
        ws.append(list(row))
    ws.append([])
    ws.append([DISCLAIMER])
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def _pdf(
    path: str | Path,
    title: str,
    headers: list[str],
    rows: list[list],
    operator_name: str,
) -> Path:
    font = register_chinese_font()
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=28,
        rightMargin=28,
        topMargin=36,
        bottomMargin=36,
    )
    body = ParagraphStyle("cn", fontName=font, fontSize=8, leading=11)
    title_style = ParagraphStyle("title", fontName=font, fontSize=16, leading=20)
    small = ParagraphStyle("small", fontName=font, fontSize=8, leading=11, textColor=colors.HexColor("#333333"))
    story = [
        Paragraph(escape(title), title_style),
        Spacer(1, 6),
        Paragraph(
            escape(f"生成时间：{format_local(now_iso())}    操作人：{operator_name}"),
            small,
        ),
        Paragraph(escape(DISCLAIMER), small),
        Spacer(1, 8),
    ]
    head = [Paragraph(escape(h), body) for h in headers]
    matrix = [head]
    if not rows:
        matrix.append([Paragraph("（无数据）", body)] + [Paragraph("", body) for _ in headers[1:]])
    for row in rows:
        matrix.append([Paragraph(escape("" if v is None else str(v)), body) for v in row])
    table = Table(matrix, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f5f74")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#b7c9cf")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(table)

    def footer(pdf, doc_):
        pdf.saveState()
        pdf.setFont(font, 8)
        pdf.drawString(28, 18, "本报表不能替代危险化学品法定安全管理记录")
        pdf.drawRightString(A4[0] - 28, 18, f"第 {doc_.page} 页")
        pdf.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out


def _draw_label(pdf, font: str, x: float, y: float, w: float, h: float, row) -> None:
    pdf.setStrokeColor(colors.HexColor("#1f5f74"))
    pdf.rect(x, y, w, h, stroke=1, fill=0)
    payload = row["qr_payload"]
    widget = qr.QrCodeWidget(payload)
    bounds = widget.getBounds()
    size = 22 * mm
    bw = bounds[2] - bounds[0]
    bh = bounds[3] - bounds[1]
    drawing = Drawing(size, size, transform=[size / bw, 0, 0, size / bh, 0, 0])
    drawing.add(widget)
    renderPDF.draw(drawing, pdf, x + 4, y + 8)
    text_x = x + size + 8
    pdf.setFillColor(colors.black)
    pdf.setFont(font, 9)
    name = str(row["chemical_name"])[:18]
    pdf.drawString(text_x, y + h - 16, name)
    pdf.setFont(font, 8)
    lines = [
        f"编号 {row['container_code']}",
        f"CAS {row['cas_no'] or '-'}",
        f"批号 {row['batch_no'] or '-'}  到期 {row['expiry_date'] or '-'}",
        f"库位 {row['location_name'] or '-'}",
    ]
    controlled = "、".join(
        part for part in [row["controlled_names"] or "", row["controlled_flags"] or ""] if part
    )
    if controlled:
        lines.append(f"管制 {controlled[:24]}")
    yy = y + h - 30
    for line in lines:
        pdf.drawString(text_x, yy, line)
        yy -= 11
    bar_value = str(row["container_code"])
    bar = code128.Code128(bar_value, barHeight=10 * mm, barWidth=0.7)
    bar.drawOn(pdf, x + 4, y + 4)
