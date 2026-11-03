"""应用程序入口。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow running without install
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from chem_wh import APP_NAME, __version__
from chem_wh.app_context import AppContext
from chem_wh.services.exceptions import AppError, ValidationError
from chem_wh.ui.login_dialog import LoginDialog
from chem_wh.ui.main_window import MainWindow


def _resolve_mode(cli_mode: str | None) -> str:
    env = os.environ.get("CHEM_WH_MODE", "").strip().lower()
    if cli_mode:
        return cli_mode
    if env in ("demo", "production"):
        return env
    return ""


def run(db_path: str | None = None, mode: str | None = None) -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")

    ctx = AppContext(db_path)
    selected = _resolve_mode(mode)
    current = ctx.mode

    if current == "unset":
        if not selected:
            choice, ok = QInputDialog.getItem(
                None,
                "选择运行模式",
                "首次启动请选择模式（选定后锁定，正式模式禁止演示数据）：",
                ["demo", "production"],
                0,
                False,
            )
            if not ok:
                ctx.close()
                return 0
            selected = choice
        try:
            ctx.initialize_mode(selected)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(None, "模式初始化失败", str(exc))
            ctx.close()
            return 1
    elif selected and selected != current:
        QMessageBox.critical(
            None,
            "模式冲突",
            f"数据库已锁定为 {current}，与请求的 {selected} 不一致。",
        )
        ctx.close()
        return 1

    if ctx.mode == "demo":
        ctx.ensure_seed()
    else:
        users = ctx.db.fetchone("SELECT COUNT(*) AS c FROM users")
        if not users or int(users["c"]) == 0:
            QMessageBox.information(
                None,
                "正式模式初始化",
                "正式模式无演示账户。请创建首个管理员（强密码）。",
            )
            from PySide6.QtWidgets import QLineEdit

            username, ok1 = QInputDialog.getText(None, "管理员用户名", "用户名:")
            if not ok1 or not username.strip():
                ctx.close()
                return 0
            password, ok2 = QInputDialog.getText(
                None,
                "管理员密码",
                "密码（正式模式≥10位且复杂度要求）:",
                QLineEdit.EchoMode.Password,
            )
            if not ok2:
                ctx.close()
                return 0
            try:
                ctx.bootstrap_production_admin(username.strip(), password)
            except (AppError, ValidationError) as exc:
                QMessageBox.critical(None, "初始化失败", str(exc))
                ctx.close()
                return 1

    login = LoginDialog(ctx)
    if ctx.mode == "demo":
        # tip already in dialog
        pass
    if login.exec() != LoginDialog.Accepted:
        ctx.close()
        return 0

    win = MainWindow(ctx)
    win.show()
    code = app.exec()
    ctx.close()
    return code


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} v{__version__}")
    parser.add_argument("--db", dest="db_path", default=None, help="SQLite 路径")
    parser.add_argument(
        "--mode",
        choices=["demo", "production"],
        default=None,
        help="首次启动模式；已锁定库不可切换",
    )
    args = parser.parse_args(argv)
    raise SystemExit(run(args.db_path, args.mode))


if __name__ == "__main__":
    main()
