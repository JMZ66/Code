from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gcms_kb.constants import (
    BASIS_REVIEW,
    BASIS_STANDARD,
    BASIS_TEXT,
    CANDIDATE_LABEL,
    DECISION_MANUAL,
    DECISION_STANDARD,
    DECISION_TEXT,
    DISCLAIMER,
)
from gcms_kb.gui.plots import ChromPlot
from gcms_kb.ri import parse_alkane_csv
from gcms_kb.version import __version__


def _item(text) -> QTableWidgetItem:
    return QTableWidgetItem("" if text is None else str(text))


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(640, 520)
        form = QFormLayout(self)
        self.user = QLineEdit(settings.user_name)
        self.parser = QLineEdit(settings.thermo_parser_path)
        self.msconvert = QLineEdit(settings.msconvert_path)
        self.msdial = QLineEdit(settings.msdial_console_path)
        self.amdis = QLineEdit(settings.amdis_path)
        self.mz_tol = QDoubleSpinBox()
        self.mz_tol.setRange(0.0001, 5)
        self.mz_tol.setDecimals(4)
        self.mz_tol.setValue(settings.mz_tolerance)
        self.rt_tol = QDoubleSpinBox()
        self.rt_tol.setRange(0.0001, 5)
        self.rt_tol.setDecimals(4)
        self.rt_tol.setValue(settings.rt_tolerance)
        self.ri_tol = QDoubleSpinBox()
        self.ri_tol.setRange(0, 5000)
        self.ri_tol.setValue(settings.ri_tolerance)
        self.min_score = QDoubleSpinBox()
        self.min_score.setRange(0, 1)
        self.min_score.setDecimals(3)
        self.min_score.setValue(settings.similarity_min)
        self.top_k = QSpinBox()
        self.top_k.setRange(1, 100)
        self.top_k.setValue(settings.similarity_top_k)
        self.apex = QDoubleSpinBox()
        self.apex.setRange(0.001, 2)
        self.apex.setDecimals(3)
        self.apex.setValue(settings.deconv_apex_tol)
        self.background = QCheckBox("峰谱默认扣除背景")
        self.background.setChecked(settings.background_subtract)
        form.addRow("操作者", self.user)
        form.addRow("ThermoRawFileParser", self.parser)
        form.addRow("msconvert", self.msconvert)
        form.addRow("MS-DIAL 控制台", self.msdial)
        form.addRow("AMDIS 路径（仅记录，不自动运行）", self.amdis)
        form.addRow("EIC m/z 容差", self.mz_tol)
        form.addRow("峰对齐 RT 容差 (min)", self.rt_tol)
        form.addRow("谱库 RI 容差", self.ri_tol)
        form.addRow("最低余弦（0–1）", self.min_score)
        form.addRow("候选条数", self.top_k)
        form.addRow("解卷积峰顶容差 (min)", self.apex)
        form.addRow(self.background)
        note = QLabel(
            "ThermoRawFileParser、msconvert、MS-DIAL、AMDIS 都不随本程序分发。"
            "请填写你本机已经安装的程序路径。相似度不是鉴定。"
        )
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def apply(self, settings):
        settings.user_name = self.user.text().strip()
        settings.thermo_parser_path = self.parser.text().strip()
        settings.msconvert_path = self.msconvert.text().strip()
        settings.msdial_console_path = self.msdial.text().strip()
        settings.amdis_path = self.amdis.text().strip()
        settings.mz_tolerance = self.mz_tol.value()
        settings.rt_tolerance = self.rt_tol.value()
        settings.ri_tolerance = self.ri_tol.value()
        settings.similarity_min = self.min_score.value()
        settings.similarity_top_k = self.top_k.value()
        settings.deconv_apex_tol = self.apex.value()
        settings.background_subtract = self.background.isChecked()


