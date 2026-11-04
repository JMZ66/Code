"""简体中文主窗口。原始信号、算法结果、谱库候选和人工结论分开显示。"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from lcms_kb.core.adducts import ADDUCTS, ASSISTANCE_BANNER, adduct_by_name, adduct_table, theoretical_mz
from lcms_kb.core.chromatogram import bpc, eic, nearest_scan, subtract_trace, tic
from lcms_kb.core.isotopes import overlay_on_spectrum, theoretical_isotope_pattern
from lcms_kb.core.masscalc import da_error, ppm_error
from lcms_kb.core.models import SAMPLE_TYPE_ZH, SAMPLE_TYPES
from lcms_kb.core.qc import blank_flag, drift_report, pearson
from lcms_kb.core.readers import read_run, read_scan_at
from lcms_kb.core.similarity import modified_cosine
from lcms_kb.db.database import Database
from lcms_kb.errors import LCMSError
from lcms_kb.paths import app_home, database_path, font_path
from lcms_kb.services.backup import create_backup, restore_backup, verify_backup_file
from lcms_kb.services.conclusions import confirm, list_conclusions, record_algorithm, record_candidate, reject
from lcms_kb.services.importer import get_dataset, import_open_file, list_datasets, scans_for, update_sample_meta
from lcms_kb.services.library import add_entry, entry_peaks, export_library, import_library_file, list_entries
from lcms_kb.services.reports import export_excel, export_pdf
from lcms_kb.services.search import search_archive_ions, search_library
from lcms_kb.services.settings import Settings
from lcms_kb.vendor.external_tools import launch_tool
from lcms_kb.vendor.msconvert import MsConvertAdapter
from lcms_kb.vendor.registry import hint_for
from lcms_kb.vendor.thermo import ThermoRawFileParserAdapter
from lcms_kb.version import __version__

BANNER = (
    "四层结果分开存放：原始信号、算法结果、谱库候选（未确认）、人工确认结论。"
    "相似度和 ppm 误差都不是化合物鉴定。"
)
TYPE_BY_ZH = {label: key for key, label in SAMPLE_TYPE_ZH.items()}


def _configure_matplotlib():
    import matplotlib
    matplotlib.use("QtAgg")
    from matplotlib import font_manager
    path = font_path()
    if path.is_file():
        try:
            font_manager.fontManager.addfont(str(path))
            matplotlib.rcParams["font.sans-serif"] = ["WenQuanYi Micro Hei", "DejaVu Sans"]
            matplotlib.rcParams["axes.unicode_minus"] = False
        except Exception:
            matplotlib.rcParams["axes.unicode_minus"] = False


class Plot(QWidget):
    """色谱或质谱图。点击色谱时回调保留时间。"""

    def __init__(self, on_click=None):
        super().__init__()
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
        from matplotlib.figure import Figure

        self.on_click = on_click
        self.figure = Figure(figsize=(6, 3.2), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.axes = self.figure.add_subplot(111)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        self.canvas.mpl_connect("button_press_event", self._clicked)
        self._series = []

    def clear(self, title: str = "") -> None:
        self.axes.clear()
        self._series = []
        if title:
            self.axes.set_title(title)
        self.canvas.draw_idle()

    def add_line(self, x, y, label: str) -> None:
        line, = self.axes.plot(x, y, label=label)
        self._series.append(line)
        self.axes.legend(fontsize=8)
        self.canvas.draw_idle()

    def add_sticks(self, mz, intensity, label: str, color: str = "C0") -> None:
        if len(mz) == 0:
            return
        self.axes.vlines(mz, 0, intensity, colors=color, label=label)
        self.axes.legend(fontsize=8)
        self.canvas.draw_idle()

    def _clicked(self, event) -> None:
        if self.on_click and event.xdata is not None and event.button == 1 and self.toolbar.mode == "":
            self.on_click(float(event.xdata))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        _configure_matplotlib()
        self.home = app_home()
        self.db = Database(database_path())
        self.settings = Settings(self.db)
        self.scan_cache: dict[int, list] = {}
        self.current_scan = None
        self.current_dataset_id: int | None = None
        self.setWindowTitle(f"LCMS 知识库 {__version__}")
        self.resize(1280, 820)

        self.nav = QListWidget()
        self.stack = QStackedWidget()
        self.pages = {}
        builders = [
            ("导入", self._build_import),
            ("色谱图", self._build_chromatogram),
            ("质谱", self._build_spectrum),
            ("精确质量", self._build_mass),
            ("MS/MS", self._build_msms),
            ("谱库", self._build_library),
            ("检索", self._build_search),
            ("空白与QC", self._build_qc),
            ("结论", self._build_conclusions),
            ("报告", self._build_reports),
            ("备份", self._build_backup),
            ("设置", self._build_settings),
        ]
        for title, builder in builders:
            self.nav.addItem(title)
            page = builder()
            self.pages[title] = page
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.currentRowChanged.connect(self._on_page)
        self.nav.setCurrentRow(0)
        self.nav.setFixedWidth(140)

        banner = QLabel(BANNER)
        banner.setWordWrap(True)
        banner.setObjectName("layerBanner")
        splitter = QSplitter()
        splitter.addWidget(self.nav)
        splitter.addWidget(self.stack)
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.addWidget(banner)
        layout.addWidget(splitter)
        self.setCentralWidget(wrapper)
        self.statusBar().showMessage(self._status_text())

    def _status_text(self) -> str:
        return f"版本 {__version__}    操作者 {self.settings.operator()}    数据目录 {self.home}"

    def _on_page(self, _index: int) -> None:
        title = self.nav.currentItem().text() if self.nav.currentItem() else ""
        if title in {"导入", "色谱图", "MS/MS", "空白与QC"}:
            self._fill_datasets()
        if title == "谱库":
            self._refresh_谱库()
        if title == "结论":
            self._refresh_结论()

    def _error(self, exc: Exception) -> None:
        QMessageBox.warning(self, "无法完成", str(exc))

    def _guard(self, func):
        try:
            func()
        except Exception as exc:
            self._error(exc)

    # ----- 导入 -----
    def _build_import(self) -> QWidget:
        page = QWidget()
        self.import_table = QTableWidget(0, 5)
        self.import_table.setHorizontalHeaderLabels(["文件", "样品名", "类型", "重复组", "进样序号"])
        self.import_button = QPushButton("开始导入")
        self.import_button.setObjectName("importButton")
        self.import_button.clicked.connect(lambda: self._guard(self.import_queued))
        add = QPushButton("添加 mzML / mzXML")
        add.clicked.connect(self._pick_open_files)
        raw = QPushButton("用外部程序转换厂商原始数据")
        raw.clicked.connect(lambda: self._guard(self._convert_vendor))
        self.import_log = QTextEdit()
        self.import_log.setReadOnly(True)
        self.dataset_table = QTableWidget(0, 6)
        self.dataset_table.setHorizontalHeaderLabels(["id", "样品", "类型", "谱图数", "厂商推断", "说明"])
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(raw)
        row.addWidget(self.import_button)
        layout.addLayout(row)
        layout.addWidget(QLabel("待导入（原始文件只读，索引写在本程序数据目录）"))
        layout.addWidget(self.import_table)
        layout.addWidget(QLabel("已入库"))
        layout.addWidget(self.dataset_table)
        layout.addWidget(self.import_log)
        return page

    def _pick_open_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "选择开放格式", "", "质谱 (*.mzML *.mzml *.mzXML *.mzxml)")
        for path in paths:
            self.queue_file(Path(path))

    def queue_file(self, path: Path, sample_name: str = "", sample_type: str = "unknown",
                   replicate_group: str = "", inject_order: str = "") -> None:
        row = self.import_table.rowCount()
        self.import_table.insertRow(row)
        self.import_table.setItem(row, 0, QTableWidgetItem(str(path)))
        self.import_table.setItem(row, 1, QTableWidgetItem(sample_name or path.stem))
        combo = QComboBox()
        for key in SAMPLE_TYPES:
            combo.addItem(SAMPLE_TYPE_ZH[key], key)
        combo.setCurrentIndex(SAMPLE_TYPES.index(sample_type))
        self.import_table.setCellWidget(row, 2, combo)
        self.import_table.setItem(row, 3, QTableWidgetItem(replicate_group))
        self.import_table.setItem(row, 4, QTableWidgetItem(inject_order))

    def import_queued(self) -> None:
        operator = self.settings.operator()
        done = 0
        for row in range(self.import_table.rowCount()):
            path = Path(self.import_table.item(row, 0).text())
            name = self.import_table.item(row, 1).text()
            combo = self.import_table.cellWidget(row, 2)
            sample_type = combo.currentData()
            group = self.import_table.item(row, 3).text()
            order_text = self.import_table.item(row, 4).text().strip()
            order = int(order_text) if order_text else None
            dataset_id = import_open_file(
                self.db, path, operator=operator, sample_name=name, sample_type=sample_type,
                replicate_group=group, inject_order=order,
            )
            record = get_dataset(self.db, dataset_id)
            note = "文件标记为测试用合成数据，不是采集谱图" if record["test_only_synthetic"] else "已索引原始文件，未改写"
            self.import_log.append(f"已导入 #{dataset_id} {path.name}。{note}。SHA-256 {record['sha256'][:16]}…")
            done += 1
        self.import_table.setRowCount(0)
        self._fill_datasets()
        self.statusBar().showMessage(f"导入 {done} 个文件。" + self._status_text())

    def _convert_vendor(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择厂商原始数据", "", "原始数据 (*.raw *.wiff *.wiff2 *.yep *.baf)")
        if not path:
            folder = QFileDialog.getExistingDirectory(self, "或选择 .d / 其他目录")
            if not folder:
                return
            path = folder
        source = Path(path)
        hint = hint_for(source.suffix)
        choice = QMessageBox.question(
            self, "选择转换程序",
            hint + "\n\n“是”使用 msconvert，“否”使用 ThermoRawFileParser。两者都需要您事先安装，本程序不附带厂商库。",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
        )
        if choice == QMessageBox.Cancel:
            return
        out = self.home / "converted" / source.stem
        out.mkdir(parents=True, exist_ok=True)
        if choice == QMessageBox.Yes:
            result = MsConvertAdapter().convert(source, out, executable=self.settings.get("msconvert_path"))
        else:
            result = ThermoRawFileParserAdapter().convert(source, out, executable=self.settings.get("thermo_parser_path"))
        for warning in result.warnings:
            self.import_log.append(warning)
        self.import_log.append(
            f"已转换到 {result.output_mzml}。原始文件哈希未变：{result.source_sha256_before == result.source_sha256_after}。"
        )
        self.queue_file(result.output_mzml)

    def _fill_datasets(self) -> None:
        rows = list_datasets(self.db)
        self.dataset_table.setRowCount(len(rows))
        for index, item in enumerate(rows):
            note = "测试用合成数据" if item["test_only_synthetic"] else ""
            values = [
                str(item["id"]), item["sample_name"] or "", SAMPLE_TYPE_ZH.get(item["sample_type"], item["sample_type"]),
                str(item["n_spectra"]), item["vendors_inferred"] or "未推断", note,
            ]
            for column, value in enumerate(values):
                self.dataset_table.setItem(index, column, QTableWidgetItem(value))
        if hasattr(self, "chroma_list"):
            self._fill_dataset_list(self.chroma_list)
        if hasattr(self, "msms_dataset"):
            self._fill_dataset_combo(self.msms_dataset)
        if hasattr(self, "qc_sample"):
            for combo in (self.qc_sample, self.qc_blank, self.qc_a, self.qc_b):
                self._fill_dataset_combo(combo)

    def _fill_dataset_list(self, widget: QListWidget) -> None:
        widget.clear()
        for item in list_datasets(self.db):
            label = f"#{item['id']} {item['sample_name']} ({SAMPLE_TYPE_ZH.get(item['sample_type'], item['sample_type'])})"
            widget.addItem(label)
            widget.item(widget.count() - 1).setData(Qt.UserRole, item["id"])

    def _fill_dataset_combo(self, combo: QComboBox) -> None:
        current = combo.currentData()
        combo.clear()
        for item in list_datasets(self.db):
            combo.addItem(f"#{item['id']} {item['sample_name']}", item["id"])
        if current is not None:
            index = combo.findData(current)
            if index >= 0:
                combo.setCurrentIndex(index)

    def dataset_count(self) -> int:
        return self.dataset_table.rowCount()

    # ----- 色谱 -----
    def _build_chromatogram(self) -> QWidget:
        page = QWidget()
        self.chroma_list = QListWidget()
        self.chroma_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.chroma_polarity = QComboBox()
        self.chroma_polarity.addItem("正离子", "positive")
        self.chroma_polarity.addItem("负离子", "negative")
        self.chroma_level = QComboBox()
        self.chroma_level.addItem("MS1", 1)
        self.chroma_level.addItem("MS2", 2)
        self.chroma_mode = QComboBox()
        self.chroma_mode.addItem("全扫描", "full_scan")
        self.chroma_mode.addItem("不按模式过滤", "")
        self.chroma_mode.addItem("SIM", "sim")
        self.chroma_mode.addItem("DDA", "dda")
        self.chroma_mode.addItem("DIA", "dia")
        self.chroma_kind = QComboBox()
        self.chroma_kind.addItem("TIC", "tic")
        self.chroma_kind.addItem("BPC", "bpc")
        self.chroma_kind.addItem("EIC", "eic")
        self.chroma_mz = QLineEdit("200")
        self.chroma_tol = QLineEdit("10")
        self.chroma_unit = QComboBox()
        self.chroma_unit.addItems(["ppm", "da"])
        button = QPushButton("绘制")
        button.setObjectName("plotChroma")
        button.clicked.connect(lambda: self._guard(self.plot_chromatograms))
        self.chroma_plot = Plot(self._chroma_clicked)
        form = QFormLayout()
        form.addRow("极性", self.chroma_polarity)
        form.addRow("级别", self.chroma_level)
        form.addRow("扫描模式", self.chroma_mode)
        form.addRow("曲线", self.chroma_kind)
        form.addRow("EIC m/z", self.chroma_mz)
        form.addRow("容差", self.chroma_tol)
        form.addRow("单位", self.chroma_unit)
        form.addRow(button)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("样品（可多选叠加，极性不会合并）"))
        left_layout.addWidget(self.chroma_list)
        left_layout.addLayout(form)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.chroma_plot)
        layout = QVBoxLayout(page)
        layout.addWidget(split)
        return page

    def _selected_dataset_ids(self) -> list[int]:
        return [item.data(Qt.UserRole) for item in self.chroma_list.selectedItems()]

    def _scans(self, dataset_id: int):
        if dataset_id not in self.scan_cache:
            record = get_dataset(self.db, dataset_id)
            if record is None:
                raise LCMSError("数据集不存在")
            path = Path(record["source_path"])
            from lcms_kb.hashing import sha256_file
            current = sha256_file(path)
            if current != record["sha256"]:
                raise LCMSError("原始文件哈希与导入时不同，已停止读取。")
            _header, scans = read_run(path)
            self.scan_cache[dataset_id] = scans
        return self.scan_cache[dataset_id]

    def plot_chromatograms(self) -> None:
        ids = self._selected_dataset_ids()
        if not ids:
            raise LCMSError("请先选择至少一个数据集。")
        polarity = self.chroma_polarity.currentData()
        level = int(self.chroma_level.currentData())
        mode = self.chroma_mode.currentData()
        modes = {mode} if mode else None
        kind = self.chroma_kind.currentData()
        self.chroma_plot.clear("原始信号" if kind != "eic" else "EIC（原始信号，只累加窗口内的峰）")
        self.chroma_plot.axes.set_xlabel("保留时间 (min)")
        self.chroma_plot.axes.set_ylabel("强度")
        self._chroma_context = (ids, polarity, level, modes)
        for dataset_id in ids:
            scans = self._scans(dataset_id)
            record = get_dataset(self.db, dataset_id)
            label = record["sample_name"] or record["file_name"]
            if record["test_only_synthetic"]:
                label += "（测试合成）"
            if kind == "tic":
                trace = tic(scans, polarity=polarity, ms_level=level, scan_modes=modes)
            elif kind == "bpc":
                trace = bpc(scans, polarity=polarity, ms_level=level, scan_modes=modes)
            else:
                trace = eic(
                    scans, float(self.chroma_mz.text()), float(self.chroma_tol.text()),
                    self.chroma_unit.currentText(), polarity=polarity, ms_level=level, scan_modes=modes,
                )
            self.chroma_plot.add_line(trace.rt_min, trace.intensity, f"{label} {trace.label}")

    def _chroma_clicked(self, rt_min: float) -> None:
        context = getattr(self, "_chroma_context", None)
        if not context:
            return
        dataset_id = context[0][0]
        polarity, level, modes = context[1], context[2], context[3]
        scans = self._scans(dataset_id)
        scan = nearest_scan(scans, rt_min, polarity=polarity, ms_level=1 if level != 1 else 1, scan_modes=modes if level == 1 else None)
        if scan is None:
            scan = nearest_scan(scans, rt_min, polarity=polarity, ms_level=1)
        if scan is None:
            return
        self.current_dataset_id = dataset_id
        self.current_scan = scan
        self.show_spectrum(dataset_id, scan)
        self.nav.setCurrentRow(2)

    def show_spectrum(self, dataset_id: int, scan) -> None:
        record = get_dataset(self.db, dataset_id)
        synthetic = "这张谱来自测试用合成文件，不是采集数据。" if record["test_only_synthetic"] else "峰来自原始文件，未改写。"
        text = (
            f"数据集 #{dataset_id} {record['file_name']}  扫描 {scan.scan_number}  "
            f"{scan.polarity_zh}  MS{scan.ms_level}  {scan.scan_mode_zh}  "
            f"RT {scan.rt_min} min  前体 {scan.precursor_mz}  CE {scan.collision_energy}  {scan.activation or ''}\n"
            f"{synthetic} 依据：{scan.scan_mode_basis}"
        )
        self.spectrum_info.setText(text)
        self.spectrum_plot.clear("MS1 原始谱图" if scan.ms_level == 1 else "MS/MS 原始谱图")
        self.spectrum_plot.axes.set_xlabel("m/z")
        self.spectrum_plot.axes.set_ylabel("强度")
        self.spectrum_plot.add_sticks(scan.mz, scan.intensity, "原始峰")
        self.peak_table.setRowCount(min(len(scan.mz), 80))
        order = np.argsort(scan.intensity)[::-1][:80]
        for row, index in enumerate(order):
            self.peak_table.setItem(row, 0, QTableWidgetItem(f"{scan.mz[index]:.6f}"))
            self.peak_table.setItem(row, 1, QTableWidgetItem(f"{scan.intensity[index]:.6g}"))

    # ----- 质谱 -----
    def _build_spectrum(self) -> QWidget:
        page = QWidget()
        self.spectrum_info = QLabel("在色谱图上点击一个时间点，这里显示该时间最近的 MS1。")
        self.spectrum_info.setWordWrap(True)
        self.spectrum_plot = Plot()
        self.peak_table = QTableWidget(0, 2)
        self.peak_table.setHorizontalHeaderLabels(["m/z", "强度"])
        layout = QVBoxLayout(page)
        layout.addWidget(self.spectrum_info)
        layout.addWidget(self.spectrum_plot, 2)
        layout.addWidget(self.peak_table, 1)
        return page

    # ----- 精确质量 -----
    def _build_mass(self) -> QWidget:
        page = QWidget()
        self.formula_edit = QLineEdit("C8H10N4O2")
        self.formula_edit.setObjectName("formulaEdit")
        self.adduct_combo = QComboBox()
        for spec in ADDUCTS:
            self.adduct_combo.addItem(f"{spec.name} {spec.note}", spec.name)
        self.observed_edit = QLineEdit("")
        self.mass_button = QPushButton("计算理论 m/z、ppm 和同位素")
        self.mass_button.setObjectName("massButton")
        self.mass_button.clicked.connect(lambda: self._guard(self.compute_mass))
        self.mass_output = QTextEdit()
        self.mass_output.setReadOnly(True)
        self.mass_output.setObjectName("massOutput")
        self.isotope_plot = Plot()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        form.addRow("分子式", self.formula_edit)
        form.addRow("加合离子", self.adduct_combo)
        form.addRow("观测 m/z（可空）", self.observed_edit)
        layout.addLayout(form)
        layout.addWidget(self.mass_button)
        layout.addWidget(QLabel(ASSISTANCE_BANNER))
        layout.addWidget(self.mass_output)
        layout.addWidget(self.isotope_plot)
        return page

    def compute_mass(self) -> None:
        formula = self.formula_edit.text().strip()
        adduct = adduct_by_name(self.adduct_combo.currentData())
        theo = theoretical_mz(formula, adduct)
        lines = [
            f"分子式 {formula}  {adduct.name}  理论 m/z {theo:.6f}",
            "这是由分子式计算的理论值，不是采集到的峰，也不是鉴定。",
        ]
        observed_text = self.observed_edit.text().strip()
        observed = None
        if observed_text:
            observed = float(observed_text)
            lines.append(
                f"观测 m/z {observed:.6f}  Δm {da_error(observed, theo):.6f} Da  "
                f"ppm {ppm_error(observed, theo):.3f}"
            )
            lines.append("ppm 误差只说明质量和理论值差多少，不能据此确认化合物。")
        peaks = []
        if self.current_scan is not None and self.current_scan.ms_level == 1 and self.current_scan.mz.size:
            peaks = list(zip(self.current_scan.mz.tolist(), self.current_scan.intensity.tolist()))
        rows = adduct_table(formula, peaks or None, polarity=adduct.polarity)
        lines.append("加合离子与源内丢失提示（辅助，非鉴定）：")
        for row in rows:
            extra = ""
            if row.ppm_error is not None:
                extra = f"  最近实测峰 {row.nearest_observed_mz:.4f}  ppm {row.ppm_error:.2f}"
            lines.append(f"  {row.name}  {row.note}  理论 {row.theoretical_mz:.4f}{extra}")
        pattern = theoretical_isotope_pattern(formula, adduct)
        lines.append(pattern.banner)
        self.mass_output.setPlainText("\n".join(lines))
        self.isotope_plot.clear("理论同位素（棒）与当前 MS1（若已选择）")
        self.isotope_plot.axes.set_xlabel("m/z")
        if self.current_scan is not None and self.current_scan.ms_level == 1:
            self.isotope_plot.add_sticks(self.current_scan.mz, self.current_scan.intensity, "实测 MS1", "0.6")
            window = 0.5
            center = pattern.peaks[0].mz
            self.isotope_plot.axes.set_xlim(center - 1, center + 5)
        mz = [peak.mz for peak in pattern.peaks]
        inten = [peak.relative_abundance for peak in pattern.peaks]
        self.isotope_plot.add_sticks(mz, inten, "理论分布（归一化到 100）", "C3")
        if self.current_dataset_id is not None:
            record_algorithm(
                self.db, operator=self.settings.operator(), dataset_id=self.current_dataset_id,
                summary="理论质量与同位素",
                detail={"formula": formula, "adduct": adduct.name, "theoretical_mz": theo, "observed": observed},
                source_sha256=(get_dataset(self.db, self.current_dataset_id) or {}).get("sha256", ""),
            )

    # ----- MS/MS -----
    def _build_msms(self) -> QWidget:
        page = QWidget()
        self.msms_dataset = QComboBox()
        self.msms_list = QListWidget()
        self.msms_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.msms_library = QComboBox()
        self.msms_allow = QCheckBox("允许比较不同极性或不同碰撞能量（必须勾选才会混合）")
        load = QPushButton("列出该样品的 MS/MS")
        load.clicked.connect(lambda: self._guard(self._load_msms))
        compare = QPushButton("比较选中的两条谱，或一条谱对谱库")
        compare.clicked.connect(lambda: self._guard(self._compare_msms))
        save = QPushButton("把选中的一条谱存入谱库")
        save.clicked.connect(lambda: self._guard(self._save_msms_to_library))
        self.msms_name = QLineEdit()
        self.msms_output = QTextEdit()
        self.msms_output.setReadOnly(True)
        self.msms_plot = Plot()
        layout = QVBoxLayout(page)
        layout.addWidget(self.msms_dataset)
        layout.addWidget(load)
        layout.addWidget(self.msms_list)
        layout.addWidget(QLabel("和谱库比较时使用这一条（只选一条实测谱时）"))
        layout.addWidget(self.msms_library)
        layout.addWidget(self.msms_allow)
        layout.addWidget(QLabel("存入谱库时的化合物名"))
        layout.addWidget(self.msms_name)
        row = QHBoxLayout()
        row.addWidget(compare)
        row.addWidget(save)
        layout.addLayout(row)
        layout.addWidget(self.msms_output)
        layout.addWidget(self.msms_plot)
        return page

    def _load_msms(self) -> None:
        dataset_id = self.msms_dataset.currentData()
        self.msms_list.clear()
        self.msms_library.clear()
        for entry in list_entries(self.db):
            self.msms_library.addItem(
                f"#{entry['id']} {entry.get('compound_name') or ''} {entry.get('polarity') or ''} CE {entry.get('collision_energy')}",
                entry["id"],
            )
        if dataset_id is None:
            return
        for row in scans_for(self.db, int(dataset_id), ms_level=2):
            text = (
                f"扫描 {row['scan_number']}  {row['polarity']}  {row['scan_mode']}  "
                f"前体 {row['precursor_mz']}  CE {row['collision_energy']}  {row['activation'] or ''}"
            )
            self.msms_list.addItem(text)
            self.msms_list.item(self.msms_list.count() - 1).setData(Qt.UserRole, row)

    def _selected_msms_scans(self):
        dataset_id = int(self.msms_dataset.currentData())
        scans = self._scans(dataset_id)
        by_number = {scan.scan_number: scan for scan in scans}
        chosen = []
        for item in self.msms_list.selectedItems():
            row = item.data(Qt.UserRole)
            chosen.append(by_number[row["scan_number"]])
        return dataset_id, chosen

    def _compare_msms(self) -> None:
        dataset_id, chosen = self._selected_msms_scans()
        if len(chosen) == 1:
            entry_id = self.msms_library.currentData()
            if entry_id is None:
                raise LCMSError("只选了一条谱，请先在谱库中选择对照条目。")
            entry = next(item for item in list_entries(self.db) if item["id"] == entry_id)
            mz, intensity = entry_peaks(self.db, entry["id"])
            other_polarity = entry.get("polarity")
            other_energy = entry.get("collision_energy")
            other_mz, other_i = mz, intensity
            other_precursor = entry.get("precursor_mz") or chosen[0].precursor_mz
            other_label = f"谱库 #{entry['id']} {entry.get('compound_name') or ''}"
        elif len(chosen) >= 2:
            entry = None
            other_polarity = chosen[1].polarity
            other_energy = chosen[1].collision_energy
            other_mz, other_i = chosen[1].mz, chosen[1].intensity
            other_precursor = chosen[1].precursor_mz
            other_label = f"扫描 {chosen[1].scan_number}"
        else:
            raise LCMSError("请选择一条或两条 MS/MS。")
        allow = self.msms_allow.isChecked()
        result = modified_cosine(
            chosen[0].mz, chosen[0].intensity, chosen[0].precursor_mz or 0,
            other_mz, other_i, other_precursor or 0,
            polarity_a=chosen[0].polarity, polarity_b=other_polarity,
            energy_a=chosen[0].collision_energy, energy_b=other_energy,
            allow_polarity_mismatch=allow, allow_energy_mismatch=allow,
        )
        self.msms_output.setPlainText(
            f"修正余弦 {result.score:.4f}，匹配峰 {result.matches}。\n{result.banner}\n"
            f"左侧扫描 {chosen[0].scan_number} {chosen[0].polarity_zh} CE {chosen[0].collision_energy}\n"
            f"右侧 {other_label}"
        )
        self.msms_plot.clear("MS/MS 原始谱图对照")
        self.msms_plot.add_sticks(chosen[0].mz, chosen[0].intensity, f"扫描 {chosen[0].scan_number}")
        self.msms_plot.add_sticks(np.asarray(other_mz, dtype=float), -np.asarray(other_i, dtype=float), other_label, "C1")
        record_algorithm(
            self.db, operator=self.settings.operator(), dataset_id=dataset_id,
            summary="MS/MS 相似度",
            detail={"score": result.score, "matches": result.matches, "allow_mix": allow},
            source_sha256=get_dataset(self.db, dataset_id)["sha256"],
        )

    def _save_msms_to_library(self) -> None:
        dataset_id, chosen = self._selected_msms_scans()
        if len(chosen) != 1:
            raise LCMSError("保存到谱库时请只选择一条谱。")
        scan = chosen[0]
        record = get_dataset(self.db, dataset_id)
        name = self.msms_name.text().strip() or record["sample_name"] or "未命名"
        entry_type = "standard" if record["sample_type"] == "standard" else "historical"
        add_entry(
            self.db, entry_type=entry_type, compound_name=name, operator=self.settings.operator(),
            polarity=scan.polarity, rt_min=scan.rt_min, precursor_mz=scan.precursor_mz,
            collision_energy=scan.collision_energy, activation=scan.activation or "",
            scan_mode=scan.scan_mode, source_dataset_id=dataset_id, source_scan_number=scan.scan_number,
            source_sha256=record["sha256"],
            notes=("测试用合成谱，" if record["test_only_synthetic"] else "") + "从原始文件提取的实测 MS/MS",
            mz=scan.mz, intensity=scan.intensity,
        )
        self.msms_output.setPlainText(f"已存入谱库（{entry_type}）：{name}。这不是确认结论。")

    # ----- 谱库 -----
    def _build_library(self) -> QWidget:
        page = QWidget()
        self.library_table = QTableWidget(0, 7)
        self.library_table.setHorizontalHeaderLabels(["id", "类型", "名称", "分子式", "加合", "极性", "CE"])
        imp = QPushButton("导入 MSP/MGF")
        imp.clicked.connect(lambda: self._guard(self._import_library))
        exp = QPushButton("导出 MSP")
        exp.clicked.connect(lambda: self._guard(self._export_library))
        self.library_type = QComboBox()
        self.library_type.addItem("历史样品谱图", "historical")
        self.library_type.addItem("标准品", "standard")
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("谱库条目是候选来源。检索结果仍标为“谱库候选（未确认）”。"))
        layout.addWidget(self.library_type)
        row = QHBoxLayout()
        row.addWidget(imp)
        row.addWidget(exp)
        layout.addLayout(row)
        layout.addWidget(self.library_table)
        return page

    def _refresh_谱库(self) -> None:
        rows = list_entries(self.db)
        self.library_table.setRowCount(len(rows))
        for index, item in enumerate(rows):
            values = [item["id"], item["entry_type"], item["compound_name"], item["formula"], item["adduct"], item["polarity"], item["collision_energy"]]
            for column, value in enumerate(values):
                self.library_table.setItem(index, column, QTableWidgetItem("" if value is None else str(value)))

    def _import_library(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入谱库", "", "谱库 (*.msp *.mgf *.MSP *.MGF)")
        if not path:
            return
        count = import_library_file(self.db, path, operator=self.settings.operator(), entry_type=self.library_type.currentData())
        self._refresh_谱库()
        QMessageBox.information(self, "导入完成", f"读入 {count} 条谱图。")

    def _export_library(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出 MSP", str(self.home / "exports" / "library.msp"), "MSP (*.msp)")
        if not path:
            return
        count = export_library(self.db, path)
        QMessageBox.information(self, "导出完成", f"写出 {count} 条到 {path}")

    # ----- 检索 -----
    def _build_search(self) -> QWidget:
        page = QWidget()
        self.search_name = QLineEdit()
        self.search_formula = QLineEdit()
        self.search_mz = QLineEdit()
        self.search_ppm = QLineEdit("10")
        self.search_rt1 = QLineEdit()
        self.search_rt2 = QLineEdit()
        self.search_frag = QLineEdit()
        self.search_polarity = QComboBox()
        self.search_polarity.addItem("不限极性", "")
        self.search_polarity.addItem("正离子", "positive")
        self.search_polarity.addItem("负离子", "negative")
        button = QPushButton("检索")
        button.clicked.connect(lambda: self._guard(self._run_search))
        self.search_table = QTableWidget(0, 6)
        self.search_table.setHorizontalHeaderLabels(["层", "名称", "分子式", "前体 m/z", "极性", "CE"])
        mark = QPushButton("把选中行记为谱库候选（未确认）")
        mark.clicked.connect(lambda: self._guard(self._mark_candidate))
        layout = QVBoxLayout(page)
        form = QFormLayout()
        form.addRow("名称", self.search_name)
        form.addRow("分子式", self.search_formula)
        form.addRow("前体 m/z", self.search_mz)
        form.addRow("ppm", self.search_ppm)
        form.addRow("RT 起", self.search_rt1)
        form.addRow("RT 止", self.search_rt2)
        form.addRow("碎片 m/z", self.search_frag)
        form.addRow("极性", self.search_polarity)
        layout.addLayout(form)
        layout.addWidget(button)
        layout.addWidget(QLabel("检索命中只表示谱库候选（未确认），不会自动确认。"))
        layout.addWidget(self.search_table)
        layout.addWidget(mark)
        return page

    def _optional_float(self, text: str):
        text = text.strip()
        return float(text) if text else None

    def _run_search(self) -> None:
        polarity = self.search_polarity.currentData() or None
        rows = search_library(
            self.db,
            name=self.search_name.text(),
            formula=self.search_formula.text(),
            mz=self._optional_float(self.search_mz.text()),
            ppm=self._optional_float(self.search_ppm.text()),
            rt_min=self._optional_float(self.search_rt1.text()),
            rt_max=self._optional_float(self.search_rt2.text()),
            fragment_mz=self._optional_float(self.search_frag.text()),
            fragment_ppm=self._optional_float(self.search_ppm.text()),
            polarity=polarity,
        )
        if self.search_mz.text().strip():
            ions = search_archive_ions(
                self.db, float(self.search_mz.text()), ppm=float(self.search_ppm.text() or 10),
                polarity=polarity,
            )
        else:
            ions = []
        self._search_rows = rows
        self.search_table.setRowCount(len(rows) + len(ions))
        for index, item in enumerate(rows):
            values = [item["label_zh"], item.get("compound_name"), item.get("formula"), item.get("precursor_mz"), item.get("polarity"), item.get("collision_energy")]
            for column, value in enumerate(values):
                cell = QTableWidgetItem("" if value is None else str(value))
                cell.setData(Qt.UserRole, ("library", item["id"]))
                self.search_table.setItem(index, column, cell)
        offset = len(rows)
        for index, item in enumerate(ions):
            values = [item["label_zh"], item.get("sample_name"), "", item.get("mz"), item.get("polarity"), ""]
            for column, value in enumerate(values):
                self.search_table.setItem(offset + index, column, QTableWidgetItem("" if value is None else str(value)))

    def _mark_candidate(self) -> None:
        row = self.search_table.currentRow()
        if row < 0 or row >= len(getattr(self, "_search_rows", [])):
            raise LCMSError("请选择一条谱库命中。归档离子索引不能被确认为化合物。")
        item = self._search_rows[row]
        record_candidate(
            self.db, operator=self.settings.operator(), dataset_id=self.current_dataset_id,
            library_entry_id=item["id"], similarity=None, ppm_error=None,
            detail={"name": item.get("compound_name"), "formula": item.get("formula")},
            source_sha256=item.get("source_sha256") or "",
        )
        QMessageBox.information(self, "已记录", "已记为谱库候选（未确认）。要变成结论，请到“结论”页填写依据并确认。")

    # ----- QC -----
    def _build_qc(self) -> QWidget:
        page = QWidget()
        self.qc_sample = QComboBox()
        self.qc_blank = QComboBox()
        self.qc_mz = QLineEdit("200")
        self.qc_ppm = QLineEdit("10")
        self.qc_ratio = QLineEdit(self.settings.get("blank_ratio"))
        self.qc_polarity = QComboBox()
        self.qc_polarity.addItem("正离子", "positive")
        self.qc_polarity.addItem("负离子", "negative")
        blank_button = QPushButton("空白比对")
        blank_button.clicked.connect(lambda: self._guard(self._run_blank))
        self.qc_a = QComboBox()
        self.qc_b = QComboBox()
        rep_button = QPushButton("重复样品 TIC 相关")
        rep_button.clicked.connect(lambda: self._guard(self._run_replicate))
        self.qc_output = QTextEdit()
        self.qc_output.setReadOnly(True)
        type_button = QPushButton("把所选色谱样品的类型保存为当前下拉值")
        self.qc_type = QComboBox()
        for key in SAMPLE_TYPES:
            self.qc_type.addItem(SAMPLE_TYPE_ZH[key], key)
        type_button.clicked.connect(lambda: self._guard(self._save_type))
        layout = QVBoxLayout(page)
        form = QFormLayout()
        form.addRow("样品", self.qc_sample)
        form.addRow("空白", self.qc_blank)
        form.addRow("m/z", self.qc_mz)
        form.addRow("ppm", self.qc_ppm)
        form.addRow("空白/样品阈值", self.qc_ratio)
        form.addRow("极性", self.qc_polarity)
        form.addRow("新的样品类型", self.qc_type)
        layout.addLayout(form)
        layout.addWidget(blank_button)
        layout.addWidget(type_button)
        layout.addWidget(QLabel("重复或 QC：选择两条同极性数据，比较 MS1 全扫描 TIC。"))
        layout.addWidget(self.qc_a)
        layout.addWidget(self.qc_b)
        layout.addWidget(rep_button)
        layout.addWidget(self.qc_output)
        return page

    def _run_blank(self) -> None:
        sample_id = int(self.qc_sample.currentData())
        blank_id = int(self.qc_blank.currentData())
        polarity = self.qc_polarity.currentData()
        sample_trace = eic(self._scans(sample_id), float(self.qc_mz.text()), float(self.qc_ppm.text()), "ppm",
                           polarity=polarity, ms_level=1, scan_modes={"full_scan"})
        blank_trace = eic(self._scans(blank_id), float(self.qc_mz.text()), float(self.qc_ppm.text()), "ppm",
                          polarity=polarity, ms_level=1, scan_modes={"full_scan"})
        flag = blank_flag(sample_trace, blank_trace, ratio_threshold=float(self.qc_ratio.text()))
        self.qc_output.setPlainText(
            f"{flag.label}\n样品最高点 RT {flag.sample_apex_rt} 强度 {flag.sample_apex_intensity}\n"
            f"空白对应点 RT {flag.blank_apex_rt} 强度 {flag.blank_apex_intensity}\n"
            f"比值 {flag.ratio_blank_over_sample}  阈值 {flag.threshold}\n"
            "这是算法结果，原始文件没有被修改。"
        )
        record_algorithm(
            self.db, operator=self.settings.operator(), dataset_id=sample_id, summary=flag.label,
            detail={"ratio": flag.ratio_blank_over_sample, "blank_id": blank_id, "mz": float(self.qc_mz.text())},
            source_sha256=get_dataset(self.db, sample_id)["sha256"],
        )

    def _run_replicate(self) -> None:
        left_id = int(self.qc_a.currentData())
        right_id = int(self.qc_b.currentData())
        polarity = self.qc_polarity.currentData()
        left = tic(self._scans(left_id), polarity=polarity, ms_level=1, scan_modes={"full_scan"})
        right = tic(self._scans(right_id), polarity=polarity, ms_level=1, scan_modes={"full_scan"})
        if left.rt_min.shape != right.rt_min.shape or not np.allclose(left.rt_min, right.rt_min):
            raise LCMSError("两条 TIC 的保留时间点不一致，不做插值，因此不算相关。")
        value = pearson(left.intensity, right.intensity)
        points = []
        for dataset_id, trace in ((left_id, left), (right_id, right)):
            if trace.intensity.size:
                index = int(np.argmax(trace.intensity))
                points.append((float(trace.rt_min[index]), float(trace.intensity[index])))
        report = drift_report(points, name="重复/QC", rt_limit=float(self.settings.get("qc_rt_limit_min")),
                              rsd_limit=float(self.settings.get("qc_rsd_limit")))
        self.qc_output.setPlainText(
            f"TIC 皮尔逊相关：{value}\nRT 跨度 {report.rt_span}（阈值 {report.rt_limit}，超限 {report.rt_flag}）\n"
            f"强度 RSD {report.intensity_rsd}（阈值 {report.rsd_limit}，超限 {report.rsd_flag}）\n"
            f"{report.label}"
        )

    def _save_type(self) -> None:
        dataset_id = self.qc_sample.currentData()
        if dataset_id is None:
            raise LCMSError("没有可修改的数据集。")
        record = get_dataset(self.db, int(dataset_id))
        update_sample_meta(
            self.db, int(dataset_id), sample_name=record["sample_name"] or "",
            sample_type=self.qc_type.currentData(), replicate_group=record["replicate_group"] or "",
            inject_order=record["inject_order"], operator=self.settings.operator(),
        )
        self._fill_datasets()
        self.qc_output.setPlainText("样品类型已更新。这只改变标记，不改变原始文件。")

    # ----- 结论 -----
    def _build_conclusions(self) -> QWidget:
        page = QWidget()
        self.conclusion_table = QTableWidget(0, 6)
        self.conclusion_table.setHorizontalHeaderLabels(["id", "层", "状态", "标签", "相似度", "ppm"])
        self.basis_edit = QTextEdit()
        self.basis_edit.setPlaceholderText("确认或否定时必须填写依据，例如与哪支标准品、哪个 CE、哪张谱比较。")
        ok = QPushButton("人工确认")
        ok.setObjectName("confirmButton")
        ok.clicked.connect(lambda: self._guard(self._confirm))
        no = QPushButton("人工否定")
        no.clicked.connect(lambda: self._guard(self._reject))
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("只有这里的“人工确认”会把谱库候选变成结论。算法结果不能被确认成化合物。"))
        layout.addWidget(self.conclusion_table)
        layout.addWidget(self.basis_edit)
        row = QHBoxLayout()
        row.addWidget(ok)
        row.addWidget(no)
        layout.addLayout(row)
        return page

    def _refresh_结论(self) -> None:
        rows = list_conclusions(self.db)
        self.conclusion_table.setRowCount(len(rows))
        for index, item in enumerate(rows):
            values = [item["id"], item["layer"], item["status"], item["label_zh"], item["similarity"], item["ppm_error"]]
            for column, value in enumerate(values):
                self.conclusion_table.setItem(index, column, QTableWidgetItem("" if value is None else str(value)))

    def _selected_conclusion_id(self) -> int:
        row = self.conclusion_table.currentRow()
        if row < 0:
            raise LCMSError("请先选择一条记录。")
        return int(self.conclusion_table.item(row, 0).text())

    def _confirm(self) -> None:
        confirm(self.db, self._selected_conclusion_id(), operator=self.settings.operator(), basis=self.basis_edit.toPlainText())
        self._refresh_结论()

    def _reject(self) -> None:
        reject(self.db, self._selected_conclusion_id(), operator=self.settings.operator(), basis=self.basis_edit.toPlainText())
        self._refresh_结论()

    # ----- 报告 -----
    def _build_reports(self) -> QWidget:
        page = QWidget()
        excel = QPushButton("导出 Excel")
        excel.clicked.connect(lambda: self._guard(self._export_excel))
        pdf = QPushButton("导出 PDF")
        pdf.clicked.connect(lambda: self._guard(self._export_pdf))
        self.report_label = QLabel("报告会写明四层结果。候选和人工结论分表。")
        self.report_label.setWordWrap(True)
        layout = QVBoxLayout(page)
        layout.addWidget(self.report_label)
        layout.addWidget(excel)
        layout.addWidget(pdf)
        layout.addStretch(1)
        return page

    def _export_excel(self) -> None:
        path = self.home / "exports" / "lcms-report.xlsx"
        export_excel(self.db, path, operator=self.settings.operator())
        self.report_label.setText(f"已写出 {path}")

    def _export_pdf(self) -> None:
        path = self.home / "exports" / "lcms-report.pdf"
        export_pdf(self.db, path, operator=self.settings.operator())
        self.report_label.setText(f"已写出 {path}")

    # ----- 备份 -----
    def _build_backup(self) -> QWidget:
        page = QWidget()
        make = QPushButton("立即备份")
        make.clicked.connect(lambda: self._guard(self._backup_now))
        check = QPushButton("校验备份文件")
        check.clicked.connect(lambda: self._guard(self._verify_backup))
        restore = QPushButton("从备份恢复")
        restore.clicked.connect(lambda: self._guard(self._restore))
        self.backup_confirm = QCheckBox("我确认用该备份替换当前数据库。恢复前会自动再备份一次。")
        self.backup_label = QLabel("备份只包含数据库，不包含原始谱图。原始文件始终留在原处。")
        self.backup_label.setWordWrap(True)
        layout = QVBoxLayout(page)
        layout.addWidget(self.backup_label)
        layout.addWidget(make)
        layout.addWidget(check)
        layout.addWidget(self.backup_confirm)
        layout.addWidget(restore)
        layout.addStretch(1)
        return page

    def _backup_now(self) -> None:
        path = create_backup(self.db, self.home / "backups")
        self.backup_label.setText(f"已备份到 {path}")

    def _verify_backup(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择备份", str(self.home / "backups"), "备份 (*.zip)")
        if not path:
            return
        manifest = verify_backup_file(Path(path))
        self.backup_label.setText(f"校验通过。创建于 {manifest.get('created_at')}，软件版本 {manifest.get('software_version')}。")

    def _restore(self) -> None:
        if not self.backup_confirm.isChecked():
            raise LCMSError("请先勾选确认。未勾选时不会替换数据库。")
        path, _ = QFileDialog.getOpenFileName(self, "选择要恢复的备份", str(self.home / "backups"), "备份 (*.zip)")
        if not path:
            return
        pre = restore_backup(self.db, Path(path), confirm=True)
        self.scan_cache.clear()
        self._fill_datasets()
        self.backup_label.setText(f"已恢复。恢复前的数据库在 {pre}")

    # ----- 设置 -----
    def _build_settings(self) -> QWidget:
        page = QWidget()
        self.operator_edit = QLineEdit(self.settings.get("operator_name"))
        self.msconvert_edit = QLineEdit(self.settings.get("msconvert_path"))
        self.thermo_edit = QLineEdit(self.settings.get("thermo_parser_path"))
        self.mzmine_edit = QLineEdit(self.settings.get("mzmine_path"))
        self.msdial_edit = QLineEdit(self.settings.get("msdial_path"))
        save = QPushButton("保存设置")
        save.clicked.connect(lambda: self._guard(self._save_settings))
        mzmine = QPushButton("启动本机 MZmine（若已安装）")
        mzmine.clicked.connect(lambda: self._guard(lambda: launch_tool(self.settings.get("mzmine_path"), "MZmine")))
        msdial = QPushButton("启动本机 MS-DIAL（若已安装）")
        msdial.clicked.connect(lambda: self._guard(lambda: launch_tool(self.settings.get("msdial_path"), "MS-DIAL")))
        about = QTextEdit()
        about.setReadOnly(True)
        about.setPlainText(
            f"LCMS_KnowledgeBase {__version__}\n"
            "解析使用 pyteomics，相似度使用 matchms 的修正余弦。\n"
            "不附带 msconvert、ThermoRawFileParser、厂商 DLL、MZmine 或 MS-DIAL。\n"
            "PySide6 / Qt 以 LGPL 动态库形式随程序提供，可替换。详见 THIRD_PARTY_LICENSES.md。\n"
            "本程序运行时不需要网络。"
        )
        form = QFormLayout()
        form.addRow("操作者", self.operator_edit)
        form.addRow("msconvert.exe", self.msconvert_edit)
        form.addRow("ThermoRawFileParser.exe", self.thermo_edit)
        form.addRow("MZmine", self.mzmine_edit)
        form.addRow("MS-DIAL", self.msdial_edit)
        layout = QVBoxLayout(page)
        layout.addLayout(form)
        layout.addWidget(save)
        layout.addWidget(mzmine)
        layout.addWidget(msdial)
        layout.addWidget(about)
        return page

    def _save_settings(self) -> None:
        self.settings.set("operator_name", self.operator_edit.text().strip())
        self.settings.set("msconvert_path", self.msconvert_edit.text().strip())
        self.settings.set("thermo_parser_path", self.thermo_edit.text().strip())
        self.settings.set("mzmine_path", self.mzmine_edit.text().strip())
        self.settings.set("msdial_path", self.msdial_edit.text().strip())
        self.statusBar().showMessage(self._status_text())

    def _refresh_导入(self) -> None:
        self._fill_datasets()

    def _refresh_色谱图(self) -> None:
        self._fill_dataset_list(self.chroma_list)

    def _refresh_MSMS(self) -> None:
        # 导航标题是 MS/MS，方法名不能含斜杠，改在 _on_page 里特判。
        return None


def launch() -> int:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
