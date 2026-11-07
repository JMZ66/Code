"""Desktop window. Each business module has its own page and its own model."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from labuv.database import ProjectStore
from labuv.errors import LabError
from labuv.examples import load_example
from labuv.importers import import_table, require_columns
from labuv.lod import PRESET_EURACHEM, lod_loq
from labuv.paths import docs_dir, font_path
from labuv.precision import analyze_precision
from labuv.regression import fit_line
from labuv.reporting import build_report, write_excel, write_pdf
from labuv.topdown import evaluate_topdown
from labuv.trueness import crm_bias, spike_recovery
from labuv.uncertainty import evaluate_bottom_up
from labuv.validation_summary import summarize
from labuv.version import APP_NAME, __version__
from labuv.gui.chart import BarChart


def _item(text):
    return QTableWidgetItem("" if text is None else str(text))


def _cell(table, row, column):
    item = table.item(row, column)
    return "" if item is None else item.text().strip()


def _fill(table, rows, columns):
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.setItem(r, c, _item(value))


def _rows(table):
    data = []
    for r in range(table.rowCount()):
        values = [_cell(table, r, c) for c in range(table.columnCount())]
        if any(values):
            data.append(values)
    return data


class ResultPane(QWidget):
    def __init__(self):
        super().__init__()
        self.trace = QPlainTextEdit()
        self.trace.setReadOnly(True)
        self.table = QTableWidget(0, 1)
        self.chart = BarChart()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("计算过程、预算和分量图"))
        layout.addWidget(self.trace, 2)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.chart, 1)

    def show_result(self, result: dict):
        warnings = "\n".join(result.get("warnings") or [])
        self.trace.setPlainText((result.get("trace") or "") + ("\n\n" + warnings if warnings else ""))
        rows = result.get("budget") or result.get("characteristics") or []
        if rows:
            headers = list(rows[0].keys())
            self.table.setColumnCount(len(headers))
            self.table.setHorizontalHeaderLabels([str(item) for item in headers])
            self.table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, key in enumerate(headers):
                    self.table.setItem(r, c, _item(row.get(key)))
        else:
            self.table.setRowCount(0)
        bars = []
        for row in result.get("budget") or []:
            bars.append((row["name"], float(row.get("variance_share") or 0.0)))
        if not bars and result.get("uc") is not None:
            bars = [("uc", float(result["uc"]))]
        self.chart.set_bars(bars)


class A1Page(QWidget):
    key = "A1"
    title = "A1 自下而上不确定度"

    def __init__(self):
        super().__init__()
        self.expression = QLineEdit("(c_meas - c_blank) * D * V / A")
        self.output_name = QLineEdit("y")
        self.expected_unit = QLineEdit("mg/dm**2")
        self.k = QLineEdit("2")
        self.coverage = QComboBox()
        self.coverage.addItems(["k", "probability"])
        self.mc = QCheckBox("同时做 JCGM 101 Monte Carlo")
        self.seed = QLineEdit("20261107")
        self.samples = QLineEdit("20000")
        self.correlation = QPlainTextEdit()
        self.correlation.setPlaceholderText("留空表示不相关。否则每个输入一行相关系数，用逗号分隔，顺序与下表中非空行一致。")
        self.table = QTableWidget()
        self.source_path = ""
        self.source_sha = ""
        self.raw_headers = []
        self.raw_rows = []
        form = QFormLayout()
        form.addRow("模型表达式", self.expression)
        form.addRow("输出名称", self.output_name)
        form.addRow("预期单位", self.expected_unit)
        form.addRow("覆盖方式", self.coverage)
        form.addRow("k 或覆盖概率", self.k)
        buttons = QHBoxLayout()
        for name, slot in (("迁移示例", "migration.json"), ("标准溶液示例", "standard_solution.json"), ("ICP 自下而上示例", "icp_bottom.json")):
            button = QPushButton(name)
            button.clicked.connect(lambda _checked=False, item=slot: self.load_named(item))
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("只接受算术表达式。A 类必须选择 single 或 mean。相关矩阵不会被自动改成对称阵。"))
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self.table)
        layout.addWidget(self.mc)
        row = QHBoxLayout()
        row.addWidget(QLabel("种子"))
        row.addWidget(self.seed)
        row.addWidget(QLabel("样本数"))
        row.addWidget(self.samples)
        layout.addLayout(row)
        layout.addWidget(self.correlation)
        self.load_named("migration.json")

    def load_named(self, name):
        payload = load_example(name)
        self.expression.setText(payload["expression"])
        self.output_name.setText(payload.get("output_name") or "y")
        self.expected_unit.setText(payload.get("expected_unit") or "")
        columns = ["name", "estimate", "unit", "kind", "role", "distribution", "u_mode", "u", "half_width", "k", "df", "source", "raw"]
        rows = []
        for item in payload["inputs"]:
            raw = item.get("raw") or []
            rows.append([
                item.get("name", ""), item.get("estimate", ""), item.get("unit", ""), item.get("kind", ""),
                item.get("role", ""), item.get("distribution", ""), item.get("u_mode", ""), item.get("u", ""),
                item.get("half_width", ""), item.get("k", ""), item.get("df", ""), item.get("source", ""),
                ";".join(str(value) for value in raw),
            ])
        _fill(self.table, rows, columns)
        self.correlation.setPlainText("")

    def payload(self):
        inputs = []
        for row in _rows(self.table):
            raw = [part.strip() for part in row[12].split(";") if part.strip() != ""]
            item = {
                "name": row[0], "estimate": row[1] or None, "unit": row[2], "kind": row[3],
                "role": row[4] or None, "distribution": row[5] or None, "u_mode": row[6] or None,
                "u": row[7] or None, "half_width": row[8] or None, "k": row[9] or None,
                "df": row[10] or None, "source": row[11], "raw": raw or None,
            }
            inputs.append(item)
        text = self.correlation.toPlainText().strip()
        correlation = None
        if text:
            correlation = [[part.strip() for part in line.split(",")] for line in text.splitlines() if line.strip()]
        coverage_value = self.k.text().strip()
        if self.coverage.currentText() == "k":
            coverage = {"mode": "k", "k": coverage_value}
        else:
            coverage = {"mode": "probability", "p": coverage_value}
        monte = {"enabled": self.mc.isChecked(), "seed": int(self.seed.text()), "n": int(self.samples.text()), "p": 0.95, "interval": "symmetric"}
        return {
            "expression": self.expression.text(),
            "output_name": self.output_name.text(),
            "expected_unit": self.expected_unit.text(),
            "report_unit": self.expected_unit.text(),
            "inputs": inputs,
            "correlation": correlation,
            "coverage": coverage,
            "monte_carlo": monte,
        }


class A2Page(QWidget):
    key = "A2"
    title = "A2 自上而下不确定度"

    def __init__(self):
        super().__init__()
        self.model = QComboBox()
        self.model.addItems(["relative", "absolute", "mean_recovery", "future_single_crm"])
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("当前模型的 JSON 参数。示例按钮会填入完整且带模拟或出处标记的数据。")
        buttons = QHBoxLayout()
        for label, name in (("ICP 自上而下模拟", "icp_topdown.json"), ("MUPR 2026 例2", "phosphate_recovery.json")):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, item=name: self.load_named(item))
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("不同数据使用不同模型。精密度是否已包含回收率必须显式声明；声明已包含时拒绝再加回收率分量。"))
        layout.addWidget(self.model)
        layout.addLayout(buttons)
        layout.addWidget(self.editor)
        self.load_named("icp_topdown.json")

    def load_named(self, name):
        import json
        payload = load_example(name)
        self.model.setCurrentText(payload["model"])
        self.editor.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))

    def payload(self):
        import json
        try:
            data = json.loads(self.editor.toPlainText())
        except json.JSONDecodeError as exc:
            raise LabError(f"参数不是合法 JSON：{exc}", code="input") from exc
        data["model"] = self.model.currentText()
        return data


class B1Page(QWidget):
    key = "B1"
    title = "B1 校准"

    def __init__(self):
        super().__init__()
        self.mode = QComboBox()
        self.mode.addItems(["ols", "wls_absolute", "wls_inv_x", "wls_inv_x2", "wls_custom"])
        self.table = QTableWidget()
        self.y0 = QLineEdit("")
        self.replicates = QLineEdit("1")
        self.u_y = QLineEdit("")
        self.source_path = ""
        self.source_sha = ""
        self.raw_headers = []
        self.raw_rows = []
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("普通最小二乘，或权重等于已知方差倒数的加权最小二乘。1/x 与 1/x² 只在用户选择后按相对权重处理；x=0 会定位到该行并停止。"))
        layout.addWidget(self.mode)
        layout.addWidget(self.table)
        form = QFormLayout()
        form.addRow("反算响应 y（可空）", self.y0)
        form.addRow("新响应重复次数", self.replicates)
        form.addRow("新响应标准不确定度（可空）", self.u_y)
        layout.addLayout(form)
        button = QPushButton("载入四点直线示例")
        button.clicked.connect(self.load_demo)
        layout.addWidget(button)
        self.load_demo()

    def load_demo(self):
        _fill(self.table, [[1, 2.1], [2, 3.9], [3, 6.2], [4, 7.8]], ["x", "y", "sigma", "weight"])
        self.mode.setCurrentText("ols")

    def import_path(self, path):
        table = import_table(path)
        require_columns(table, ["x", "y"])
        rows = []
        for row in table["rows"]:
            rows.append([row.get("x", ""), row.get("y", ""), row.get("sigma", ""), row.get("weight", ""), row.get("_row", "")])
        _fill(self.table, rows, ["x", "y", "sigma", "weight", "_row"])
        self.source_path = table["path"]
        self.source_sha = table["sha256"]
        self.raw_headers = [header for header in table["headers"]]
        self.raw_rows = [{key: value for key, value in row.items() if key != "_row"} for row in table["rows"]]
        return table

    def payload(self):
        rows = []
        for row in _rows(self.table):
            item = {"x": row[0], "y": row[1]}
            if len(row) > 2 and row[2] != "":
                item["sigma"] = row[2]
            if len(row) > 3 and row[3] != "":
                item["weight"] = row[3]
            if len(row) > 4 and row[4] != "":
                item["_row"] = row[4]
            rows.append(item)
        payload = {"rows": rows, "weight_mode": self.mode.currentText()}
        if self.y0.text().strip():
            payload["inverse"] = {"y": self.y0.text().strip(), "replicates": self.replicates.text().strip() or 1}
            if self.u_y.text().strip():
                payload["inverse"]["u_y"] = self.u_y.text().strip()
        return payload


class B2Page(QWidget):
    key = "B2"
    title = "B2 精密度"

    def __init__(self):
        super().__init__()
        self.design = QComboBox()
        self.design.addItems(["one_way", "two_way_balanced"])
        self.rsd = QCheckBox("计算重复性 RSD")
        self.table = QTableWidget()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("单因素可用于平衡或不平衡数据。两个因素都存在时不能改按单因素计算。均值为 0 时拒绝 RSD。"))
        layout.addWidget(self.design)
        layout.addWidget(self.rsd)
        layout.addWidget(self.table)
        button = QPushButton("载入不平衡单因素示例")
        button.clicked.connect(self.load_demo)
        layout.addWidget(button)
        self.load_demo()

    def load_demo(self):
        _fill(self.table, [[1, "日1", ""], [2, "日1", ""], [3, "日2", ""], [4, "日2", ""], [5, "日2", ""]], ["value", "factor1", "factor2"])
        self.design.setCurrentText("one_way")

    def payload(self):
        rows = []
        for row in _rows(self.table):
            rows.append({"value": row[0], "factor1": row[1], "factor2": row[2] if len(row) > 2 else ""})
        return {"rows": rows, "design": self.design.currentText(), "include_rsd": self.rsd.isChecked()}


class B3Page(QWidget):
    key = "B3"
    title = "B3 正确度"

    def __init__(self):
        super().__init__()
        self.kind = QComboBox()
        self.kind.addItems(["crm", "spike_replicates", "spike_paired"])
        self.values = QLineEdit("10.1, 9.9, 10.2, 9.8, 10.0")
        self.reference = QLineEdit("9.8")
        self.expanded = QLineEdit("0.2")
        self.k = QLineEdit("2")
        self.applicable = QCheckBox("证书不确定度适用于本次比对")
        self.applicable.setChecked(True)
        self.added = QLineEdit("10")
        self.blank = QLineEdit("1")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("CRM 偏倚和加标回收分开计算。证书没有覆盖因子时不会假设 k=2。"))
        form = QFormLayout()
        form.addRow("类型", self.kind)
        form.addRow("测定值或加标前/测得值，逗号分隔", self.values)
        form.addRow("证书值或加标后（成对时）", self.reference)
        form.addRow("证书扩展不确定度 U", self.expanded)
        form.addRow("证书 k", self.k)
        form.addRow("加入量", self.added)
        form.addRow("空白", self.blank)
        layout.addLayout(form)
        layout.addWidget(self.applicable)

    def payload(self):
        kind = self.kind.currentText()
        numbers = [part.strip() for part in self.values.text().split(",") if part.strip() != ""]
        if kind == "crm":
            return {
                "replicates": numbers,
                "reference": self.reference.text(),
                "certificate_uncertainty_applicable": self.applicable.isChecked(),
                "certificate_expanded": self.expanded.text(),
                "certificate_k": self.k.text(),
            }
        if kind == "spike_replicates":
            return {"design": "replicates", "found": numbers, "added": self.added.text(), "blank": self.blank.text()}
        before = numbers
        after = [part.strip() for part in self.reference.text().split(",") if part.strip() != ""]
        return {"design": "paired_native", "before": before, "after": after, "added": self.added.text()}


class B4Page(QWidget):
    key = "B4"
    title = "B4 检出限和定量限"

    def __init__(self):
        super().__init__()
        self.method = QComboBox()
        self.method.addItems(["blank_sd", "calibration"])
        self.scope = QComboBox()
        self.scope.addItems(["method", "instrument"])
        self.values = QLineEdit("1, 2, 3")
        self.k_lod = QLineEdit("")
        self.k_loq = QLineEdit("")
        self.source = QLineEdit("")
        self.corrected = QCheckBox("常规结果做空白校正")
        self.corrected.setChecked(True)
        self.unit = QLineEdit("mg/kg")
        self.slope = QLineEdit("")
        self.residual = QLineEdit("")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("倍数和出处为空时不计算。3 和 10 只有在按下预设并确认出处后才会写入，不会偷偷当作法定标准。"))
        form = QFormLayout()
        for label, widget in (
            ("方法", self.method), ("仪器或方法", self.scope), ("空白测定值", self.values),
            ("k_LOD", self.k_lod), ("k_LOQ", self.k_loq), ("出处", self.source), ("单位", self.unit),
            ("斜率", self.slope), ("信号残差标准差", self.residual),
        ):
            form.addRow(label, widget)
        layout.addLayout(form)
        layout.addWidget(self.corrected)
        preset = QPushButton("填入 Eurachem 2025 常用倍数及出处")
        preset.clicked.connect(self.apply_preset)
        layout.addWidget(preset)

    def apply_preset(self):
        self.k_lod.setText(str(PRESET_EURACHEM["k_lod"]))
        self.k_loq.setText(str(PRESET_EURACHEM["k_loq"]))
        self.source.setText(PRESET_EURACHEM["source"])

    def payload(self):
        values = [part.strip() for part in self.values.text().split(",") if part.strip() != ""]
        return {
            "method": self.method.currentText(),
            "scope": self.scope.currentText(),
            "values": values,
            "k_lod": self.k_lod.text(),
            "k_loq": self.k_loq.text(),
            "source": self.source.text(),
            "blank_corrected": self.corrected.isChecked(),
            "n_averaged": 1,
            "n_blank": 1,
            "unit": self.unit.text(),
            "slope": self.slope.text(),
            "residual_sd": self.residual.text(),
            "residual_domain": "signal",
        }


class B5Page(QWidget):
    key = "B5"
    title = "B5 验证汇总"

    def __init__(self):
        super().__init__()
        self.table = QTableWidget()
        self.levels = QLineEdit("0.2, 0.5, 1.0")
        self.claimed_min = QLineEdit("")
        self.claimed_max = QLineEdit("")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("验收准则和出处都由用户录入。缺一项就显示未评价，软件不自造统一合格线。"))
        layout.addWidget(self.table)
        form = QFormLayout()
        form.addRow("已测水平", self.levels)
        form.addRow("声称下限（可空）", self.claimed_min)
        form.addRow("声称上限（可空）", self.claimed_max)
        layout.addLayout(form)
        _fill(self.table, [["回收率", "0.98", "1", "", ""]], ["name", "result", "unit", "criterion_min", "criterion_source"])

    def payload(self):
        characteristics = []
        for row in _rows(self.table):
            criterion = {}
            if len(row) > 3 and row[3] != "":
                criterion["min"] = row[3]
            if len(row) > 4 and self.table.columnCount() > 5 and row[5] != "":
                criterion["max"] = row[5]
            characteristics.append({
                "name": row[0],
                "result": row[1],
                "unit": row[2] if len(row) > 2 else "",
                "criterion": criterion,
                "criterion_source": row[4] if len(row) > 4 else "",
            })
        claimed = {}
        if self.claimed_min.text().strip() and self.claimed_max.text().strip():
            claimed = {"min": self.claimed_min.text(), "max": self.claimed_max.text()}
        levels = [part.strip() for part in self.levels.text().split(",") if part.strip() != ""]
        return {"characteristics": characteristics, "working_range": {"tested_levels": levels, "claimed": claimed}}


class HistoryPage(QWidget):
    key = "history"
    title = "历史项目"

    def __init__(self, store: ProjectStore):
        super().__init__()
        self.store = store
        self.search = QLineEdit()
        self.list = QListWidget()
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        button = QPushButton("检索")
        button.clicked.connect(self.refresh)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("打开历史记录只显示当时保存的原始快照、参数和结果，不会悄悄重算。"))
        layout.addWidget(self.search)
        layout.addWidget(button)
        layout.addWidget(self.list)
        layout.addWidget(self.detail)
        self.list.currentRowChanged.connect(self.open_current)
        self.rows = []

    def refresh(self):
        self.rows = self.store.search(self.search.text().strip())
        self.list.clear()
        for row in self.rows:
            self.list.addItem(f"{row['id']}  {row['name']}  {row['module']}  {row['operator']}")

    def open_current(self, index):
        if index < 0 or index >= len(self.rows):
            return
        project = self.store.get_project(self.rows[index]["id"])
        checked = project.get("raw_sha256_checked")
        note = "原始字节的 SHA-256 与保存值一致。" if checked and checked == project.get("source_sha256") else "没有原始字节或哈希未同时存在。"
        self.detail.setPlainText(
            "这是保存的结果，不是重新计算。\n"
            f"应用 {project['app_version']}，引擎 {project['engine_version']}，模型 {project['model_id']}\n"
            f"{note}\n\n{project['process_text']}"
        )


class StandardsPage(QWidget):
    key = "standards"
    title = "标准、限制和手册"

    def __init__(self):
        super().__init__()
        browser = QTextBrowser()
        path = docs_dir() / "标准与公式清单.md"
        if path.is_file():
            browser.setPlainText(path.read_text(encoding="utf-8"))
        else:
            browser.setPlainText("标准清单文件没有放在文档目录中。")
        limits = docs_dir() / "已知限制.md"
        manual = docs_dir() / "用户手册.md"
        extra = ""
        if limits.is_file():
            extra += "\n\n" + limits.read_text(encoding="utf-8")
        if manual.is_file():
            extra += "\n\n" + manual.read_text(encoding="utf-8")[:4000]
        browser.setPlainText(browser.toPlainText() + extra)
        layout = QVBoxLayout(self)
        layout.addWidget(browser)


class MainWindow(QMainWindow):
    def __init__(self, db_path):
        super().__init__()
        font_id = QFontDatabase.addApplicationFont(str(font_path()))
        if font_id >= 0:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                self.setFont(QFont(families[0], 10))
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1180, 760)
        self.store = ProjectStore(db_path)
        self.operator = QLineEdit("模拟操作者")
        self.project_name = QLineEdit("未命名项目")
        self.pages = [
            A1Page(), A2Page(), B1Page(), B2Page(), B3Page(), B4Page(), B5Page(),
            HistoryPage(self.store), StandardsPage(),
        ]
        self.result = ResultPane()
        self.stack = QStackedWidget()
        self.menu = QListWidget()
        for page in self.pages:
            self.stack.addWidget(page)
            self.menu.addItem(page.title)
        self.menu.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.menu.setCurrentRow(0)
        self.last = None
        self.last_module = "A1"
        buttons = QHBoxLayout()
        for label, slot in (("计算", self.calculate_current), ("导出 PDF", self.export_pdf_dialog), ("导出 Excel", self.export_excel_dialog), ("保存项目", self.save_current), ("导入校准 CSV", self.import_calibration_dialog)):
            button = QPushButton(label)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(self.menu)
        form = QFormLayout()
        form.addRow("操作者", self.operator)
        form.addRow("项目名称", self.project_name)
        left_layout.addLayout(form)
        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(self.stack)
        splitter.addWidget(self.result)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 2)
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(splitter)
        layout.addLayout(buttons)
        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())

    def current_page(self):
        return self.pages[self.stack.currentIndex()]

    def show_error(self, exc: LabError):
        self.result.trace.setPlainText(exc.located())
        self.statusBar().showMessage(exc.located(), 10000)

    def calculate_current(self):
        page = self.current_page()
        if not hasattr(page, "payload"):
            return
        try:
            payload = page.payload()
            if page.key == "A1":
                result = evaluate_bottom_up(payload)
            elif page.key == "A2":
                result = evaluate_topdown(payload)
            elif page.key == "B1":
                result = fit_line(payload)
            elif page.key == "B2":
                result = analyze_precision(payload)
            elif page.key == "B3":
                if page.kind.currentText() == "crm":
                    result = crm_bias(payload)
                else:
                    result = spike_recovery(payload)
            elif page.key == "B4":
                result = lod_loq(payload)
            elif page.key == "B5":
                result = summarize(payload)
            else:
                return
        except LabError as exc:
            self.show_error(exc)
            self.last = None
            return
        except Exception as exc:  # unexpected programming errors stay visible
            self.result.trace.setPlainText("计算过程出现未预期错误：" + str(exc))
            self.last = None
            return
        self.last = result
        self.last_module = page.key
        self.result.show_result(result)

    def report_dict(self):
        if not self.last:
            raise LabError("还没有可导出的计算结果。")
        page = self.current_page()
        return build_report(
            title=self.project_name.text() or page.title,
            module=page.key,
            operator=self.operator.text() or "未填写",
            model_id=self.last.get("model_id", page.key),
            result=self.last,
            source_path=getattr(page, "source_path", ""),
            source_sha256=getattr(page, "source_sha", ""),
            raw_headers=getattr(page, "raw_headers", None),
            raw_rows=getattr(page, "raw_rows", None),
        )

    def export_pdf(self, path):
        write_pdf(path, self.report_dict())

    def export_excel(self, path):
        write_excel(path, self.report_dict())

    def export_pdf_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出 PDF", "报告.pdf", "PDF (*.pdf)")
        if path:
            try:
                self.export_pdf(path)
            except LabError as exc:
                self.show_error(exc)

    def export_excel_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出 Excel", "报告.xlsx", "Excel (*.xlsx)")
        if path:
            try:
                self.export_excel(path)
            except LabError as exc:
                self.show_error(exc)

    def import_calibration_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入校准", "", "表格 (*.csv *.xlsx)")
        if not path:
            return
        self.menu.setCurrentRow(2)
        try:
            self.pages[2].import_path(path)
        except LabError as exc:
            self.show_error(exc)

    def save_current(self):
        if not self.last:
            self.show_error(LabError("没有可保存的计算结果。"))
            return
        page = self.current_page()
        raw = None
        source = getattr(page, "source_path", "") or None
        if source and Path(source).is_file():
            raw = Path(source).read_bytes()
        parameters = page.payload() if hasattr(page, "payload") else {}
        project_id = self.store.save_project(
            name=self.project_name.text() or "未命名项目",
            module=page.key,
            operator=self.operator.text() or "未填写",
            model_id=self.last.get("model_id", page.key),
            parameters=parameters,
            result=self.last,
            process_text=self.last.get("trace") or "",
            source_path=source,
            raw_bytes=raw,
        )
        if parameters:
            self.store.save_template(name=self.project_name.text() or page.title, module=page.key, parameters=parameters)
        self.result.trace.appendPlainText(f"\n已保存项目 {project_id}，并保存了可复用模板。")
        return project_id
