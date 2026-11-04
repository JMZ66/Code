from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook
from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from chem_wh import APP_NAME, __version__
from chem_wh.app_context import AppContext
from chem_wh.constants import (
    DISCLAIMER,
    SESSION_STATUS_LABELS,
    STATUS_LABELS,
    TX_TYPE_LABELS,
)
from chem_wh.services.auth import ROLE_LABELS
from chem_wh.services.exceptions import AppError
from chem_wh.utils.resources import find_doc
from chem_wh.utils.timeutil import format_local


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        user = self._user()
        mode_name = "演示模式" if ctx.mode == "demo" else "正式模式"
        self.setWindowTitle(
            f"{APP_NAME} v{__version__} — {mode_name} — {user.display_name}（{user.role_label}）"
        )
        self.resize(1200, 780)
        self.tx_key = uuid.uuid4().hex
        self.receive_key = uuid.uuid4().hex
        self.editing_chemical_id: int | None = None
        self.count_session_id: int | None = None
        self.cat_checks: list[tuple[int, QCheckBox]] = []

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        header = QLabel(APP_NAME)
        header.setFont(QFont(self.font().family(), 18, QFont.Weight.Bold))
        layout.addWidget(header)
        self.banner = QLabel(DISCLAIMER)
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(
            "background:#fff4d6;color:#5c4300;padding:8px;border:1px solid #e6d39a;"
        )
        layout.addWidget(self.banner)
        self.demo_banner = QLabel(
            "当前为演示模式，数据库与正式库隔离，禁止用于真实危化品台账。"
        )
        self.demo_banner.setStyleSheet(
            "background:#fde8e8;color:#9b1c1c;padding:6px;font-weight:700;"
        )
        self.demo_banner.setVisible(ctx.mode == "demo")
        layout.addWidget(self.demo_banner)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.tabs.addTab(self._build_home(), "工作台")
        self.tabs.addTab(self._build_chemicals(), "试剂台账")
        self.tabs.addTab(self._build_bottles(), "瓶与标签")
        self.tabs.addTab(self._build_tx(), "出入库")
        self.tabs.addTab(self._build_count(), "盘点")
        self.tabs.addTab(self._build_alerts(), "预警")
        self.tabs.addTab(self._build_sds(), "SDS")
        self.tabs.addTab(self._build_reports(), "报表")
        self.tabs.addTab(self._build_system(), "系统")
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f4f7f8; }
            QTabWidget::pane { border: 1px solid #c5d2d7; background: #ffffff; }
            QTabBar::tab { padding: 8px 14px; }
            QPushButton { padding: 6px 12px; background: #1f5f74; color: white; border: none; }
            QPushButton:disabled { background: #9bb0b8; }
            QLineEdit, QComboBox, QDoubleSpinBox, QDateEdit, QSpinBox {
                padding: 4px; background: white;
            }
            """
        )
        self.statusBar().showMessage(f"{DISCLAIMER}  数据库：{ctx.db.path}")
        self.refresh_all()

    def _user(self):
        assert self.ctx.current_user is not None
        return self.ctx.current_user

    def _err(self, exc: Exception) -> None:
        QMessageBox.warning(self, "操作没有完成", str(exc))

    def _fill(self, table: QTableWidget, headers: list[str], rows: list[list], ids: list | None = None) -> None:
        table.clear()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(rows))
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                item = QTableWidgetItem("" if val is None else str(val))
                if j == 0 and ids is not None:
                    item.setData(Qt.ItemDataRole.UserRole, ids[i])
                table.setItem(i, j, item)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    def _selected_id(self, table: QTableWidget) -> int | None:
        row = table.currentRow()
        if row < 0:
            return None
        item = table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else None

    def _fill_locations(self, combo: QComboBox, *, allow_blank: bool, blank: str = "不变更库位") -> None:
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        if allow_blank:
            combo.addItem(blank, None)
        for loc in self.ctx.chemicals.list_locations():
            combo.addItem(f"{loc['name']}（{loc['code']}）", int(loc["id"]))
        if current is not None:
            index = combo.findData(current)
            if index >= 0:
                combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _fill_chemicals(self, combo: QComboBox) -> None:
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for chem in self.ctx.chemicals.list_chemicals():
            mark = chem["controlled_names"] or chem["controlled_flags"] or ""
            suffix = f" · {mark}" if mark else ""
            combo.addItem(f"{chem['name']}{suffix}", int(chem["id"]))
        if current is not None:
            index = combo.findData(current)
            if index >= 0:
                combo.setCurrentIndex(index)
        combo.blockSignals(False)

    # ---- home ----
    def _build_home(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.scan_edit = QLineEdit()
        self.scan_edit.setPlaceholderText("扫描瓶子上的码，或输入瓶子编号后回车")
        self.scan_edit.returnPressed.connect(self.lookup_scan)
        self.scan_result = QLabel("扫描结果会显示在这里。扫码枪相当于键盘，扫完会自动回车。")
        self.scan_result.setWordWrap(True)
        self.scan_result.setStyleSheet("font-size: 16px; padding: 12px; background: white;")
        self.home_stats = QLabel("")
        self.home_stats.setWordWrap(True)
        v.addWidget(QLabel("查瓶子"))
        v.addWidget(self.scan_edit)
        v.addWidget(self.scan_result)
        v.addWidget(self.home_stats)
        btn = QPushButton("刷新工作台")
        btn.clicked.connect(self.refresh_home)
        manual = QPushButton("打开用户手册")
        manual.clicked.connect(self.open_manual)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addWidget(manual)
        row.addStretch(1)
        v.addLayout(row)
        v.addStretch(1)
        return w

    def lookup_scan(self) -> None:
        code = self.scan_edit.text().strip()
        row = self.ctx.chemicals.find_container_by_code(code) if code else None
        if not row:
            self.scan_result.setText("没有找到这个编号。")
            return
        flags = row["controlled_flags"] or ""
        place = row["location_name"] or "未指定库位"
        self.scan_result.setText(
            f"{row['container_code']}  {row['chemical_name']}\n"
            f"数量 {row['quantity']} {row['unit']}  状态 {STATUS_LABELS.get(row['status'], row['status'])}\n"
            f"库位 {place}  有效期 {row['expiry_date'] or '未填'}  批号 {row['batch_no'] or '-'}\n"
            f"管制标记 {flags or '无'}"
        )
        self.scan_edit.clear()
        self.scan_edit.setFocus()

    def refresh_home(self) -> None:
        bottles = self.ctx.db.fetchone(
            "SELECT COUNT(*) AS c FROM containers WHERE status='in_stock'"
        )
        alerts = self.ctx.alerts.all_alerts()
        self.home_stats.setText(
            f"在库 {int(bottles['c'])} 瓶。"
            f"已过期 {len(alerts['expired'])} 瓶，"
            f"{self.ctx.alerts.warn_days()} 天内到期 {len(alerts['expiring'])} 瓶，"
            f"超储 {len(alerts['over_stock'])} 项，"
            f"低于下限 {len(alerts['low_stock'])} 项，"
            f"缺少已审核 SDS {len(alerts['missing_sds'])} 种。"
        )

    def open_manual(self) -> None:
        path = find_doc("用户手册.pdf", "用户手册.md")
        if path is None:
            self._err(AppError("没有找到用户手册文件"))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    # ---- chemicals ----
    def _build_chemicals(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.chem_search = QLineEdit()
        self.chem_search.setPlaceholderText("按名称、CAS 或管制类别筛选")
        self.chem_search.textChanged.connect(lambda text: self._filter(self.chem_table, text))
        self.chem_table = QTableWidget()
        self.chem_table.itemSelectionChanged.connect(self._load_selected_chemical)
        form = QFormLayout()
        self.chem_name = QLineEdit()
        self.chem_cas = QLineEdit()
        self.chem_conc = QLineEdit()
        self.chem_spec = QLineEdit()
        self.chem_mfr = QLineEdit()
        self.chem_notes = QLineEdit()
        form.addRow("名称", self.chem_name)
        form.addRow("CAS", self.chem_cas)
        form.addRow("浓度", self.chem_conc)
        form.addRow("规格", self.chem_spec)
        form.addRow("生产厂家", self.chem_mfr)
        form.addRow("备注", self.chem_notes)
        self.cat_layout = QVBoxLayout()
        cat_host = QWidget()
        cat_host.setLayout(self.cat_layout)
        form.addRow("管制类别", cat_host)
        self.chem_review_user = QLineEdit()
        self.chem_review_user.setPlaceholderText("取消勾选管制类别时，填写另一名复核人")
        self.chem_review_pass = QLineEdit()
        self.chem_review_pass.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("复核人", self.chem_review_user)
        form.addRow("复核密码", self.chem_review_pass)
        self.chem_status = QLabel("")
        self.chem_status.setWordWrap(True)
        buttons = QHBoxLayout()
        save = QPushButton("保存试剂")
        save.clicked.connect(self.save_chemical)
        clear = QPushButton("清空，改为新建")
        clear.clicked.connect(self.clear_chemical_form)
        buttons.addWidget(save)
        buttons.addWidget(clear)
        v.addWidget(self.chem_search)
        v.addWidget(self.chem_table, 2)
        v.addLayout(form)
        v.addLayout(buttons)
        v.addWidget(self.chem_status)
        return w

    def _reload_category_checks(self) -> None:
        while self.cat_layout.count():
            item = self.cat_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.cat_checks = []
        enabled = self._user().has("user.manage")
        cats = self.ctx.chemicals.list_controlled_categories(active_only=True)
        if not cats:
            hint = QLabel("还没有管制类别。管理员可在「系统」里添加，例如易制毒、易制爆、剧毒。")
            hint.setWordWrap(True)
            self.cat_layout.addWidget(hint)
            return
        for cat in cats:
            box = QCheckBox(f"{cat['name']}（{cat['code']}）")
            box.setEnabled(enabled)
            self.cat_layout.addWidget(box)
            self.cat_checks.append((int(cat["id"]), box))

    def refresh_chemicals(self) -> None:
        rows, ids = [], []
        for chem in self.ctx.chemicals.list_chemicals():
            ids.append(int(chem["id"]))
            rows.append(
                [
                    chem["name"],
                    chem["cas_no"],
                    chem["concentration"],
                    chem["specification"],
                    chem["controlled_names"] or chem["controlled_flags"] or "",
                    chem["manufacturer"],
                ]
            )
        self._fill(self.chem_table, ["名称", "CAS", "浓度", "规格", "管制类别", "厂家"], rows, ids)
        self._filter(self.chem_table, self.chem_search.text())

    def clear_chemical_form(self) -> None:
        self.editing_chemical_id = None
        for widget in (
            self.chem_name,
            self.chem_cas,
            self.chem_conc,
            self.chem_spec,
            self.chem_mfr,
            self.chem_notes,
            self.chem_review_user,
            self.chem_review_pass,
        ):
            widget.clear()
        for _cid, box in self.cat_checks:
            box.setChecked(False)
        self.chem_status.setText("正在新建试剂。")

    def _load_selected_chemical(self) -> None:
        cid = self._selected_id(self.chem_table)
        if cid is None:
            return
        row = self.ctx.db.fetchone("SELECT * FROM chemicals WHERE id=?", (cid,))
        if not row:
            return
        self.editing_chemical_id = cid
        self.chem_name.setText(row["name"] or "")
        self.chem_cas.setText(row["cas_no"] or "")
        self.chem_conc.setText(row["concentration"] or "")
        self.chem_spec.setText(row["specification"] or "")
        self.chem_mfr.setText(row["manufacturer"] or "")
        self.chem_notes.setText(row["notes"] or "")
        selected = set(self.ctx.chemicals.category_ids_for(cid))
        for cat_id, box in self.cat_checks:
            box.setChecked(cat_id in selected)

    def save_chemical(self) -> None:
        user = self._user()
        try:
            fields = dict(
                name=self.chem_name.text(),
                cas_no=self.chem_cas.text(),
                concentration=self.chem_conc.text(),
                specification=self.chem_spec.text(),
                manufacturer=self.chem_mfr.text(),
                notes=self.chem_notes.text(),
            )
            if self.editing_chemical_id:
                self.ctx.chemicals.update_chemical(user, self.editing_chemical_id, **fields)
                cid = self.editing_chemical_id
                verb = "已更新"
            else:
                cid = self.ctx.chemicals.add_chemical(user, **fields)
                self.editing_chemical_id = cid
                verb = "已新建"
            if user.has("user.manage") and self.cat_checks:
                reviewer = self._optional_reviewer(self.chem_review_user, self.chem_review_pass)
                ids = [cat_id for cat_id, box in self.cat_checks if box.isChecked()]
                self.ctx.chemicals.set_chemical_controlled(user, cid, ids, reviewer=reviewer)
            self.chem_status.setText(f"{verb}：{self.chem_name.text().strip()}")
            self.refresh_chemicals()
            self._fill_chemicals(self.bottle_chem)
            self._fill_chemicals(self.limit_chem)
            self._fill_chemicals(self.sds_chem)
            self._fill_chemicals(self.compat_a)
            self._fill_chemicals(self.compat_b)
        except AppError as exc:
            self.chem_status.setText(str(exc))
            self._err(exc)

    # ---- bottles ----
    def _build_bottles(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        form = QFormLayout()
        self.bottle_chem = QComboBox()
        self.bottle_batch = QLineEdit()
        self.bottle_expiry = QDateEdit()
        self.bottle_expiry.setCalendarPopup(True)
        self.bottle_expiry.setDisplayFormat("yyyy-MM-dd")
        self.bottle_expiry.setDate(QDate.currentDate().addYears(2))
        self.bottle_qty = QDoubleSpinBox()
        self.bottle_qty.setRange(0.001, 1_000_000)
        self.bottle_qty.setDecimals(3)
        self.bottle_qty.setValue(1)
        self.bottle_unit = QComboBox()
        self.bottle_unit.setEditable(True)
        self.bottle_unit.addItems(["mL", "L", "g", "kg", "mg", "瓶"])
        self.bottle_loc = QComboBox()
        self.bottle_review_user = QLineEdit()
        self.bottle_review_user.setPlaceholderText("管制试剂入库时必填另一名复核人")
        self.bottle_review_pass = QLineEdit()
        self.bottle_review_pass.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("试剂", self.bottle_chem)
        form.addRow("批号", self.bottle_batch)
        form.addRow("有效期", self.bottle_expiry)
        form.addRow("入库数量", self.bottle_qty)
        form.addRow("单位", self.bottle_unit)
        form.addRow("库位", self.bottle_loc)
        form.addRow("复核人", self.bottle_review_user)
        form.addRow("复核密码", self.bottle_review_pass)
        self.bottle_status = QLabel("一瓶一个编号。数量通过入库流水入账。")
        self.bottle_status.setWordWrap(True)
        buttons = QHBoxLayout()
        receive = QPushButton("建瓶并入库")
        receive.clicked.connect(self.submit_receive)
        label = QPushButton("打印所选瓶子的标签")
        label.clicked.connect(self.print_selected_label)
        buttons.addWidget(receive)
        buttons.addWidget(label)
        self.bottle_search = QLineEdit()
        self.bottle_search.setPlaceholderText("筛选编号、名称或 CAS")
        self.bottle_search.textChanged.connect(lambda text: self._filter(self.bottle_table, text))
        self.bottle_table = QTableWidget()
        v.addLayout(form)
        v.addLayout(buttons)
        v.addWidget(self.bottle_status)
        v.addWidget(self.bottle_search)
        v.addWidget(self.bottle_table, 1)
        return w

    def refresh_bottles(self) -> None:
        self._fill_chemicals(self.bottle_chem)
        self._fill_locations(self.bottle_loc, allow_blank=False, blank="")
        rows, ids = [], []
        for row in self.ctx.chemicals.list_containers():
            ids.append(int(row["id"]))
            rows.append(
                [
                    row["container_code"],
                    row["chemical_name"],
                    row["cas_no"],
                    row["batch_no"],
                    row["expiry_date"],
                    row["quantity"],
                    row["unit"],
                    STATUS_LABELS.get(row["status"], row["status"]),
                    row["location_name"] or "",
                ]
            )
        self._fill(
            self.bottle_table,
            ["编号", "名称", "CAS", "批号", "有效期", "数量", "单位", "状态", "库位"],
            rows,
            ids,
        )
        self._filter(self.bottle_table, self.bottle_search.text())

    def submit_receive(self) -> None:
        user = self._user()
        try:
            if self.bottle_chem.currentData() is None:
                raise AppError("请先在试剂台账中新增试剂")
            reviewer = self._optional_reviewer(self.bottle_review_user, self.bottle_review_pass)
            before = int(self.ctx.db.fetchone("SELECT COUNT(*) AS c FROM containers")["c"])
            result = self.ctx.receive_new_container(
                user,
                chemical_id=int(self.bottle_chem.currentData()),
                batch_no=self.bottle_batch.text().strip(),
                expiry_date=self.bottle_expiry.date().toString("yyyy-MM-dd"),
                quantity=float(self.bottle_qty.value()),
                unit=self.bottle_unit.currentText().strip() or "mL",
                location_id=self.bottle_loc.currentData(),
                remark="入库",
                reviewer=reviewer,
                idempotency_key=self.receive_key,
            )
            after = int(self.ctx.db.fetchone("SELECT COUNT(*) AS c FROM containers")["c"])
            code = self.ctx.db.fetchone(
                "SELECT container_code FROM containers WHERE id=?", (result.container_id,)
            )["container_code"]
            if after == before:
                self.bottle_status.setText(f"该提交已处理，未重复建瓶：{code}")
            else:
                self.bottle_status.setText(f"已入库 {code}。可打印标签后贴到瓶子上。")
                self.receive_key = uuid.uuid4().hex
            self.refresh_bottles()
            self.refresh_transactions()
            self.refresh_home()
        except AppError as exc:
            self.bottle_status.setText(str(exc))
            self._err(exc)

    def print_selected_label(self) -> None:
        cid = self._selected_id(self.bottle_table)
        if cid is None:
            self._err(AppError("请先在表中选中一瓶"))
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存标签 PDF", "瓶标签.pdf", "PDF (*.pdf)")
        if not path:
            return
        try:
            self.ctx.reports.export_labels_pdf(self._user(), path, [cid])
            self.bottle_status.setText(f"标签已生成：{path}")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve())))
        except AppError as exc:
            self._err(exc)

    # ---- transactions ----
    def _build_tx(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)
        form = QFormLayout()
        self.tx_code = QLineEdit()
        self.tx_code.setPlaceholderText("扫描或输入瓶子编号")
        self.tx_type = QComboBox()
        for code, label in (
            ("inbound", "入库"),
            ("issue", "领用"),
            ("return", "归还"),
            ("transfer", "调拨"),
            ("dispose", "处置"),
        ):
            self.tx_type.addItem(label, code)
        self.tx_type.setCurrentIndex(1)
        self.tx_qty = QDoubleSpinBox()
        self.tx_qty.setRange(0, 1_000_000)
        self.tx_qty.setDecimals(3)
        self.tx_qty.setValue(1)
        self.tx_loc = QComboBox()
        self.tx_remark = QLineEdit()
        self.tx_compat = QCheckBox("我已按本单位制度和 SDS 人工确认可以调入目标库位（系统不判断能否混放）")
        self.tx_review_user = QLineEdit()
        self.tx_review_user.setPlaceholderText("管制试剂必填另一名复核人")
        self.tx_review_pass = QLineEdit()
        self.tx_review_pass.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("瓶子", self.tx_code)
        form.addRow("操作", self.tx_type)
        form.addRow("数量", self.tx_qty)
        form.addRow("目标库位", self.tx_loc)
        form.addRow("备注", self.tx_remark)
        form.addRow("", self.tx_compat)
        form.addRow("复核人", self.tx_review_user)
        form.addRow("复核密码", self.tx_review_pass)
        submit = QPushButton("提交")
        submit.clicked.connect(self.submit_tx)
        self.btn_tx = submit
        form.addRow(submit)
        self.tx_status = QLabel(
            "领用按本次实际用量扣减该瓶数量；没用完的数量用「归还」加回。"
            "整瓶拿到另一个柜子，请用「调拨」，不要把数量清零。"
            "已记账的流水不能删除，纠错请联系管理员做冲正。"
        )
        self.tx_status.setWordWrap(True)
        form.addRow(self.tx_status)
        left = QWidget()
        left.setLayout(form)
        right = QVBoxLayout()
        right.addWidget(QLabel("最近流水"))
        self.tx_table = QTableWidget()
        right.addWidget(self.tx_table)
        refresh = QPushButton("刷新流水")
        refresh.clicked.connect(self.refresh_transactions)
        right.addWidget(refresh)
        layout.addWidget(left, 2)
        holder = QWidget()
        holder.setLayout(right)
        layout.addWidget(holder, 3)
        return w

    def submit_tx(self) -> None:
        if not self.btn_tx.isEnabled():
            return
        self.btn_tx.setEnabled(False)
        try:
            user = self._user()
            ctr = self.ctx.chemicals.find_container_by_code(self.tx_code.text())
            if not ctr:
                raise AppError("找不到这瓶试剂，请核对编号或重新扫描")
            reviewer = self._optional_reviewer(self.tx_review_user, self.tx_review_pass)
            before = int(self.ctx.db.fetchone("SELECT COUNT(*) AS c FROM stock_transactions")["c"])
            tx_id = self.ctx.stock.post_transaction(
                operator=user,
                tx_type=self.tx_type.currentData(),
                container_id=int(ctr["id"]),
                quantity=float(self.tx_qty.value()),
                remark=self.tx_remark.text().strip(),
                to_location_id=self.tx_loc.currentData(),
                reviewer=reviewer,
                human_confirmed_compatibility=self.tx_compat.isChecked(),
                idempotency_key=self.tx_key,
            )
            after = int(self.ctx.db.fetchone("SELECT COUNT(*) AS c FROM stock_transactions")["c"])
            tx_no = self.ctx.db.fetchone(
                "SELECT tx_no FROM stock_transactions WHERE id=?", (tx_id,)
            )["tx_no"]
            if after == before:
                self.tx_status.setText(f"该提交已处理，未重复记账（{tx_no}）")
            else:
                self.tx_status.setText(f"已记账 {tx_no}")
                self.tx_key = uuid.uuid4().hex
                self.tx_review_pass.clear()
            self.refresh_transactions()
            self.refresh_bottles()
            self.refresh_home()
            self.refresh_alerts()
        except AppError as exc:
            self.tx_status.setText(str(exc))
            self._err(exc)
        finally:
            self.btn_tx.setEnabled(True)

    def refresh_transactions(self) -> None:
        self._fill_locations(self.tx_loc, allow_blank=True)
        rows = []
        for r in self.ctx.stock.list_transactions(200):
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
        self._fill(
            self.tx_table,
            ["单号", "类型", "瓶子", "品名", "变动", "结余", "操作人", "复核人", "时间", "备注"],
            rows,
        )

    # ---- stocktake ----
    def _build_count(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.count_loc = QComboBox()
        start = QPushButton("开始盘点")
        start.clicked.connect(self.start_count)
        save = QPushButton("保存实盘")
        save.clicked.connect(self.save_count)
        cancel = QPushButton("取消本次盘点")
        cancel.clicked.connect(self.cancel_count)
        bar.addWidget(QLabel("范围"))
        bar.addWidget(self.count_loc)
        bar.addWidget(start)
        bar.addWidget(save)
        bar.addWidget(cancel)
        self.count_table = QTableWidget()
        self.count_status = QLabel("未确认的盘点可以取消，库存不会变。确认后如有差异，会记入流水。")
        self.count_status.setWordWrap(True)
        form = QFormLayout()
        self.count_review_user = QLineEdit()
        self.count_review_pass = QLineEdit()
        self.count_review_pass.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("复核人（含管制品时必填）", self.count_review_user)
        form.addRow("复核密码", self.count_review_pass)
        confirm = QPushButton("确认并过账")
        confirm.clicked.connect(self.confirm_count)
        v.addLayout(bar)
        v.addWidget(self.count_status)
        v.addWidget(self.count_table, 1)
        v.addLayout(form)
        v.addWidget(confirm)
        return w

    def refresh_count_locations(self) -> None:
        self._fill_locations(self.count_loc, allow_blank=True, blank="全部在库瓶子")

    def start_count(self) -> None:
        try:
            self.count_session_id = self.ctx.inventory.start_session(
                self._user(), self.count_loc.currentData()
            )
            location_id = self.count_loc.currentData()
            allowed = None if location_id is None else self._location_tree(int(location_id))
            containers = []
            for row in self.ctx.chemicals.list_containers(status="in_stock"):
                if allowed is None or int(row["location_id"] or 0) in allowed:
                    containers.append(row)
            self.count_table.clear()
            self.count_table.setColumnCount(5)
            self.count_table.setHorizontalHeaderLabels(["编号", "品名", "账面", "实盘", "单位"])
            self.count_table.setRowCount(len(containers))
            for i, row in enumerate(containers):
                code = QTableWidgetItem(row["container_code"])
                code.setData(Qt.ItemDataRole.UserRole, int(row["id"]))
                self.count_table.setItem(i, 0, code)
                self.count_table.setItem(i, 1, QTableWidgetItem(row["chemical_name"]))
                self.count_table.setItem(i, 2, QTableWidgetItem(str(row["quantity"])))
                editor = QLineEdit(str(row["quantity"]))
                self.count_table.setCellWidget(i, 3, editor)
                self.count_table.setItem(i, 4, QTableWidgetItem(row["unit"]))
            self.count_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            session = self.ctx.db.fetchone(
                "SELECT session_no FROM inventory_sessions WHERE id=?",
                (self.count_session_id,),
            )
            self.count_status.setText(f"盘点 {session['session_no']} 已开始。填写实盘后先保存，再确认。")
        except AppError as exc:
            self._err(exc)

    def _location_tree(self, root_id: int) -> set[int]:
        ids = {root_id}
        locs = list(self.ctx.chemicals.list_locations())
        changed = True
        while changed:
            changed = False
            for loc in locs:
                parent = loc["parent_id"]
                if parent is not None and int(parent) in ids and int(loc["id"]) not in ids:
                    ids.add(int(loc["id"]))
                    changed = True
        return ids

    def save_count(self) -> bool:
        if self.count_session_id is None:
            self._err(AppError("请先开始盘点"))
            return False
        try:
            saved = 0
            for row in range(self.count_table.rowCount()):
                item = self.count_table.item(row, 0)
                editor = self.count_table.cellWidget(row, 3)
                if item is None or editor is None or not editor.text().strip():
                    continue
                self.ctx.inventory.upsert_line(
                    self._user(),
                    self.count_session_id,
                    int(item.data(Qt.ItemDataRole.UserRole)),
                    float(editor.text()),
                )
                saved += 1
            self.count_status.setText(f"已保存 {saved} 行实盘。确认前库存不变。")
            return True
        except (AppError, ValueError) as exc:
            self._err(exc)
            return False

    def cancel_count(self) -> None:
        if self.count_session_id is None:
            self._err(AppError("没有进行中的盘点"))
            return
        try:
            self.ctx.inventory.cancel_session(self._user(), self.count_session_id)
            self.count_status.setText("盘点已取消，库存没有变化。")
            self.count_session_id = None
            self.count_table.setRowCount(0)
            self.refresh_bottles()
        except AppError as exc:
            self._err(exc)

    def confirm_count(self) -> None:
        if self.count_session_id is None:
            self._err(AppError("没有进行中的盘点"))
            return
        try:
            if not self.save_count():
                return
            reviewer = self._optional_reviewer(self.count_review_user, self.count_review_pass)
            lines = self.ctx.inventory.close_session(
                self._user(), self.count_session_id, True, reviewer=reviewer
            )
            self.count_status.setText(f"盘点已确认，共 {len(lines)} 行。有差异的数量已记入流水。")
            self.count_session_id = None
            self.refresh_bottles()
            self.refresh_transactions()
            self.refresh_home()
        except AppError as exc:
            self._err(exc)

    # ---- alerts ----
    def _build_alerts(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.warn_days = QSpinBox()
        self.warn_days.setRange(1, 3650)
        save = QPushButton("保存预警天数")
        save.clicked.connect(self.save_warn_days)
        refresh = QPushButton("刷新预警")
        refresh.clicked.connect(self.refresh_alerts)
        bar.addWidget(QLabel("即将到期天数"))
        bar.addWidget(self.warn_days)
        bar.addWidget(save)
        bar.addWidget(refresh)
        bar.addStretch(1)
        self.alert_table = QTableWidget()
        note = QLabel("超储和低库存按管理员设置的全库或某个库位限额计算，单位必须与瓶子一致。")
        note.setWordWrap(True)
        v.addLayout(bar)
        v.addWidget(note)
        v.addWidget(self.alert_table)
        return w

    def save_warn_days(self) -> None:
        try:
            self.ctx.settings.set_expiry_warn_days(self._user(), int(self.warn_days.value()))
            self.refresh_alerts()
            self.refresh_home()
        except AppError as exc:
            self._err(exc)

    def refresh_alerts(self) -> None:
        self.warn_days.setValue(self.ctx.alerts.warn_days())
        data = self.ctx.alerts.all_alerts()
        rows = []
        for item in data["expired"]:
            rows.append(["已过期", item["name"], f"{item['container_code']} 到期 {item['expiry_date']}"])
        for item in data["expiring"]:
            rows.append(["即将到期", item["name"], f"{item['container_code']} 到期 {item['expiry_date']}"])
        for item in data["over_stock"]:
            rows.append(
                [
                    "超储",
                    item["name"],
                    f"{item['location_name']} 当前 {item['total_qty']} / 上限 {item['approved_max_qty']} {item['unit']}",
                ]
            )
        for item in data["low_stock"]:
            rows.append(
                [
                    "低于下限",
                    item["name"],
                    f"{item['location_name']} 当前 {item['total_qty']} / 下限 {item['min_qty']} {item['unit']}",
                ]
            )
        for item in data["missing_sds"]:
            rows.append(["缺少已审核 SDS", item["name"], item["cas_no"] or ""])
        self._fill(self.alert_table, ["类型", "对象", "说明"], rows)

    # ---- SDS ----
    def _build_sds(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.sds_search = QLineEdit()
        self.sds_search.setPlaceholderText("按试剂名称、CAS 或版本搜索")
        self.sds_search.returnPressed.connect(self.refresh_sds)
        find = QPushButton("搜索")
        find.clicked.connect(self.refresh_sds)
        open_btn = QPushButton("打开所选 PDF")
        open_btn.clicked.connect(self.open_sds)
        bar.addWidget(self.sds_search)
        bar.addWidget(find)
        bar.addWidget(open_btn)
        self.sds_table = QTableWidget()
        form = QFormLayout()
        self.sds_chem = QComboBox()
        self.sds_version = QLineEdit()
        self.sds_version.setPlaceholderText("例如 2026-01")
        pick = QPushButton("选择 PDF 并归档")
        pick.clicked.connect(self.attach_sds)
        self.sds_status = QLabel("PDF 会复制到本机数据目录，不依赖原来的文件位置。")
        self.sds_status.setWordWrap(True)
        form.addRow("试剂", self.sds_chem)
        form.addRow("版本", self.sds_version)
        form.addRow(pick)
        v.addLayout(bar)
        v.addWidget(self.sds_table, 1)
        v.addLayout(form)
        v.addWidget(self.sds_status)
        return w

    def refresh_sds(self) -> None:
        self._fill_chemicals(self.sds_chem)
        rows, ids = [], []
        for row in self.ctx.chemicals.search_sds(self.sds_search.text()):
            ids.append(int(row["id"]))
            rows.append(
                [
                    row["chemical_name"],
                    row["cas_no"],
                    row["version"],
                    row["review_status"],
                    row["file_path"],
                    format_local(row["uploaded_at"]),
                ]
            )
        self._fill(self.sds_table, ["试剂", "CAS", "版本", "状态", "归档路径", "时间"], rows, ids)

    def attach_sds(self) -> None:
        if self.sds_chem.currentData() is None:
            self._err(AppError("请先选择试剂"))
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择 SDS PDF", "", "PDF (*.pdf)")
        if not path:
            return
        try:
            sid = self.ctx.chemicals.add_sds(
                self._user(),
                int(self.sds_chem.currentData()),
                self.sds_version.text().strip() or "1",
                path,
                require_pdf=True,
                copy_into=self.ctx.sds_dir,
            )
            self.sds_status.setText(f"已归档，记录号 {sid}")
            self.refresh_sds()
            self.refresh_alerts()
        except AppError as exc:
            self._err(exc)

    def open_sds(self) -> None:
        sid = self._selected_id(self.sds_table)
        if sid is None:
            self._err(AppError("请先选中一份 SDS"))
            return
        row = self.ctx.db.fetchone("SELECT file_path FROM sds_documents WHERE id=?", (sid,))
        if not row:
            return
        path = self.ctx.chemicals.resolve_sds_path(row["file_path"])
        if not path.is_file():
            self._err(AppError("归档文件已丢失"))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    # ---- reports ----
    def _build_reports(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.report_status = QLabel("报表导出到本机数据目录下的 reports 文件夹，PDF 已嵌入中文字体。")
        self.report_status.setWordWrap(True)
        grid = QGridLayout()
        buttons = [
            ("库存 Excel", self._export_stock_xlsx),
            ("库存 PDF", self._export_stock_pdf),
            ("流水 Excel", self._export_tx_xlsx),
            ("流水 PDF", self._export_tx_pdf),
            ("效期 Excel", self._export_exp_xlsx),
            ("效期 PDF", self._export_exp_pdf),
            ("管制台账 Excel", self._export_ctrl_xlsx),
            ("管制台账 PDF", self._export_ctrl_pdf),
            ("盘点 Excel", self._export_count_xlsx),
            ("盘点 PDF", self._export_count_pdf),
        ]
        for index, (label, slot) in enumerate(buttons):
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            grid.addWidget(btn, index // 2, index % 2)
        self.report_session = QComboBox()
        grid.addWidget(QLabel("盘点会话"), 5, 0)
        grid.addWidget(self.report_session, 5, 1)
        v.addWidget(self.report_status)
        v.addLayout(grid)
        v.addStretch(1)
        return w

    def _report_path(self, stem: str, suffix: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.ctx.reports_dir / f"{stem}_{stamp}.{suffix}"

    def _done_report(self, path: Path) -> None:
        self.report_status.setText(f"已生成：{path}")

    def _export_stock_xlsx(self) -> None:
        self._run_report(lambda p: self.ctx.reports.export_stock_excel(self._user(), p), "库存汇总", "xlsx")

    def _export_stock_pdf(self) -> None:
        self._run_report(lambda p: self.ctx.reports.export_stock_pdf(self._user(), p), "库存汇总", "pdf")

    def _export_tx_xlsx(self) -> None:
        self._run_report(lambda p: self.ctx.reports.export_transactions_excel(self._user(), p), "出入库流水", "xlsx")

    def _export_tx_pdf(self) -> None:
        self._run_report(lambda p: self.ctx.reports.export_transactions_pdf(self._user(), p), "出入库流水", "pdf")

    def _export_exp_xlsx(self) -> None:
        self._run_report(lambda p: self.ctx.reports.export_expiry_excel(self._user(), p), "效期清单", "xlsx")

    def _export_exp_pdf(self) -> None:
        self._run_report(lambda p: self.ctx.reports.export_expiry_pdf(self._user(), p), "效期清单", "pdf")

    def _export_ctrl_xlsx(self) -> None:
        self._run_report(lambda p: self.ctx.reports.export_controlled_excel(self._user(), p), "管制台账", "xlsx")

    def _export_ctrl_pdf(self) -> None:
        self._run_report(lambda p: self.ctx.reports.export_controlled_pdf(self._user(), p), "管制台账", "pdf")

    def _export_count_xlsx(self) -> None:
        self._run_count_report("xlsx")

    def _export_count_pdf(self) -> None:
        self._run_count_report("pdf")

    def _run_count_report(self, suffix: str) -> None:
        session_id = self.report_session.currentData()
        if session_id is None:
            self._err(AppError("请选择一次盘点"))
            return
        if suffix == "xlsx":
            self._run_report(
                lambda p: self.ctx.reports.export_stocktake_excel(self._user(), p, int(session_id)),
                "盘点报告",
                "xlsx",
            )
        else:
            self._run_report(
                lambda p: self.ctx.reports.export_stocktake_pdf(self._user(), p, int(session_id)),
                "盘点报告",
                "pdf",
            )

    def _run_report(self, func, stem: str, suffix: str) -> None:
        try:
            path = func(self._report_path(stem, suffix))
            self._done_report(path)
        except AppError as exc:
            self._err(exc)

    def refresh_report_sessions(self) -> None:
        current = self.report_session.currentData()
        self.report_session.clear()
        for row in self.ctx.inventory.list_sessions(100):
            label = (
                f"{row['session_no']} {SESSION_STATUS_LABELS.get(row['status'], row['status'])}"
            )
            self.report_session.addItem(label, int(row["id"]))
        if current is not None:
            index = self.report_session.findData(current)
            if index >= 0:
                self.report_session.setCurrentIndex(index)

    # ---- system ----
    def _build_system(self) -> QWidget:
        tabs = QTabWidget()
        tabs.addTab(self._build_users(), "用户")
        tabs.addTab(self._build_locations(), "库位与限额")
        tabs.addTab(self._build_categories(), "管制类别")
        tabs.addTab(self._build_backup_tab(), "备份与恢复")
        tabs.addTab(self._build_audit_tab(), "审计日志")
        tabs.addTab(self._build_compat(), "相容性参考")
        return tabs

    def _build_users(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.user_table = QTableWidget()
        form = QFormLayout()
        self.new_username = QLineEdit()
        self.new_display = QLineEdit()
        self.new_password = QLineEdit()
        self.new_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_role = QComboBox()
        for code, label in (
            ("warehouse", "库管员"),
            ("user", "普通用户"),
            ("auditor", "审计员"),
            ("safety", "安全员"),
            ("admin", "管理员"),
        ):
            self.new_role.addItem(label, code)
        form.addRow("登录名", self.new_username)
        form.addRow("姓名", self.new_display)
        form.addRow("初始密码", self.new_password)
        form.addRow("角色", self.new_role)
        create = QPushButton("创建用户")
        create.clicked.connect(self.create_user)
        deactivate = QPushButton("停用所选用户")
        deactivate.clicked.connect(lambda: self.set_selected_user_active(False))
        activate = QPushButton("启用所选用户")
        activate.clicked.connect(lambda: self.set_selected_user_active(True))
        reset = QPushButton("重置所选用户密码")
        reset.clicked.connect(self.reset_selected_password)
        self.user_status = QLabel("普通用户只能查询和看报表。库管员办理出入库。审计员只能看日志和报表。")
        self.user_status.setWordWrap(True)
        row = QHBoxLayout()
        for btn in (create, deactivate, activate, reset):
            row.addWidget(btn)
        v.addWidget(self.user_table, 1)
        v.addLayout(form)
        v.addLayout(row)
        v.addWidget(self.user_status)
        return w

    def refresh_users(self) -> None:
        user = self._user()
        if not (user.has("user.manage") or user.has("audit.read")):
            self._fill(self.user_table, ["说明"], [["当前角色不能查看用户列表"]])
            return
        rows, ids = [], []
        for row in self.ctx.auth.list_users(user):
            ids.append(int(row["id"]))
            rows.append(
                [
                    row["username"],
                    row["display_name"],
                    ROLE_LABELS.get(row["role"], row["role"]),
                    "启用" if int(row["is_active"]) else "停用",
                    "演示" if int(row["is_demo"] or 0) else "",
                ]
            )
        self._fill(self.user_table, ["登录名", "姓名", "角色", "状态", "标记"], rows, ids)

    def create_user(self) -> None:
        try:
            self.ctx.auth.create_user(
                self.new_username.text().strip(),
                self.new_password.text(),
                self.new_role.currentData(),
                self.new_display.text().strip(),
                actor=self._user(),
                production=self.ctx.mode == "production",
            )
            self.user_status.setText("用户已创建。请把初始密码单独告诉对方，并要求其妥善保管。")
            self.new_password.clear()
            self.refresh_users()
        except AppError as exc:
            self._err(exc)

    def set_selected_user_active(self, active: bool) -> None:
        uid = self._selected_id(self.user_table)
        if uid is None:
            return
        try:
            self.ctx.auth.set_active(self._user(), uid, active)
            self.refresh_users()
        except AppError as exc:
            self._err(exc)

    def reset_selected_password(self) -> None:
        uid = self._selected_id(self.user_table)
        if uid is None:
            return
        try:
            self.ctx.auth.reset_password(
                self._user(),
                uid,
                self.new_password.text(),
                production=self.ctx.mode == "production",
            )
            self.user_status.setText("密码已重置。")
            self.new_password.clear()
        except AppError as exc:
            self._err(exc)

    def _build_locations(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.loc_table = QTableWidget()
        form = QFormLayout()
        self.loc_level = QComboBox()
        self.loc_level.addItem("库房", "warehouse")
        self.loc_level.addItem("分区", "zone")
        self.loc_level.addItem("柜", "cabinet")
        self.loc_level.addItem("层", "shelf")
        self.loc_code = QLineEdit()
        self.loc_name = QLineEdit()
        self.loc_parent = QComboBox()
        self.loc_condition = QLineEdit()
        form.addRow("层级", self.loc_level)
        form.addRow("编码", self.loc_code)
        form.addRow("名称", self.loc_name)
        form.addRow("上级", self.loc_parent)
        form.addRow("存放条件（文字）", self.loc_condition)
        add = QPushButton("添加库位")
        add.clicked.connect(self.add_location)
        self.limit_chem = QComboBox()
        self.limit_loc = QComboBox()
        self.limit_min = QDoubleSpinBox()
        self.limit_min.setRange(0, 1_000_000_000)
        self.limit_min.setDecimals(3)
        self.limit_max = QDoubleSpinBox()
        self.limit_max.setRange(0, 1_000_000_000)
        self.limit_max.setDecimals(3)
        self.limit_unit = QComboBox()
        self.limit_unit.setEditable(True)
        self.limit_unit.addItems(["mL", "L", "g", "kg", "mg", "瓶"])
        form.addRow("限额试剂", self.limit_chem)
        form.addRow("限额范围", self.limit_loc)
        form.addRow("下限", self.limit_min)
        form.addRow("上限（超储）", self.limit_max)
        form.addRow("限额单位", self.limit_unit)
        limit_btn = QPushButton("保存限额")
        limit_btn.clicked.connect(self.save_limit)
        self.limit_table = QTableWidget()
        self.loc_status = QLabel("")
        self.loc_status.setWordWrap(True)
        v.addWidget(self.loc_table, 1)
        v.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(limit_btn)
        v.addLayout(row)
        v.addWidget(self.limit_table, 1)
        v.addWidget(self.loc_status)
        return w

    def refresh_locations(self) -> None:
        rows, ids = [], []
        for loc in self.ctx.chemicals.list_locations():
            ids.append(int(loc["id"]))
            rows.append([loc["name"], loc["code"], loc["level"], loc["parent_id"] or "", loc["storage_condition"] or ""])
        self._fill(self.loc_table, ["名称", "编码", "层级", "上级ID", "存放条件"], rows, ids)
        self._fill_locations(self.loc_parent, allow_blank=True, blank="无上级")
        self._fill_locations(self.limit_loc, allow_blank=True, blank="全库")
        self._fill_chemicals(self.limit_chem)
        limits = []
        for row in self.ctx.chemicals.list_limits():
            limits.append(
                [
                    row["chemical_name"],
                    row["location_name"] or "全库",
                    row["min_qty"],
                    row["approved_max_qty"],
                    row["unit"],
                ]
            )
        self._fill(self.limit_table, ["试剂", "范围", "下限", "上限", "单位"], limits)

    def add_location(self) -> None:
        try:
            self.ctx.chemicals.add_location(
                self._user(),
                level=self.loc_level.currentData(),
                code=self.loc_code.text(),
                name=self.loc_name.text(),
                parent_id=self.loc_parent.currentData(),
                storage_condition=self.loc_condition.text(),
            )
            self.loc_status.setText("库位已添加。")
            self.refresh_locations()
            self.refresh_bottles()
            self.refresh_count_locations()
        except AppError as exc:
            self._err(exc)

    def save_limit(self) -> None:
        if self.limit_chem.currentData() is None:
            self._err(AppError("请选择试剂"))
            return
        try:
            self.ctx.chemicals.set_stock_limit(
                self._user(),
                int(self.limit_chem.currentData()),
                float(self.limit_min.value()),
                float(self.limit_max.value()),
                self.limit_unit.currentText().strip() or "mL",
                self.limit_loc.currentData(),
            )
            self.loc_status.setText("限额已保存。超过上限会在预警里显示为超储。")
            self.refresh_locations()
            self.refresh_alerts()
        except AppError as exc:
            self._err(exc)

    def _build_categories(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.cat_table = QTableWidget()
        form = QFormLayout()
        self.cat_code = QLineEdit()
        self.cat_name = QLineEdit()
        self.cat_desc = QLineEdit()
        self.cat_review_user = QLineEdit()
        self.cat_review_pass = QLineEdit()
        self.cat_review_pass.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("编码", self.cat_code)
        form.addRow("名称", self.cat_name)
        form.addRow("说明", self.cat_desc)
        form.addRow("停用时的复核人", self.cat_review_user)
        form.addRow("复核密码", self.cat_review_pass)
        add = QPushButton("添加类别")
        add.clicked.connect(self.add_category)
        stop = QPushButton("停用所选类别")
        stop.clicked.connect(lambda: self.toggle_category(False))
        start = QPushButton("重新启用所选类别")
        start.clicked.connect(lambda: self.toggle_category(True))
        self.cat_status = QLabel("停用类别后，只属于该类别的试剂不再强制双人复核。停用本身需要另一名授权人员确认，并写入审计日志。")
        self.cat_status.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(stop)
        row.addWidget(start)
        v.addWidget(self.cat_table, 1)
        v.addLayout(form)
        v.addLayout(row)
        v.addWidget(self.cat_status)
        return w

    def refresh_categories(self) -> None:
        rows, ids = [], []
        for row in self.ctx.chemicals.list_controlled_categories(False):
            ids.append(int(row["id"]))
            rows.append([row["code"], row["name"], row["description"] or "", "启用" if int(row["is_active"]) else "停用"])
        self._fill(self.cat_table, ["编码", "名称", "说明", "状态"], rows, ids)
        self._reload_category_checks()

    def add_category(self) -> None:
        try:
            self.ctx.chemicals.add_controlled_category(
                self._user(), self.cat_code.text(), self.cat_name.text(), self.cat_desc.text()
            )
            self.cat_status.setText("类别已添加。请到试剂台账里勾选到具体试剂。")
            self.refresh_categories()
            self.refresh_chemicals()
        except AppError as exc:
            self._err(exc)

    def toggle_category(self, active: bool) -> None:
        cid = self._selected_id(self.cat_table)
        if cid is None:
            return
        try:
            reviewer = self._optional_reviewer(self.cat_review_user, self.cat_review_pass)
            self.ctx.chemicals.set_category_active(self._user(), cid, active, reviewer=reviewer)
            self.refresh_categories()
        except AppError as exc:
            self._err(exc)

    def _build_backup_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        text = QLabel(
            "备份是一个 ZIP，里面有数据库、SDS 和标签图片，并带校验码。"
            "恢复前必须由您确认。确认后系统会先自动再备份一份当前数据，校验备份文件，然后才覆盖。"
            "不会在未确认的情况下覆盖现有数据。"
        )
        text.setWordWrap(True)
        backup = QPushButton("立即备份")
        backup.clicked.connect(self.do_backup)
        restore = QPushButton("从备份恢复")
        restore.clicked.connect(self.do_restore)
        self.backup_status = QLabel(f"数据库文件：{self.ctx.db.path}")
        self.backup_status.setWordWrap(True)
        self.backup_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(text)
        v.addWidget(backup)
        v.addWidget(restore)
        v.addWidget(self.backup_status)
        v.addStretch(1)
        return w

    def do_backup(self) -> None:
        dest = QFileDialog.getExistingDirectory(self, "选择备份保存位置")
        if not dest:
            return
        try:
            path = self.ctx.backup.backup(self._user(), dest)
            self.backup_status.setText(f"备份完成：{path}")
        except AppError as exc:
            self._err(exc)

    def do_restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择备份 ZIP", "", "备份 (*.zip)")
        if not path:
            return
        answer = QMessageBox.question(
            self,
            "确认恢复",
            "恢复会用备份覆盖当前台账。\n"
            "系统会先自动备份现在的数据，并校验您选择的文件。\n"
            "校验失败则不会覆盖。\n\n确定继续？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.backup_status.setText("已取消恢复，数据未改动。")
            return
        try:
            pre = self.ctx.backup.restore(self._user(), path, confirmed=True)
            self.backup_status.setText(f"恢复完成。恢复前的数据在：{pre}。建议重新打开软件。")
            self.refresh_all()
        except AppError as exc:
            self._err(exc)

    def _build_audit_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        note = QLabel("操作日志只追加、不提供删除或修改。每条记录含前一条的校验值，用来发现事后改动。拥有本机文件权限的人仍可能直接改数据库文件，这不是密码能挡住的。")
        note.setWordWrap(True)
        self.audit_search = QLineEdit()
        self.audit_search.setPlaceholderText("筛选动作或详情")
        self.audit_search.textChanged.connect(lambda text: self._filter(self.audit_table, text))
        self.audit_table = QTableWidget()
        check = QPushButton("校验防篡改链")
        check.clicked.connect(self.verify_audit)
        self.audit_status = QLabel("")
        self.audit_status.setWordWrap(True)
        v.addWidget(note)
        v.addWidget(self.audit_search)
        v.addWidget(self.audit_table, 1)
        v.addWidget(check)
        v.addWidget(self.audit_status)
        return w

    def refresh_audit(self) -> None:
        rows = []
        for row in self.ctx.audit.list_recent(300):
            rows.append(
                [
                    row["id"],
                    row["user_id"] or "",
                    row["action"],
                    row["entity_type"] or "",
                    row["entity_id"] or "",
                    row["detail_json"] or "",
                    format_local(row["created_at"]),
                ]
            )
        self._fill(self.audit_table, ["序号", "用户", "动作", "对象", "对象号", "详情", "时间"], rows)
        self._filter(self.audit_table, self.audit_search.text())

    def verify_audit(self) -> None:
        ok, msg = self.ctx.audit.verify_chain()
        ok2, msg2 = self.ctx.stock.verify_chain()
        if ok and ok2:
            self.audit_status.setText("审计链和库存流水链均未发现改动。")
        else:
            self.audit_status.setText(f"发现不一致。审计：{msg}；流水：{msg2}")

    def _build_compat(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        banner = QLabel(
            "这里只保存管理员手工写下的备注，仅供参考。软件不会判断两种化学品能不能放在一起。"
        )
        banner.setWordWrap(True)
        banner.setStyleSheet("background:#fff4d6;padding:8px;")
        form = QFormLayout()
        self.compat_a = QComboBox()
        self.compat_b = QComboBox()
        self.compat_note = QLineEdit()
        form.addRow("试剂甲", self.compat_a)
        form.addRow("试剂乙", self.compat_b)
        form.addRow("人工备注", self.compat_note)
        save = QPushButton("保存备注")
        save.clicked.connect(self.save_compat)
        self.compat_table = QTableWidget()
        self.compat_status = QLabel("")
        v.addWidget(banner)
        v.addLayout(form)
        v.addWidget(save)
        v.addWidget(self.compat_table, 1)
        v.addWidget(self.compat_status)
        return w

    def refresh_compat(self) -> None:
        self._fill_chemicals(self.compat_a)
        self._fill_chemicals(self.compat_b)
        rows = []
        for row in self.ctx.chemicals.list_compatibility_notes():
            rows.append([row["name_a"], row["name_b"], row["note"]])
        self._fill(self.compat_table, ["试剂甲", "试剂乙", "人工备注（仅供参考）"], rows)

    def save_compat(self) -> None:
        if self.compat_a.currentData() is None or self.compat_b.currentData() is None:
            return
        try:
            self.ctx.chemicals.add_compatibility_note(
                self._user(),
                int(self.compat_a.currentData()),
                int(self.compat_b.currentData()),
                self.compat_note.text(),
            )
            self.compat_status.setText("已保存。这只是备注，不是混放结论。")
            self.compat_note.clear()
            self.refresh_compat()
        except AppError as exc:
            self._err(exc)

    def _optional_reviewer(self, user_edit: QLineEdit, pass_edit: QLineEdit):
        name = user_edit.text().strip()
        if not name:
            return None
        return self.ctx.auth.verify_second_user(self._user(), name, pass_edit.text())

    def _filter(self, table: QTableWidget, text: str) -> None:
        needle = text.strip().lower()
        for row in range(table.rowCount()):
            blob = " ".join(
                table.item(row, col).text() if table.item(row, col) else ""
                for col in range(table.columnCount())
            )
            table.setRowHidden(row, bool(needle) and needle not in blob.lower())

    def refresh_all(self) -> None:
        self.refresh_home()
        self._reload_category_checks()
        self.refresh_chemicals()
        self.refresh_bottles()
        self.refresh_transactions()
        self.refresh_count_locations()
        self.refresh_alerts()
        self.refresh_sds()
        self.refresh_report_sessions()
        self.refresh_users()
        self.refresh_locations()
        self.refresh_categories()
        self.refresh_audit()
        self.refresh_compat()

    def import_chemicals_from_excel(self, path: str) -> int:
        """Kept for operators who already have a spreadsheet. Not shown as a required step."""
        self.ctx.auth.require(self._user(), "chem.write")
        wb = load_workbook(path)
        ws = wb.active
        headers = [str(c.value).strip() if c.value else "" for c in next(ws.iter_rows(min_row=1, max_row=1))]
        mapping = {h: i for i, h in enumerate(headers)}
        if "name" not in mapping and "名称" in mapping:
            mapping["name"] = mapping["名称"]
        for key, cn in (
            ("cas_no", "CAS"),
            ("concentration", "浓度"),
            ("specification", "规格"),
            ("manufacturer", "生产厂家"),
        ):
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
                    "concentration": excel_row[mapping["concentration"]] if "concentration" in mapping else "",
                    "specification": excel_row[mapping["specification"]] if "specification" in mapping else "",
                    "manufacturer": excel_row[mapping["manufacturer"]] if "manufacturer" in mapping else "",
                }
            )
        count = self.ctx.reports.import_chemicals_excel(rows)
        self.ctx.audit.log(self._user().id, "chem.import_excel", "chemicals", None, {"count": count})
        self.refresh_chemicals()
        return count
