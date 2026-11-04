from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from chem_wh.constants import DISCLAIMER
from chem_wh.services.exceptions import AppError


class FirstRunWizard(QDialog):
    """Create the first administrator. No sample chemicals and no sample accounts."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("首次设置")
        self.setModal(True)
        self.setMinimumWidth(560)

        title = QLabel("第一次使用")
        title.setStyleSheet("font-size: 20px; font-weight: 700; color: #143844;")
        intro = QLabel(
            "请创建本机唯一的初始管理员。完成后没有预置账户，也没有示例试剂。\n\n" + DISCLAIMER
        )
        intro.setWordWrap(True)

        self.username = QLineEdit()
        self.username.setPlaceholderText("登录名，例如 zhangsan")
        self.display_name = QLineEdit()
        self.display_name.setPlaceholderText("真实姓名")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("至少 10 位，并包含大小写、数字、符号中的三类")
        self.password2 = QLineEdit()
        self.password2.setEchoMode(QLineEdit.Password)
        self.location_name = QLineEdit()
        self.location_name.setPlaceholderText("例如：试剂主库")
        self.agree = QCheckBox("我已阅读说明：本软件不能替代法定危化品安全管理")
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #9b1c1c;")

        form = QFormLayout()
        form.addRow("管理员登录名", self.username)
        form.addRow("姓名", self.display_name)
        form.addRow("密码", self.password)
        form.addRow("再次输入密码", self.password2)
        form.addRow("第一个库房名称", self.location_name)

        ok = QPushButton("创建管理员并进入")
        ok.clicked.connect(self.submit)
        cancel = QPushButton("退出")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(cancel)
        buttons.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(self.agree)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

    def submit(self) -> None:
        self.error_label.setText("")
        if not self.agree.isChecked():
            self.error_label.setText("请先勾选声明。")
            return
        if self.password.text() != self.password2.text():
            self.error_label.setText("两次输入的密码不一致。")
            return
        try:
            self.ctx.auth.validate_password(self.password.text(), production=True)
            uid = self.ctx.bootstrap_production_admin(
                self.username.text().strip(),
                self.password.text(),
                self.display_name.text().strip() or "系统管理员",
            )
            self.ctx.current_user = self.ctx.auth.get_user(uid)
        except AppError as exc:
            self.error_label.setText(str(exc))
            return
        loc_name = self.location_name.text().strip() or "试剂主库"
        if self.ctx.current_user is not None:
            try:
                self.ctx.chemicals.add_location(
                    self.ctx.current_user,
                    level="warehouse",
                    code="WH1",
                    name=loc_name,
                    storage_condition="按本单位制度存放",
                )
            except AppError:
                pass
        self.accept()
