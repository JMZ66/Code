"""简体中文桌面界面：选择文件、只读审查、打开报告。"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from bid_review.pipeline import run_review


class ReviewWorker(QThread):
    progressed = Signal(str)
    finished_ok = Signal(object, object)
    failed = Signal(str)

    def __init__(self, files, output_dir, template, profile):
        super().__init__()
        self.files = files
        self.output_dir = output_dir
        self.template = template
        self.profile = profile

    def run(self):
        try:
            result, paths = run_review(
                self.files,
                self.output_dir,
                template_docx=self.template or None,
                profile_json=self.profile or None,
                progress=lambda m: self.progressed.emit(m),
            )
            self.finished_ok.emit(result, paths)
        except Exception as exc:  # noqa: BLE001 — 界面层统一展示
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("招投标文件审查助手 1.0（只读·离线）")
        self.resize(920, 640)
        self.files: list[str] = []
        self.template_path = ""
        self.profile_path = ""
        self.output_dir = str(Path.home() / "bid_review_reports")

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        title = QLabel("招投标文件审查助手")
        title.setFont(QFont("Microsoft YaHei", 20, QFont.Bold))
        layout.addWidget(title)

        subtitle = QLabel(
            "只读核查格式、占位残留与跨文件一致性。不修改原文件，不上传，不调用云端 API。"
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.list = QListWidget()
        layout.addWidget(self.list)

        row = QHBoxLayout()
        btn_add = QPushButton("添加 DOCX/PDF/XLSX")
        btn_add.clicked.connect(self.add_files)
        btn_remove = QPushButton("移除选中")
        btn_remove.clicked.connect(self.remove_selected)
        btn_template = QPushButton("指定官方 Word 模板")
        btn_template.clicked.connect(self.pick_template)
        btn_profile = QPushButton("加载格式 JSON（可选）")
        btn_profile.clicked.connect(self.pick_profile)
        btn_out = QPushButton("选择报告目录")
        btn_out.clicked.connect(self.pick_output)
        for b in (btn_add, btn_remove, btn_template, btn_profile, btn_out):
            row.addWidget(b)
        layout.addLayout(row)

        self.meta = QLabel(self._meta_text())
        self.meta.setWordWrap(True)
        layout.addWidget(self.meta)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

        self.btn_run = QPushButton("开始只读审查")
        self.btn_run.clicked.connect(self.start_review)
        layout.addWidget(self.btn_run)

        self.worker: ReviewWorker | None = None

    def _meta_text(self) -> str:
        return (
            f"模板：{self.template_path or '（未指定，使用内置默认配置）'}\n"
            f"配置：{self.profile_path or '（无）'}\n"
            f"报告目录：{self.output_dir}"
        )

    def add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择待审查文件",
            "",
            "招投标文件 (*.docx *.pdf *.xlsx *.xlsm)",
        )
        for f in files:
            if f not in self.files:
                self.files.append(f)
                self.list.addItem(f)

    def remove_selected(self) -> None:
        for item in self.list.selectedItems():
            path = item.text()
            self.files = [f for f in self.files if f != path]
            self.list.takeItem(self.list.row(item))

    def pick_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择官方 Word 模板", "", "Word (*.docx)")
        if path:
            self.template_path = path
            self.meta.setText(self._meta_text())

    def pick_profile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择格式配置 JSON", "", "JSON (*.json)")
        if path:
            self.profile_path = path
            self.meta.setText(self._meta_text())

    def pick_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择报告输出目录", self.output_dir)
        if path:
            self.output_dir = path
            self.meta.setText(self._meta_text())

    def start_review(self) -> None:
        if not self.files:
            QMessageBox.warning(self, "提示", "请先添加待审查文件。")
            return
        self.btn_run.setEnabled(False)
        self.log.clear()
        self.log.append("开始审查…")
        self.worker = ReviewWorker(
            self.files,
            self.output_dir,
            self.template_path,
            self.profile_path,
        )
        self.worker.progressed.connect(self.log.append)
        self.worker.finished_ok.connect(self.on_ok)
        self.worker.failed.connect(self.on_fail)
        self.worker.start()

    def on_ok(self, result, paths) -> None:
        self.btn_run.setEnabled(True)
        summary = result.summary()
        self.log.append("—— 审查完成 ——")
        for k, v in summary.items():
            self.log.append(f"{k}: {v}")
        self.log.append("报告文件：")
        for kind, p in paths.items():
            self.log.append(f"  [{kind}] {p}")
        unchanged = all(i.unchanged for i in result.integrity)
        if not unchanged:
            QMessageBox.critical(self, "完整性异常", "检测到原文件哈希变化，请立即停止使用并排查。")
            return
        QMessageBox.information(
            self,
            "完成",
            f"共发现 {len(result.findings)} 个问题。\n报告目录：\n{self.output_dir}",
        )

    def on_fail(self, message: str) -> None:
        self.btn_run.setEnabled(True)
        self.log.append(f"失败：{message}")
        QMessageBox.critical(self, "审查失败", message)


def launch_gui() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("招投标文件审查助手")
    win = MainWindow()
    win.show()
    return app.exec()
