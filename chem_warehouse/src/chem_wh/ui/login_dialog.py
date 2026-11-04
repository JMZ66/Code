from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from chem_wh import APP_NAME, __version__
from chem_wh.app_context import AppContext
from chem_wh.services.exceptions import AuthError


class LoginDialog(QDialog):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(f"{APP_NAME} — 登录")
        self.setModal(True)
        self.setMinimumWidth(420)

        title = QLabel(APP_NAME)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: 700; color: #1a3a4a;")
        sub = QLabel(f"离线危化品仓库管理 V{__version__}")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet("color: #4a6670;")

        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("用户名")
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.pass_edit.setPlaceholderText("密码")
        self.pass_edit.returnPressed.connect(self._do_login)

        form = QFormLayout()
        form.addRow("用户名", self.user_edit)
        form.addRow("密码", self.pass_edit)

        mode = ctx.mode
        if mode == "demo":
            tip_text = (
                "演示模式使用独立数据库，示例账户 admin / Admin@123。"
                "演示数据不能用于真实危化品台账。"
            )
        else:
            tip_text = "请使用管理员创建的账户登录。本程序没有预置账户。"
        self.tip = QLabel(tip_text)
        self.tip.setWordWrap(True)
        self.tip.setStyleSheet("color: #6b7c85; font-size: 12px;")

        btn = QPushButton("登录")
        btn.clicked.connect(self._do_login)
        cancel = QPushButton("退出")
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(cancel)
        row.addWidget(btn)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(sub)
        layout.addSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self.tip)
        layout.addLayout(row)

        self.setStyleSheet(
            """
            QDialog {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #e8f1f4, stop:1 #f7f3ea);
            }
            QLineEdit { padding: 8px; border: 1px solid #9bb0b8; border-radius: 4px; }
            QPushButton {
                padding: 8px 16px; background: #1f5f74; color: white;
                border: none; border-radius: 4px;
            }
            QPushButton:hover { background: #2a7a94; }
            """
        )

    def _do_login(self) -> None:
        try:
            self.ctx.login(self.user_edit.text().strip(), self.pass_edit.text())
            self.accept()
        except AuthError as exc:
            QMessageBox.warning(self, "登录失败", str(exc))
