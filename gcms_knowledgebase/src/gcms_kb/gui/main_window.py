from __future__ import annotations

from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gcms_kb.constants import CANDIDATE_LABEL, DISCLAIMER, LAYER_ALGORITHM, LAYER_CANDIDATE, LAYER_CONFIRMED, LAYER_RAW
from gcms_kb.gui.dialogs import (
    AboutDialog,
    CalibrationDialog,
    CompareDialog,
    ConfirmDialog,
    ImportMetaDialog,
    LibraryAddDialog,
    SearchDialog,
    SettingsDialog,
    TextDialog,
    UnknownDialog,
    choose_open_files,
    choose_save,
)
from gcms_kb.gui.plots import ChromPlot, SpectrumPlot
from gcms_kb.paths import locate_doc
from gcms_kb.service import KnowledgeBase


class _Worker(QThread):
    ok = Signal(object)
    err = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self.ok.emit(self._fn())
        except Exception as exc:
            self.err.emit(str(exc))


def _fill(table: QTableWidget, headers: list[str], rows: list[list]) -> None:
    table.clear()
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.setItem(r, c, QTableWidgetItem("" if value is None else str(value)))
    table.resizeColumnsToContents()


class MainWindow(QMainWindow):
    def __init__(self, data_dir: Path, interactive_notices: bool = True):
        super().__init__()
        self.data_dir = Path(data_dir)
        self.kb = KnowledgeBase(self.data_dir)
        self._worker: _Worker | None = None
        self._sample_ids: list[int] = []
        self._peaks: list[dict] = []
        self._components: list[dict] = []
        self._hits: list[dict] = []
        self.current_rt: float | None = None
        self.setWindowTitle("GCMS 谱图知识库")
        self.resize(1280, 820)
        self._build()
        self._reload_samples()
        self._set_status()
        if interactive_notices and self.kb.settings.first_run:
            self.kb.settings.first_run = False
            self.kb.save_settings()
            QMessageBox.information(self, "请先阅读", DISCLAIMER + "\n\n候选、算法结果和确认结论在界面上分开放置。")

    def _build(self) -> None:
        self._menu()
        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText("筛选样品编号")
        self.filter_box.textChanged.connect(lambda _text: self._reload_samples())
        self.sample_list = QListWidget()
        self.sample_list.currentRowChanged.connect(self._on_sample)
        left_layout.addWidget(QLabel("历史样品"))
        left_layout.addWidget(self.filter_box)
        left_layout.addWidget(self.sample_list)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        controls = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItems(["TIC", "BPC", "EIC"])
        self.mz_box = QDoubleSpinBox()
        self.mz_box.setRange(1, 2000)
        self.mz_box.setDecimals(4)
        self.mz_box.setValue(91)
        self.background = QCheckBox("背景扣除")
        self.background.setChecked(self.kb.settings.background_subtract)
        self.kind.currentTextChanged.connect(lambda _text: self._draw_chrom())
        self.mz_box.valueChanged.connect(lambda _value: self._draw_chrom())
        controls.addWidget(QLabel("色谱"))
        controls.addWidget(self.kind)
        controls.addWidget(QLabel("EIC m/z"))
        controls.addWidget(self.mz_box)
        controls.addWidget(self.background)
        controls.addStretch(1)
        self.layer_banner = QLabel(f"{LAYER_RAW}  |  {LAYER_ALGORITHM}  |  {LAYER_CANDIDATE}  |  {LAYER_CONFIRMED}")
        self.layer_banner.setStyleSheet("background:#fff7ed;color:#9a3412;padding:6px;font-weight:600;")
        self.chrom = ChromPlot()
        self.chrom.rtClicked.connect(self._on_rt)
        self.spectrum = SpectrumPlot()
        self.spectrum_title = QLabel(LAYER_RAW)
        center_layout.addWidget(self.layer_banner)
        center_layout.addLayout(controls)
        center_layout.addWidget(self.chrom, stretch=3)
        center_layout.addWidget(self.spectrum_title)
        center_layout.addWidget(self.spectrum, stretch=2)
        right = QTabWidget()
        self.tabs = right
        self.peak_table = QTableWidget()
        self.component_table = QTableWidget()
        self.hit_table = QTableWidget()
        self.confirm_table = QTableWidget()
        self.unknown_table = QTableWidget()
        right.addTab(self.peak_table, "峰（算法结果）")
        right.addTab(self.component_table, "解卷积（算法结果）")
        right.addTab(self.hit_table, "谱库候选（未确认）")
        right.addTab(self.confirm_table, "确认结论")
        right.addTab(self.unknown_table, "未知峰")
        self.peak_table.itemSelectionChanged.connect(self._on_peak_row)
        self.component_table.itemSelectionChanged.connect(self._on_component_row)
        self.hit_table.itemSelectionChanged.connect(self._on_hit_row)
        side_actions = QWidget()
        action_row = QHBoxLayout(side_actions)
        for text, slot in (
            ("峰检测", self.detect_peaks_async),
            ("解卷积", self.deconvolve_async),
            ("谱库检索", self.search_current),
            ("加入谱库", self.add_current_to_library),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            action_row.addWidget(button)
        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.addWidget(side_actions)
        wrapper_layout.addWidget(right)
        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.addWidget(wrapper)
        splitter.setStretchFactor(1, 3)
        self.setCentralWidget(splitter)
        self.setStatusBar(QStatusBar())

    def _menu(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        self._add(file_menu, "导入 mzML", self.import_mzml_dialog)
        self._add(file_menu, "导入 RAW", self.import_raw_dialog)
        self._add(file_menu, "批量导入", self.import_batch_dialog)
        file_menu.addSeparator()
        self._add(file_menu, "导出 Excel 报告", self.export_excel)
        self._add(file_menu, "导出 PDF 报告", self.export_pdf)
        self._add(file_menu, "备份", self.backup_dialog)
        self._add(file_menu, "恢复", self.restore_dialog)
        self._add(file_menu, "校验原始文件未被修改", self.verify_original)
        self._add(file_menu, "从本库删除样品（不删除原始文件）", self.delete_current)
        file_menu.addSeparator()
        self._add(file_menu, "退出", self.close)
        process = self.menuBar().addMenu("处理")
        self._add(process, "峰检测与积分", self.detect_peaks_async)
        self._add(process, "解卷积", self.deconvolve_async)
        self._add(process, "与历史样品比较", self.compare_dialog)
        self._add(process, "运行外部 MS-DIAL（不入库）", self.run_msdial)
        library = self.menuBar().addMenu("谱库")
        self._add(library, "导入 MSP", self.import_msp)
        self._add(library, "导出 MSP", self.export_msp)
        self._add(library, "将当前谱图加入谱库", self.add_current_to_library)
        self._add(library, "对当前峰或组分检索", self.search_current)
        ri_menu = self.menuBar().addMenu("保留指数")
        self._add(ri_menu, "烷烃校正并计算 RI", self.calibration_dialog)
        review = self.menuBar().addMenu("审核")
        self._add(review, "标准品确认或人工审核", self.confirm_dialog)
        self._add(review, "登记未知峰", self.unknown_dialog)
        find = self.menuBar().addMenu("检索")
        self._add(find, "综合检索", self.search_dialog)
        settings = self.menuBar().addMenu("设置")
        self._add(settings, "首选项", self.settings_dialog)
        help_menu = self.menuBar().addMenu("帮助")
        self._add(help_menu, "使用说明", lambda: self._show_doc("使用说明.md"))
        self._add(help_menu, "四个数据层", self._layer_help)
        self._add(help_menu, "关于", self._about)

    def _add(self, menu, text, slot) -> None:
        action = QAction(text, self)
        action.triggered.connect(slot)
        menu.addAction(action)

    def _set_status(self) -> None:
        user = self.kb.settings.user_name or "未填写操作者"
        self.statusBar().showMessage(f"操作者：{user}    数据目录：{self.data_dir}    {DISCLAIMER}")

    def _reload_samples(self) -> None:
        current = self.current_sample_id()
        rows = self.kb.list_samples(self.filter_box.text() if hasattr(self, "filter_box") else "")
        self.sample_list.clear()
        self._sample_ids = []
        restore = -1
        for row in rows:
            mark = "合成" if row.get("is_synthetic") else row.get("source_format")
            self.sample_list.addItem(f"{row['id']}  {row['sample_code']}  [{mark}]")
            self._sample_ids.append(row["id"])
            if row["id"] == current:
                restore = len(self._sample_ids) - 1
        if restore >= 0:
            self.sample_list.setCurrentRow(restore)
        elif self._sample_ids:
            self.sample_list.setCurrentRow(0)

    def current_sample_id(self) -> int | None:
        row = self.sample_list.currentRow()
        if row < 0 or row >= len(self._sample_ids):
            return None
        return self._sample_ids[row]

    def _on_sample(self, _row: int) -> None:
        sample_id = self.current_sample_id()
        if sample_id is None:
            return
        self._draw_chrom()
        self._refresh_tables()
        sample, run = self.kb.load_sample_run(sample_id)
        if run.n_scans:
            self._show_raw(float(run.rt[int(np_argmax(run.tic))]))
        hint = sample.get("file_hint") or ""
        synthetic = "合成数据。" if sample.get("is_synthetic") else ""
        self.spectrum_title.setText(f"{LAYER_RAW}  {synthetic}{hint}")

    def _draw_chrom(self) -> None:
        sample_id = self.current_sample_id()
        if sample_id is None:
            return
        kind = self.kind.currentText().lower()
        try:
            rt, y = self.kb.chromatogram(
                sample_id,
                kind,
                mz=self.mz_box.value() if kind == "eic" else None,
            )
        except Exception as exc:
            self.statusBar().showMessage(str(exc))
            return
        self.chrom.set_curves([(rt, y, pg.mkPen("#1d4ed8", width=1.6), kind.upper())])

    def _on_rt(self, rt: float) -> None:
        self.current_rt = rt
        self.chrom.mark(rt)
        self._show_raw(rt)

    def _show_raw(self, rt: float) -> None:
        sample_id = self.current_sample_id()
        if sample_id is None:
            return
        mz, inten, _index, subtracted = self.kb.spectrum_at_rt(sample_id, rt, background=self.background.isChecked())
        self.current_rt = rt
        self.chrom.mark(rt)
        self._current_mz = mz
        self._current_i = inten
        label = "已扣背景" if subtracted else "未扣背景"
        self.spectrum_title.setText(f"{LAYER_RAW} · RT {rt:.4f} min · {label}")
        self.spectrum.set_sticks([(mz, inten, pg.mkPen("#1d4ed8", width=1.4))])

    def _refresh_tables(self) -> None:
        sample_id = self.current_sample_id()
        if sample_id is None:
            return
        from gcms_kb import repository as store

        self._peaks = store.list_peaks(self.kb.db, sample_id)
        self._components = store.list_components(self.kb.db, sample_id)
        self._hits = store.list_hits(self.kb.db, sample_id)
        report = self.kb.report(sample_id)
        _fill(
            self.peak_table,
            ["峰号", "RT", "起点", "终点", "高度", "面积", "RI", "算法"],
            [
                [p["id"], f"{p['rt']:.4f}", f"{p['rt_start']:.4f}", f"{p['rt_end']:.4f}", f"{p['height']:.4g}", f"{p['area']:.4g}", _fmt(p.get("ri")), p["algorithm"]]
                for p in self._peaks
            ],
        )
        _fill(
            self.component_table,
            ["组分", "RT", "高度", "面积", "RI", "算法"],
            [
                [c["id"], f"{c['rt']:.4f}", f"{c['height']:.4g}", f"{c['area']:.4g}", _fmt(c.get("ri")), c["algorithm"]]
                for c in self._components
            ],
        )
        _fill(
            self.hit_table,
            ["状态", "排名", "谱库名称", "CAS", "余弦", "反向", "匹配峰", "ΔRI"],
            [
                [CANDIDATE_LABEL, h["rank"], h["library_name"], h.get("library_cas") or "", f"{h['score']:.3f}", _fmt(h.get("reverse_score")), h["matched_peaks"], _fmt(h.get("ri_delta"))]
                for h in self._hits
            ],
        )
        _fill(
            self.confirm_table,
            ["类型", "化合物", "CAS", "操作者", "时间", "证据"],
            [
                [item["decision"], item["compound_name"], item.get("cas") or "", item["user_name"], item["decided_at"], item["evidence"]]
                for item in report["confirmations"]
            ],
        )
        _fill(
            self.unknown_table,
            ["RT", "操作者", "时间", "说明"],
            [[u["rt"], u["user_name"], u["logged_at"], u["note"]] for u in report["unknowns"]],
        )

    def _selected_peak(self) -> dict | None:
        row = self.peak_table.currentRow()
        if row < 0 or row >= len(self._peaks):
            return None
        return self._peaks[row]

    def _selected_component(self) -> dict | None:
        row = self.component_table.currentRow()
        if row < 0 or row >= len(self._components):
            return None
        return self._components[row]

    def _on_peak_row(self) -> None:
        peak = self._selected_peak()
        if peak is None:
            return
        self.current_rt = peak["rt"]
        self.chrom.mark(peak["rt"])
        self._current_mz = peak["mz"]
        self._current_i = peak["intensity"]
        self.spectrum_title.setText(f"{LAYER_ALGORITHM} · 峰 {peak['id']} · RT {peak['rt']:.4f} min")
        self.spectrum.set_sticks([(peak["mz"], peak["intensity"], pg.mkPen("#0f766e", width=1.4))])

    def _on_component_row(self) -> None:
        component = self._selected_component()
        if component is None:
            return
        self.current_rt = component["rt"]
        self.chrom.mark(component["rt"])
        self._current_mz = component["mz"]
        self._current_i = component["intensity"]
        self.spectrum_title.setText(f"{LAYER_ALGORITHM} · 解卷积组分 {component['id']} · 纯化谱，不是鉴定")
        self.spectrum.set_sticks([(component["mz"], component["intensity"], pg.mkPen("#7c3aed", width=1.4))])

    def _on_hit_row(self) -> None:
        row = self.hit_table.currentRow()
        if row < 0 or row >= len(self._hits):
            return
        hit = self._hits[row]
        from gcms_kb.repository import get_library

        entry = get_library(self.kb.db, hit["library_entry_id"])
        query = None
        if hit["query_kind"] == "peak":
            query = next((item for item in self._peaks if item["id"] == hit["query_id"]), None)
        else:
            query = next((item for item in self._components if item["id"] == hit["query_id"]), None)
        series = []
        if query is not None:
            series.append((query["mz"], query["intensity"], pg.mkPen("#0f766e", width=1.4)))
        if entry is not None:
            series.append((entry["mz"], entry["intensity"], pg.mkPen("#be123c", width=1.2)))
        self.spectrum.set_sticks(series)
        self.spectrum_title.setText(
            f"{CANDIDATE_LABEL} · {hit['library_name']} · 余弦 {hit['score']:.3f} · 反向 {hit.get('reverse_score')}"
        )

    def _run(self, fn, on_ok) -> None:
        if self._worker is not None:
            QMessageBox.information(self, "请稍候", "已有任务在运行。")
            return
        self._worker = _Worker(fn)
        self._worker.ok.connect(lambda result: self._done(on_ok, result))
        self._worker.err.connect(self._failed)
        self._worker.start()

    def _done(self, on_ok, result) -> None:
        self._worker = None
        on_ok(result)

    def _failed(self, message: str) -> None:
        self._worker = None
        QMessageBox.warning(self, "没有完成", message)

    def import_paths_sync(self, paths: list[Path], user_name: str, **common) -> list[dict]:
        results = self.kb.import_paths(paths, user_name, **common)
        self._reload_samples()
        return results

    def import_mzml_dialog(self) -> None:
        paths = choose_open_files(self, "导入 mzML", "mzML (*.mzML *.mzml)")
        if paths:
            self._import_with_meta(paths)

    def import_raw_dialog(self) -> None:
        paths = choose_open_files(self, "导入 RAW", "Thermo RAW (*.raw *.RAW)")
        if paths:
            self._import_with_meta(paths)

    def import_batch_dialog(self) -> None:
        paths = choose_open_files(self, "批量导入", "数据文件 (*.mzML *.mzml *.raw *.RAW)")
        if paths:
            self._import_with_meta(paths)

    def _import_with_meta(self, paths: list[Path]) -> None:
        dialog = ImportMetaDialog(self.kb.settings.user_name, single=len(paths) == 1, parent=self)
        if dialog.exec() != ImportMetaDialog.Accepted:
            return
        values = dialog.values()
        user = values.pop("user_name") or self.kb.settings.user_name
        if len(paths) > 1:
            values["sample_code"] = None

        def work():
            kb = KnowledgeBase(self.data_dir)
            return kb.import_paths(paths, user, **values)

        self.statusBar().showMessage("正在导入，原始文件只读。")
        self._run(work, self._imported)

    def _imported(self, results: list[dict]) -> None:
        self.kb = KnowledgeBase(self.data_dir)
        self._reload_samples()
        failed = [item for item in results if not item.get("ok")]
        if failed:
            QMessageBox.warning(self, "导入结束", "\n".join(item["error"] for item in failed[:8]))
        else:
            self.statusBar().showMessage(f"已导入 {len(results)} 个文件。原始文件未改写。")

    def detect_peaks_sync(self) -> list[dict]:
        sample_id = self.current_sample_id()
        if sample_id is None:
            return []
        rows = self.kb.detect_peaks_for(sample_id)
        self._refresh_tables()
        return rows

    def detect_peaks_async(self) -> None:
        sample_id = self.current_sample_id()
        if sample_id is None:
            return

        def work():
            return KnowledgeBase(self.data_dir).detect_peaks_for(sample_id)

        self._run(work, lambda _rows: self._after_job("峰检测完成。峰表是算法结果，没有化合物名称。"))

    def deconvolve_async(self) -> None:
        sample_id = self.current_sample_id()
        if sample_id is None:
            return

        def work():
            _rows, note = KnowledgeBase(self.data_dir).deconvolve_sample(sample_id)
            return note

        self._run(work, lambda note: self._after_job(note or "解卷积完成。组分谱是算法纯化结果，不是鉴定。"))

    def _after_job(self, message: str) -> None:
        self.kb = KnowledgeBase(self.data_dir)
        self._refresh_tables()
        self.statusBar().showMessage(message)

    def search_current(self) -> None:
        sample_id = self.current_sample_id()
        kind, target = self._active_target()
        if sample_id is None or target is None:
            QMessageBox.information(self, "谱库检索", "请先在峰表或组分表中选中一行。")
            return
        query_id = target["id"]

        def work():
            return KnowledgeBase(self.data_dir).search_library(sample_id, kind, query_id)

        self._run(work, lambda _hits: self._after_job("检索完成。结果栏固定为谱库候选（未确认）。"))

    def add_current_to_library(self) -> None:
        mz = getattr(self, "_current_mz", None)
        inten = getattr(self, "_current_i", None)
        if mz is None or len(mz) == 0:
            QMessageBox.information(self, "谱库", "当前没有可保存的谱图。")
            return
        dialog = LibraryAddDialog(self)
        if dialog.exec() != LibraryAddDialog.Accepted:
            return
        values = dialog.values()
        values.update(
            {
                "mz": mz,
                "intensity": inten,
                "source": "sample",
                "source_sample_id": self.current_sample_id(),
                "rt": self.current_rt,
                "added_by": self.kb.settings.user_name or "未填写",
            }
        )
        try:
            self.kb.add_library_spectrum(values)
        except Exception as exc:
            QMessageBox.warning(self, "谱库", str(exc))
            return
        QMessageBox.information(self, "谱库", "已保存为参考谱。样品本身没有被鉴定。")

    def _active_target(self):
        if self.tabs.currentIndex() == 1:
            component = self._selected_component()
            if component is not None:
                return "component", component
        peak = self._selected_peak()
        if peak is not None and self.tabs.currentIndex() in (0, 2, 3, 4):
            return "peak", peak
        component = self._selected_component()
        if component is not None:
            return "component", component
        if peak is not None:
            return "peak", peak
        return None, None

    def confirm_dialog(self) -> None:
        sample_id = self.current_sample_id()
        if sample_id is None:
            return
        kind, target = self._active_target()
        if target is None:
            QMessageBox.information(self, "确认", "请先选择一个算法峰或解卷积组分。")
            return
        score = self._hits[0]["score"] if self._hits else None
        dialog = ConfirmDialog(self.kb.settings.user_name, target.get("rt"), target.get("ri"), score, self)
        if dialog.exec() != ConfirmDialog.Accepted:
            return
        record = dialog.record(sample_id, kind, target["id"])
        try:
            self.kb.confirm(record)
        except Exception as exc:
            QMessageBox.warning(self, "确认没有保存", str(exc))
            return
        self._refresh_tables()
        self.statusBar().showMessage("已写入确认结论。这一步与谱库分数是分开的。")

    def unknown_dialog(self) -> None:
        sample_id = self.current_sample_id()
        if sample_id is None:
            return
        target = self._selected_peak() or self._selected_component()
        dialog = UnknownDialog(
            self.kb.settings.user_name,
            None if target is None else target.get("rt"),
            None if target is None else target.get("ri"),
            self,
        )
        if dialog.exec() != UnknownDialog.Accepted:
            return
        kind = None if target is None else ("peak" if self._selected_peak() is not None else "component")
        record = dialog.record(sample_id, kind, None if target is None else target["id"])
        try:
            self.kb.log_unknown(record)
        except Exception as exc:
            QMessageBox.warning(self, "未知峰", str(exc))
            return
        self._refresh_tables()

    def calibration_dialog(self) -> None:
        sample_id = self.current_sample_id()
        dialog = CalibrationDialog(self)
        if dialog.exec() != CalibrationDialog.Accepted:
            return
        try:
            calibration_id = self.kb.save_calibration(
                dialog.cal_name.text().strip() or "烷烃校正",
                dialog.points(),
                self.kb.settings.user_name or "未填写",
            )
            if sample_id is not None:
                count = self.kb.apply_retention_index(sample_id, calibration_id)
                self._refresh_tables()
                self.statusBar().showMessage(f"已计算 {count} 条 RT 的保留指数。RI 是计算值，不是鉴定。")
        except Exception as exc:
            QMessageBox.warning(self, "保留指数", str(exc))

    def search_dialog(self) -> None:
        SearchDialog(self.kb, self).exec()

    def compare_dialog(self) -> None:
        CompareDialog(self.kb, self).exec()

    def settings_dialog(self) -> None:
        dialog = SettingsDialog(self.kb.settings, self)
        if dialog.exec() != SettingsDialog.Accepted:
            return
        dialog.apply(self.kb.settings)
        self.kb.save_settings()
        self.background.setChecked(self.kb.settings.background_subtract)
        self._set_status()

    def export_excel(self) -> None:
        self._export("excel")

    def export_pdf(self) -> None:
        self._export("pdf")

    def _export(self, kind: str) -> None:
        sample_id = self.current_sample_id()
        if sample_id is None:
            return
        suffix = "xlsx" if kind == "excel" else "pdf"
        path = choose_save(self, "导出报告", f"报告 (*.{suffix})")
        if path is None:
            return
        try:
            if kind == "excel":
                self.kb.export_excel(sample_id, path)
            else:
                self.kb.export_pdf(sample_id, path)
        except Exception as exc:
            QMessageBox.warning(self, "导出", str(exc))
            return
        self.statusBar().showMessage(f"已导出 {path}")

    def backup_dialog(self) -> None:
        path = choose_save(self, "备份", "备份 (*.zip)")
        if path is None:
            return
        try:
            self.kb.backup(path)
        except Exception as exc:
            QMessageBox.warning(self, "备份", str(exc))
            return
        QMessageBox.information(self, "备份", f"已写入 {path}")

    def restore_dialog(self) -> None:
        paths = choose_open_files(self, "恢复", "备份 (*.zip)")
        if not paths:
            return
        answer = QMessageBox.question(
            self,
            "恢复",
            "恢复前会先把当前数据打成安全备份。校验失败则不会替换当前数据。继续吗？",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            safety = self.kb.restore(paths[0])
        except Exception as exc:
            QMessageBox.warning(self, "恢复没有执行", str(exc))
            return
        self.kb = KnowledgeBase(self.data_dir)
        self._reload_samples()
        QMessageBox.information(self, "恢复", f"已恢复。替换前的数据在 {safety}")

    def verify_original(self) -> None:
        sample_id = self.current_sample_id()
        if sample_id is None:
            return
        result = self.kb.verify_original(sample_id)
        if not result["exists"]:
            QMessageBox.information(self, "校验", "原始路径上已经没有这个文件。数据库里的哈希还在。")
            return
        if result["unchanged"]:
            QMessageBox.information(self, "校验", "原始文件的大小和 SHA-256 与导入时一致。")
        else:
            QMessageBox.warning(self, "校验", "原始文件的哈希与导入时不同。")

    def delete_current(self) -> None:
        sample_id = self.current_sample_id()
        if sample_id is None:
            return
        answer = QMessageBox.question(
            self,
            "删除",
            "只删除本程序数据库里的样品、缓存、算法结果和确认记录。原始文件不会被删除或移动。已复制进谱库的参考谱会保留。",
        )
        if answer != QMessageBox.Yes:
            return
        self.kb.delete_sample(sample_id)
        self._reload_samples()

    def import_msp(self) -> None:
        paths = choose_open_files(self, "导入 MSP", "MSP (*.msp)")
        if not paths:
            return
        count = self.kb.import_msp(paths[0], self.kb.settings.user_name or "未填写")
        QMessageBox.information(self, "谱库", f"读入 {count} 条参考谱。它们不是样品鉴定。")

    def export_msp(self) -> None:
        path = choose_save(self, "导出 MSP", "MSP (*.msp)")
        if path is None:
            return
        count = self.kb.export_msp(path)
        self.statusBar().showMessage(f"已导出 {count} 条谱库记录到 {path}")

    def run_msdial(self) -> None:
        sample_id = self.current_sample_id()
        if sample_id is None:
            return

        def work():
            return KnowledgeBase(self.data_dir).run_external_msdial(sample_id)

        self._run(
            work,
            lambda result: QMessageBox.information(
                self,
                "MS-DIAL",
                f"{result['message']}\n退出码 {result['returncode']}\n{result['output_dir']}",
            ),
        )

    def _show_doc(self, name: str) -> None:
        path = locate_doc(name)
        if path is None:
            QMessageBox.information(self, "说明", f"找不到 {name}")
            return
        TextDialog(name, path.read_text(encoding="utf-8"), self).exec()

    def _layer_help(self) -> None:
        QMessageBox.information(
            self,
            "四个数据层",
            f"{LAYER_RAW}：色谱和单击得到的质谱，来自文件。\n"
            f"{LAYER_ALGORITHM}：峰面积、解卷积纯化谱。\n"
            f"{LAYER_CANDIDATE}：永远标注为谱库候选（未确认）。\n"
            f"{LAYER_CONFIRMED}：只有标准品确认或人工审核，并写明是谁、什么时候、依据是什么。",
        )

    def _about(self) -> None:
        AboutDialog(self.data_dir, self).exec()


def _fmt(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.4g}"
    except (TypeError, ValueError):
        return str(value)


def np_argmax(values) -> int:
    import numpy as np

    return int(np.argmax(values))
