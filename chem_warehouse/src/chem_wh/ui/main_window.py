from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from openpyxl import load_workbook
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from chem_wh import APP_NAME, __version__
from chem_wh.app_context import AppContext
from chem_wh.services.exceptions import AppError


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        user = ctx.current_user
        assert user is not None
        self.setWindowTitle(f"{APP_NAME} v{__version__} — {user.display_name} ({user.role})")
        self.resize(1180, 760)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        header = QLabel(APP_NAME)
        header.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
        header.setStyleSheet("color: #143844;")
        sub = QLabel(
            "电子台账 · 瓶级追踪 · 出入库事务 · SDS · 预警 · 审计  |  完全离线"
        )
        sub.setStyleSheet("color: #5a6f78;")
        layout.addWidget(header)
        layout.addWidget(sub)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.tabs.addTab(self._build_stock_tab(), "库存容器")
        self.tabs.addTab(self._build_tx_tab(), "出入库")
        self.tabs.addTab(self._build_alert_tab(), "安全预警")
        self.tabs.addTab(self._build_sds_tab(), "SDS / 分类")
        self.tabs.addTab(self._build_stats_tab(), "统计报表")
        self.tabs.addTab(self._build_system_tab(), "系统")

        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f3f6f7; }
            QTabWidget::pane { border: 1px solid #c5d2d7; background: #ffffff; }
            QTabBar::tab { padding: 8px 14px; }
            QTableWidget { gridline-color: #d7e0e4; }
            QPushButton {
                padding: 6px 12px; background: #1f5f74; color: white;
                border: none; border-radius: 3px;
            }
            QPushButton:hover { background: #2a7a94; }
            QLineEdit, QComboBox, QDoubleSpinBox, QTextEdit {
                padding: 4px; border: 1px solid #a9bcc3; border-radius: 3px;
            }
            """
        )
        self.refresh_all()

    # ---- helpers ----
    def _err(self, exc: Exception) -> None:
        QMessageBox.warning(self, "操作失败", str(exc))

    def _info(self, msg: str) -> None:
        QMessageBox.information(self, "提示", msg)

    def _fill_table(self, table: QTableWidget, headers: list[str], rows: list[list]) -> None:
        table.clear()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                table.setItem(i, j, QTableWidgetItem("" if val is None else str(val)))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    # ---- stock tab ----
    def _build_stock_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.scan_edit = QLineEdit()
        self.scan_edit.setPlaceholderText("扫描/输入容器编号或二维码内容后回车定位…")
        self.scan_edit.returnPressed.connect(self._locate_container)
        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self.refresh_containers)
        bar.addWidget(self.scan_edit)
        bar.addWidget(btn_refresh)
        v.addLayout(bar)
        self.container_table = QTableWidget()
        v.addWidget(self.container_table)
        return w

    def refresh_containers(self) -> None:
        rows = []
        for r in self.ctx.chemicals.list_containers():
            rows.append(
                [
                    r["container_code"],
                    r["chemical_name"],
                    r["cas_no"],
                    r["batch_no"],
                    r["expiry_date"],
                    r["quantity"],
                    r["unit"],
                    r["status"],
                    r["location_id"],
                    r["qr_payload"],
                ]
            )
        self._fill_table(
            self.container_table,
            ["容器编号", "名称", "CAS", "批次", "有效期", "数量", "单位", "状态", "位置ID", "二维码"],
            rows,
        )

    def _locate_container(self) -> None:
        code = self.scan_edit.text().strip()
        if not code:
            return
        row = self.ctx.chemicals.find_container_by_code(code)
        if not row:
            self._err(AppError("未找到容器"))
            return
        self._info(
            f"定位成功\n编号: {row['container_code']}\n"
            f"品名: {row['chemical_name']}\n数量: {row['quantity']}{row['unit']}\n"
            f"状态: {row['status']}"
        )
        # highlight
        for i in range(self.container_table.rowCount()):
            item = self.container_table.item(i, 0)
            if item and item.text() == row["container_code"]:
                self.container_table.selectRow(i)
                break

    # ---- transaction tab ----
    def _build_tx_tab(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)

        form_box = QWidget()
        form = QFormLayout(form_box)
        self.tx_code = QLineEdit()
        self.tx_code.setPlaceholderText("容器编号 / 扫码")
        self.tx_type = QComboBox()
        self.tx_type.addItems(["inbound", "issue", "return", "transfer", "dispose"])
        self.tx_qty = QDoubleSpinBox()
        self.tx_qty.setMaximum(1_000_000)
        self.tx_qty.setDecimals(3)
        self.tx_qty.setValue(1)
        self.tx_to_loc = QLineEdit()
        self.tx_to_loc.setPlaceholderText("目标位置 ID（调拨/入库可选）")
        self.tx_remark = QLineEdit()
        self.tx_compat = QCheckBox(
            "本人已根据单位制度与 SDS 人工确认储存相容性（系统不做自动混储判定）"
        )
        self.tx_reviewer_user = QLineEdit()
        self.tx_reviewer_user.setPlaceholderText("复核人用户名（管制品）")
        self.tx_reviewer_pass = QLineEdit()
        self.tx_reviewer_pass.setEchoMode(QLineEdit.Password)
        self.tx_reviewer_pass.setPlaceholderText("复核人密码")

        form.addRow("容器", self.tx_code)
        form.addRow("类型", self.tx_type)
        form.addRow("数量", self.tx_qty)
        form.addRow("目标位置", self.tx_to_loc)
        form.addRow("备注", self.tx_remark)
        form.addRow("", self.tx_compat)
        form.addRow("复核账号", self.tx_reviewer_user)
        form.addRow("复核密码", self.tx_reviewer_pass)

        btn = QPushButton("提交事务")
        btn.clicked.connect(self._submit_tx)
        form.addRow(btn)

        note = QLabel(
            "说明：库存变更只通过事务记录；禁止删除流水。\n"
            "管制标识化学品的领用/调拨/处置须双人独立账户复核。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#5a6f78;")
        form.addRow(note)

        right = QVBoxLayout()
        right.addWidget(QLabel("最近出入库流水"))
        self.tx_table = QTableWidget()
        right.addWidget(self.tx_table)
        btn_ref = QPushButton("刷新流水")
        btn_ref.clicked.connect(self.refresh_transactions)
        right.addWidget(btn_ref)

        layout.addWidget(form_box, 2)
        rw = QWidget()
        rw.setLayout(right)
        layout.addWidget(rw, 3)
        return w

    def _submit_tx(self) -> None:
        assert self.ctx.current_user is not None
        try:
            code = self.tx_code.text().strip()
            ctr = self.ctx.chemicals.find_container_by_code(code)
            if not ctr:
                raise AppError("容器不存在")
            reviewer = None
            ru = self.tx_reviewer_user.text().strip()
            if ru:
                reviewer = self.ctx.auth.verify_second_user(
                    self.ctx.current_user,
                    ru,
                    self.tx_reviewer_pass.text(),
                )
            to_loc = self.tx_to_loc.text().strip()
            to_location_id = int(to_loc) if to_loc else None
            tx_id = self.ctx.stock.post_transaction(
                operator=self.ctx.current_user,
                tx_type=self.tx_type.currentText(),
                container_id=int(ctr["id"]),
                quantity=float(self.tx_qty.value()),
                remark=self.tx_remark.text().strip(),
                to_location_id=to_location_id,
                reviewer=reviewer,
                human_confirmed_compatibility=self.tx_compat.isChecked(),
            )
            self._info(f"事务已记账，ID={tx_id}")
            self.refresh_transactions()
            self.refresh_containers()
            self.refresh_alerts()
        except AppError as exc:
            self._err(exc)

    def refresh_transactions(self) -> None:
        rows = []
        for r in self.ctx.stock.list_transactions(100):
            rows.append(
                [
                    r["tx_no"],
                    r["tx_type"],
                    r["container_code"],
                    r["chemical_name"],
                    r["qty_delta"],
                    r["qty_after"],
                    r["operator_name"],
                    r["reviewer_id"],
                    r["created_at"],
                    r["remark"],
                ]
            )
        self._fill_table(
            self.tx_table,
            ["单号", "类型", "容器", "品名", "变动", "结余", "操作人", "复核人ID", "时间", "备注"],
            rows,
        )

    # ---- alerts ----
    def _build_alert_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        btn = QPushButton("刷新预警")
        btn.clicked.connect(self.refresh_alerts)
        v.addWidget(btn)
        self.alert_text = QTextEdit()
        self.alert_text.setReadOnly(True)
        v.addWidget(self.alert_text)
        return w

    def refresh_alerts(self) -> None:
        data = self.ctx.alerts.all_alerts()
        lines = ["=== 安全预警 ===", ""]
        lines.append(f"【过期】{len(data['expired'])} 项")
        for r in data["expired"]:
            lines.append(
                f"  - {r['name']} / {r['container_code']} 到期 {r['expiry_date']}"
            )
        lines.append("")
        lines.append(f"【低库存】{len(data['low_stock'])} 项")
        for r in data["low_stock"]:
            lines.append(
                f"  - {r['name']} 当前 {r['total_qty']} / 最低 {r['min_qty']} {r['unit']}"
            )
        lines.append("")
        lines.append(f"【超核定库存】{len(data['over_stock'])} 项")
        for r in data["over_stock"]:
            lines.append(
                f"  - {r['name']} 当前 {r['total_qty']} / 核定上限 {r['approved_max_qty']} {r['unit']}"
            )
        lines.append("")
        lines.append(f"【缺失已审核 SDS】{len(data['missing_sds'])} 项")
        for r in data["missing_sds"]:
            lines.append(f"  - {r['name']} CAS {r['cas_no']}")
        self.alert_text.setPlainText("\n".join(lines))

    # ---- SDS ----
    def _build_sds_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.sds_table = QTableWidget()
        v.addWidget(self.sds_table)
        btn = QPushButton("刷新 SDS / 危险类别")
        btn.clicked.connect(self.refresh_sds)
        v.addWidget(btn)
        tip = QLabel(
            "危险类别与 SDS 审核状态仅反映人工审核结果；系统不会自动推断混储安全性。"
        )
        tip.setWordWrap(True)
        v.addWidget(tip)
        return w

    def refresh_sds(self) -> None:
        sds = self.ctx.db.fetchall(
            """
            SELECT s.id, ch.name, s.version, s.review_status, s.file_path, s.uploaded_at
            FROM sds_documents s
            JOIN chemicals ch ON ch.id = s.chemical_id
            ORDER BY s.id DESC
            """
        )
        rows = [
            [r["id"], r["name"], r["version"], r["review_status"], r["file_path"], r["uploaded_at"]]
            for r in sds
        ]
        self._fill_table(
            self.sds_table,
            ["ID", "化学品", "版本", "审核状态", "本地路径", "上传时间"],
            rows,
        )

    # ---- stats ----
    def _build_stats_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        btn_sum = QPushButton("刷新库存汇总")
        btn_sum.clicked.connect(self.refresh_summary)
        btn_xlsx = QPushButton("导出 Excel")
        btn_xlsx.clicked.connect(self._export_excel)
        btn_pdf = QPushButton("导出 PDF")
        btn_pdf.clicked.connect(self._export_pdf)
        btn_imp = QPushButton("导入化学品 Excel")
        btn_imp.clicked.connect(self._import_excel)
        btn_month = QPushButton("本月消耗")
        btn_month.clicked.connect(self._show_monthly)
        btn_inv = QPushButton("快速盘点（选中差异冲正）")
        btn_inv.clicked.connect(self._quick_inventory)
        for b in (btn_sum, btn_xlsx, btn_pdf, btn_imp, btn_month, btn_inv):
            bar.addWidget(b)
        v.addLayout(bar)
        self.summary_table = QTableWidget()
        v.addWidget(self.summary_table)
        return w

    def refresh_summary(self) -> None:
        rows = []
        for r in self.ctx.reports.stock_summary():
            rows.append(
                [
                    r["name"],
                    r["cas_no"],
                    r["concentration"],
                    r["specification"],
                    r["bottle_count"],
                    r["stock_qty"],
                    r["unit"],
                ]
            )
        self._fill_table(
            self.summary_table,
            ["名称", "CAS", "浓度", "规格", "瓶数", "在库数量", "单位"],
            rows,
        )

    def _export_excel(self) -> None:
        assert self.ctx.current_user is not None
        path, _ = QFileDialog.getSaveFileName(self, "导出 Excel", "库存汇总.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        try:
            self.ctx.reports.export_stock_excel(self.ctx.current_user, path)
            self._info(f"已导出: {path}")
        except AppError as exc:
            self._err(exc)

    def _export_pdf(self) -> None:
        assert self.ctx.current_user is not None
        path, _ = QFileDialog.getSaveFileName(self, "导出 PDF", "库存汇总.pdf", "PDF (*.pdf)")
        if not path:
            return
        try:
            self.ctx.reports.export_stock_pdf(self.ctx.current_user, path)
            self._info(f"已导出: {path}")
        except AppError as exc:
            self._err(exc)

    def _import_excel(self) -> None:
        assert self.ctx.current_user is not None
        try:
            self.ctx.auth.require(self.ctx.current_user, "chem.write")
        except AppError as exc:
            self._err(exc)
            return
        path, _ = QFileDialog.getOpenFileName(self, "导入 Excel", "", "Excel (*.xlsx)")
        if not path:
            return
        wb = load_workbook(path)
        ws = wb.active
        headers = [str(c.value).strip() if c.value else "" for c in next(ws.iter_rows(min_row=1, max_row=1))]
        mapping = {h: i for i, h in enumerate(headers)}
        required = ["name"]
        if "name" not in mapping and "名称" in mapping:
            mapping["name"] = mapping["名称"]
        for key, cn in [
            ("cas_no", "CAS"),
            ("concentration", "浓度"),
            ("specification", "规格"),
            ("manufacturer", "生产厂家"),
        ]:
            if key not in mapping and cn in mapping:
                mapping[key] = mapping[cn]
        rows = []
        for excel_row in ws.iter_rows(min_row=2, values_only=True):
            if not excel_row or excel_row[mapping.get("name", 0)] is None:
                continue
            rows.append(
                {
                    "name": excel_row[mapping["name"]],
                    "cas_no": excel_row[mapping["cas_no"]] if "cas_no" in mapping else "",
                    "concentration": excel_row[mapping["concentration"]]
                    if "concentration" in mapping
                    else "",
                    "specification": excel_row[mapping["specification"]]
                    if "specification" in mapping
                    else "",
                    "manufacturer": excel_row[mapping["manufacturer"]]
                    if "manufacturer" in mapping
                    else "",
                }
            )
        n = self.ctx.reports.import_chemicals_excel(rows)
        self.ctx.audit.log(
            self.ctx.current_user.id, "chem.import_excel", "chemicals", None, {"count": n}
        )
        self._info(f"已导入 {n} 条化学品（草稿状态，须审核）")
        self.refresh_summary()

    def _show_monthly(self) -> None:
        ym = datetime.now(timezone.utc).strftime("%Y-%m")
        data = self.ctx.stock.monthly_consumption(ym)
        rows = [[r["name"], r["cas_no"], r["consumed"], r["unit"]] for r in data]
        self._fill_table(self.summary_table, ["名称", "CAS", "本月消耗", "单位"], rows)

    def _quick_inventory(self) -> None:
        assert self.ctx.current_user is not None
        try:
            sid = self.ctx.inventory.start_session(self.ctx.current_user)
            containers = self.ctx.chemicals.list_containers(status="in_stock")
            if not containers:
                raise AppError("无在库容器")
            # Demo: ask counted qty for first container only via dialog loop limited
            for ctr in containers[:5]:
                val, ok = QInputDialog.getDouble(
                    self,
                    "盘点录入",
                    f"{ctr['container_code']} {ctr['chemical_name']} 账面 {ctr['quantity']}，实盘数量：",
                    float(ctr["quantity"]),
                    0,
                    1_000_000,
                    3,
                )
                if not ok:
                    continue
                self.ctx.inventory.add_line(
                    self.ctx.current_user, sid, int(ctr["id"]), float(val)
                )
            lines = self.ctx.inventory.close_session(self.ctx.current_user, sid, True)
            self._info(f"盘点会话 {sid} 已关闭，共 {len(lines)} 行，差异已生成调整事务")
            self.refresh_containers()
            self.refresh_transactions()
            variances = self.ctx.inventory.variance_report(sid)
            rows = [
                [
                    r["container_code"],
                    r["chemical_name"],
                    r["book_qty"],
                    r["counted_qty"],
                    r["difference"],
                ]
                for r in variances
            ]
            self._fill_table(
                self.summary_table,
                ["容器", "品名", "账面", "实盘", "差异"],
                rows,
            )
        except AppError as exc:
            self._err(exc)

    # ---- system ----
    def _build_system_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.audit_table = QTableWidget()
        v.addWidget(self.audit_table)
        bar = QHBoxLayout()
        btn_audit = QPushButton("刷新操作日志")
        btn_audit.clicked.connect(self.refresh_audit)
        btn_bak = QPushButton("备份数据库")
        btn_bak.clicked.connect(self._backup)
        btn_res = QPushButton("恢复数据库")
        btn_res.clicked.connect(self._restore)
        bar.addWidget(btn_audit)
        bar.addWidget(btn_bak)
        bar.addWidget(btn_res)
        v.addLayout(bar)
        path_lbl = QLabel(f"数据库路径: {self.ctx.db.path}")
        path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(path_lbl)
        return w

    def refresh_audit(self) -> None:
        rows = []
        for r in self.ctx.audit.list_recent(200):
            rows.append(
                [
                    r["id"],
                    r["user_id"],
                    r["action"],
                    r["entity_type"],
                    r["entity_id"],
                    r["detail_json"],
                    r["created_at"],
                ]
            )
        self._fill_table(
            self.audit_table,
            ["ID", "用户", "动作", "实体", "实体ID", "详情", "时间"],
            rows,
        )

    def _backup(self) -> None:
        assert self.ctx.current_user is not None
        dest = QFileDialog.getExistingDirectory(self, "选择备份目录")
        if not dest:
            return
        try:
            path = self.ctx.backup.backup(self.ctx.current_user, dest)
            self._info(f"备份完成: {path}")
        except AppError as exc:
            self._err(exc)

    def _restore(self) -> None:
        assert self.ctx.current_user is not None
        path, _ = QFileDialog.getOpenFileName(self, "选择备份文件", "", "SQLite (*.db)")
        if not path:
            return
        reply = QMessageBox.question(
            self, "确认恢复", "恢复将覆盖当前数据库，是否继续？"
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self.ctx.backup.restore(self.ctx.current_user, path)
            self._info("恢复完成，请重启应用以加载全部界面状态")
        except AppError as exc:
            self._err(exc)

    def refresh_all(self) -> None:
        self.refresh_containers()
        self.refresh_transactions()
        self.refresh_alerts()
        self.refresh_sds()
        self.refresh_summary()
        self.refresh_audit()