class ImportMetaDialog(QDialog):
    def __init__(self, user_name: str, single: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入信息")
        form = QFormLayout(self)
        self.code = QLineEdit()
        self.instrument = QLineEdit()
        self.method = QLineEdit()
        self.acquired = QLineEdit()
        self.notes = QPlainTextEdit()
        self.user = QLineEdit(user_name)
        if single:
            form.addRow("样品编号（空则用文件名）", self.code)
        else:
            self.code.setPlaceholderText("批量导入时使用各文件名")
            self.code.setEnabled(False)
            form.addRow("样品编号", self.code)
        form.addRow("仪器", self.instrument)
        form.addRow("方法", self.method)
        form.addRow("采集时间", self.acquired)
        form.addRow("操作者", self.user)
        form.addRow("备注", self.notes)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict:
        return {
            "sample_code": self.code.text().strip() or None,
            "instrument": self.instrument.text().strip(),
            "method_name": self.method.text().strip(),
            "acquired_at": self.acquired.text().strip(),
            "notes": self.notes.toPlainText().strip(),
            "user_name": self.user.text().strip(),
        }


class ConfirmDialog(QDialog):
    def __init__(self, user_name: str, rt: float | None, ri: float | None, score: float | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("记录确认结论")
        self.resize(560, 460)
        layout = QVBoxLayout(self)
        warning = QLabel(DISCLAIMER + " 高相似度不会被保存成鉴定。")
        warning.setWordWrap(True)
        warning.setStyleSheet("color:#9a3412;font-weight:600;")
        layout.addWidget(warning)
        self.standard = QRadioButton("标准品确认")
        self.manual = QRadioButton("人工审核")
        self.standard.setChecked(True)
        row = QHBoxLayout()
        row.addWidget(self.standard)
        row.addWidget(self.manual)
        layout.addLayout(row)
        form = QFormLayout()
        self.name = QLineEdit()
        self.cas = QLineEdit()
        self.detail = QLineEdit()
        self.evidence = QPlainTextEdit()
        self.user = QLineEdit(user_name)
        form.addRow("化合物名称", self.name)
        form.addRow("CAS", self.cas)
        form.addRow("依据摘要", self.detail)
        form.addRow("操作者", self.user)
        form.addRow("证据", self.evidence)
        layout.addLayout(form)
        extra = "未计算"
        if score is not None:
            extra = f"{score:.3f}（仅供参考，不是鉴定依据）"
        layout.addWidget(QLabel(f"若你刚看过谱库候选，其参考余弦是 {extra}。RT={rt} RI={ri}"))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._rt = rt
        self._ri = ri
        self._score = score

    def record(self, sample_id: int, target_kind: str, target_id: int | None) -> dict:
        decision = DECISION_STANDARD if self.standard.isChecked() else DECISION_MANUAL
        return {
            "sample_id": sample_id,
            "target_kind": target_kind,
            "target_id": target_id,
            "decision": decision,
            "basis": BASIS_STANDARD if decision == DECISION_STANDARD else BASIS_REVIEW,
            "compound_name": self.name.text().strip(),
            "cas": self.cas.text().strip(),
            "basis_detail": self.detail.text().strip(),
            "user_name": self.user.text().strip(),
            "evidence": self.evidence.toPlainText().strip(),
            "rt_observed": self._rt,
            "ri_observed": self._ri,
            "score_informational": self._score,
        }


class UnknownDialog(QDialog):
    def __init__(self, user_name: str, rt: float | None, ri: float | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("登记未知峰")
        form = QFormLayout(self)
        self.rt = QDoubleSpinBox()
        self.rt.setRange(0, 10000)
        self.rt.setDecimals(4)
        self.rt.setValue(0 if rt is None else float(rt))
        self.note = QPlainTextEdit()
        self.user = QLineEdit(user_name)
        form.addRow("保留时间 (min)", self.rt)
        form.addRow("操作者", self.user)
        form.addRow("说明", self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._ri = ri

    def record(self, sample_id: int, target_kind: str | None, target_id: int | None) -> dict:
        return {
            "sample_id": sample_id,
            "target_kind": target_kind,
            "target_id": target_id,
            "rt": self.rt.value(),
            "ri": self._ri,
            "user_name": self.user.text().strip(),
            "note": self.note.toPlainText().strip(),
            "evidence": "人工登记未知峰",
        }


class LibraryAddDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("加入自建谱库")
        layout = QVBoxLayout(self)
        note = QLabel("这只保存一条参考谱。它不会把当前样品峰确认成该化合物。")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.name = QLineEdit()
        self.cas = QLineEdit()
        self.formula = QLineEdit()
        self.ri = QLineEdit()
        self.notes = QPlainTextEdit()
        self.synthetic = QCheckBox("这是合成或练习用谱图")
        form.addRow("名称", self.name)
        form.addRow("CAS", self.cas)
        form.addRow("分子式", self.formula)
        form.addRow("保留指数（可空）", self.ri)
        form.addRow("备注", self.notes)
        form.addRow(self.synthetic)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict:
        ri_text = self.ri.text().strip()
        return {
            "name": self.name.text().strip(),
            "cas": self.cas.text().strip(),
            "formula": self.formula.text().strip(),
            "ri": float(ri_text) if ri_text else None,
            "notes": self.notes.toPlainText().strip(),
            "is_synthetic": self.synthetic.isChecked(),
        }


class CalibrationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("烷烃校正（程序升温 RI）")
        self.resize(520, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("van den Dool–Kratz。碳数和保留时间都要按出峰顺序增加。"))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["碳数", "RT (min)", "名称"])
        layout.addWidget(self.table)
        self.cal_name = QLineEdit("正构烷烃")
        buttons = QHBoxLayout()
        add = QPushButton("添加一行")
        remove = QPushButton("删除选中")
        load = QPushButton("从 CSV 读入")
        add.clicked.connect(lambda: self._add())
        remove.clicked.connect(self._remove)
        load.clicked.connect(self._load)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addWidget(load)
        layout.addLayout(buttons)
        layout.addWidget(QLabel("校正名称"))
        layout.addWidget(self.cal_name)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
        for carbon, rt in ((8, 3.2), (9, 4.1), (10, 5.0)):
            self._add(carbon, rt, f"n-C{carbon}")

    def _add(self, carbon="", rt="", name=""):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, _item(carbon))
        self.table.setItem(row, 1, _item(rt))
        self.table.setItem(row, 2, _item(name))

    def _remove(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(self, "烷烃 CSV", "", "CSV (*.csv *.txt)")
        if not path:
            return
        points = parse_alkane_csv(Path(path).read_text(encoding="utf-8"))
        self.table.setRowCount(0)
        for point in points:
            self._add(point.carbon_number, point.rt, point.name)

    def points(self) -> list[dict]:
        rows = []
        for row in range(self.table.rowCount()):
            carbon = self.table.item(row, 0)
            rt = self.table.item(row, 1)
            name = self.table.item(row, 2)
            if not carbon or not rt or not carbon.text().strip():
                continue
            rows.append(
                {
                    "carbon_number": int(float(carbon.text())),
                    "rt": float(rt.text()),
                    "name": "" if name is None else name.text().strip(),
                }
            )
        return rows


class SearchDialog(QDialog):
    def __init__(self, kb, parent=None):
        super().__init__(parent)
        self.kb = kb
        self.setWindowTitle("检索")
        self.resize(760, 520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.ions = QLineEdit()
        self.name = QLineEdit()
        self.cas = QLineEdit()
        self.sample = QLineEdit()
        self.rt_min = QLineEdit()
        self.rt_max = QLineEdit()
        self.ri_min = QLineEdit()
        self.ri_max = QLineEdit()
        form.addRow("特征离子，逗号分隔", self.ions)
        form.addRow("名称", self.name)
        form.addRow("CAS", self.cas)
        form.addRow("样品编号", self.sample)
        form.addRow("RT 起 / 止", self._pair(self.rt_min, self.rt_max))
        form.addRow("RI 起 / 止", self._pair(self.ri_min, self.ri_max))
        layout.addLayout(form)
        go = QPushButton("检索")
        go.clicked.connect(self.run)
        layout.addWidget(go)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["层", "摘要"])
        layout.addWidget(self.tree)
        layout.addWidget(QLabel("谱库候选和确认结论分列。检索不会把候选改成确认。"))

    def _pair(self, left, right) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(left)
        layout.addWidget(right)
        return widget

    def _optional(self, text: str):
        text = text.strip()
        return float(text) if text else None

    def run(self):
        ions = []
        raw = self.ions.text().strip()
        if raw:
            ions = [float(part) for part in raw.replace("，", ",").split(",") if part.strip()]
        found = self.kb.search(
            ions=ions,
            name=self.name.text(),
            cas=self.cas.text(),
            sample_code=self.sample.text(),
            rt_min=self._optional(self.rt_min.text()),
            rt_max=self._optional(self.rt_max.text()),
            ri_min=self._optional(self.ri_min.text()),
            ri_max=self._optional(self.ri_max.text()),
        )
        self.tree.clear()
        for layer, rows in found.items():
            parent = QTreeWidgetItem([layer, f"{len(rows)} 条"])
            self.tree.addTopLevelItem(parent)
            for row in rows[:200]:
                summary = " ".join(
                    str(row.get(key))
                    for key in ("sample_code", "name", "kind", "rt", "detail", "label")
                    if row.get(key) not in (None, "")
                )
                parent.addChild(QTreeWidgetItem([layer, summary]))
            parent.setExpanded(True)


class CompareDialog(QDialog):
    def __init__(self, kb, parent=None):
        super().__init__(parent)
        self.kb = kb
        self.setWindowTitle("与历史样品比较")
        self.resize(900, 640)
        layout = QVBoxLayout(self)
        self.checks = QTableWidget(0, 2)
        self.checks.setHorizontalHeaderLabels(["选择", "样品"])
        samples = kb.list_samples()
        self.samples = samples
        self.checks.setRowCount(len(samples))
        for row, sample in enumerate(samples):
            mark = QTableWidgetItem()
            mark.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            mark.setCheckState(Qt.Unchecked)
            self.checks.setItem(row, 0, mark)
            self.checks.setItem(row, 1, _item(f"{sample['id']}  {sample['sample_code']}"))
        layout.addWidget(self.checks)
        self.normalize = QCheckBox("色谱按最大值归一化（只比较形状，面积以峰表为准）")
        self.normalize.setChecked(True)
        layout.addWidget(self.normalize)
        button = QPushButton("叠加并比较峰表")
        button.clicked.connect(self.run)
        layout.addWidget(button)
        self.plot = ChromPlot()
        layout.addWidget(self.plot, stretch=1)
        self.table = QTableWidget(0, 1)
        layout.addWidget(self.table)

    def run(self):
        ids = []
        for row, sample in enumerate(self.samples):
            if self.checks.item(row, 0).checkState() == Qt.Checked:
                ids.append(sample["id"])
        if len(ids) < 2:
            QMessageBox.information(self, "比较", "请至少选择两个样品。")
            return
        result = self.kb.compare_samples(ids)
        colors = ["#1d4ed8", "#b45309", "#047857", "#7c3aed", "#be123c"]
        curves = []
        headers = ["RT 组"]
        for index, chrom in enumerate(result["chromatograms"]):
            y = np.asarray(chrom["tic"], dtype=float)
            if self.normalize.isChecked() and y.size and float(np.max(y)) > 0:
                y = y / float(np.max(y))
            curves.append((chrom["rt"], y, pg.mkPen(colors[index % len(colors)], width=1.6), chrom["sample_code"]))
            headers.append(chrom["sample_code"])
        self.plot.set_curves(curves)
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        aligned = result["aligned"]
        self.table.setRowCount(len(aligned))
        for row, cluster in enumerate(aligned):
            self.table.setItem(row, 0, _item(f"{cluster['rt_anchor']:.4f}"))
            for index, sample_id in enumerate(ids):
                peak = cluster["by_sample"].get(index)
                text = "" if peak is None else f"面积 {peak['area']:.4g}"
                self.table.setItem(row, index + 1, _item(text))


class TextDialog(QDialog):
    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 560)
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setMarkdown(text)
        layout.addWidget(browser)


class AboutDialog(QDialog):
    def __init__(self, data_dir: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关于")
        layout = QVBoxLayout(self)
        label = QLabel(
            f"GCMS 谱图知识库 {__version__}\n\n"
            f"{DISCLAIMER}\n\n"
            "RawFileReader reading tool. Copyright © 2016 by Thermo Fisher Scientific, Inc. "
            "All rights reserved.\n"
            "本程序不附带 Thermo RawFileReader。上面这行只在你自行安装并使用 RawFileReader 时适用。\n\n"
            "界面使用 PySide6 / Qt，按 LGPL 方式随目录分发，可以用兼容版本替换 Qt 动态库。\n"
            f"数据目录：{data_dir}"
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


def choose_open_files(parent, title: str, file_filter: str) -> list[Path]:
    paths, _ = QFileDialog.getOpenFileNames(parent, title, "", file_filter)
    return [Path(path) for path in paths]


def choose_save(parent, title: str, file_filter: str) -> Path | None:
    path, _ = QFileDialog.getSaveFileName(parent, title, "", file_filter)
    return Path(path) if path else None
