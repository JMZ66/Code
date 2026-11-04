"""应用程序入口。默认正式模式；演示模式必须显式打开，且使用独立数据库。"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chem_wh import APP_NAME, __version__
from chem_wh.db.database import get_default_db_path


def _demo_requested(args) -> bool:
    env = os.environ.get("CHEM_WH_MODE", "").strip().lower()
    return bool(args.demo or args.mode == "demo" or env == "demo")


def _resolve_db(args) -> tuple[str | None, bool]:
    demo = _demo_requested(args)
    if args.mode == "production" and (args.demo or os.environ.get("CHEM_WH_MODE", "").lower() == "demo"):
        raise SystemExit("不能同时指定正式模式与演示模式")
    if args.db_path:
        chosen = Path(args.db_path).expanduser().resolve()
        production_default = get_default_db_path(demo=False).resolve()
        if demo and chosen == production_default:
            raise SystemExit("演示模式不能使用正式数据库路径，请去掉 --db 以使用独立演示库")
        return str(chosen), demo
    if demo:
        return str(get_default_db_path(demo=True)), True
    return str(get_default_db_path(demo=False)), False


def run(db_path: str | None = None, *, demo: bool = False) -> int:
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication, QMessageBox

    from chem_wh.app_context import AppContext
    from chem_wh.services.exceptions import AppError, ValidationError
    from chem_wh.ui.login_dialog import LoginDialog
    from chem_wh.ui.main_window import MainWindow
    from chem_wh.ui.wizard import FirstRunWizard
    from chem_wh.utils.resources import font_path

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    try:
        font_id = QFontDatabase.addApplicationFont(str(font_path()))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 10))
    except OSError:
        app.setFont(QFont("Microsoft YaHei", 10))

    ctx = AppContext(db_path)
    try:
        if ctx.mode == "unset":
            ctx.initialize_mode("demo" if demo else "production")
        elif demo and ctx.mode != "demo":
            QMessageBox.critical(
                None,
                "模式冲突",
                f"这个数据库已锁定为正式模式，不能当作演示库打开。\n{ctx.db.path}",
            )
            return 1
        elif (not demo) and ctx.mode == "demo" and db_path and Path(db_path).resolve() == get_default_db_path(demo=False).resolve():
            # An older demo file may already live at the default path. Do not convert or delete it.
            pass

        if ctx.mode == "demo":
            ctx.ensure_seed()
        else:
            users = ctx.db.fetchone("SELECT COUNT(*) AS c FROM users")
            if not users or int(users["c"]) == 0:
                wizard = FirstRunWizard(ctx)
                if wizard.exec() != wizard.Accepted:
                    return 0

        if ctx.current_user is None:
            login = LoginDialog(ctx)
            if login.exec() != LoginDialog.Accepted:
                return 0

        win = MainWindow(ctx)
        win.show()
        return app.exec()
    except (AppError, ValidationError, ValueError) as exc:
        QMessageBox.critical(None, "启动失败", str(exc))
        return 1
    finally:
        ctx.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} v{__version__}")
    parser.add_argument("--db", dest="db_path", default=None, help="SQLite 数据库文件")
    parser.add_argument("--mode", choices=["demo", "production"], default=None)
    parser.add_argument("--demo", action="store_true", help="打开独立的演示库，默认关闭")
    parser.add_argument("--self-test", action="store_true", help="在临时库中做无界面自检后退出")
    parser.add_argument("--self-test-report", default=None, help="自检结果 JSON 路径")
    parser.add_argument("--gui-probe", action="store_true", help="只创建离屏窗口并退出，供打包检查")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        raise SystemExit(0)
    if args.gui_probe:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication, QLabel

        app = QApplication([])
        label = QLabel("危化品仓库管理系统")
        label.show()
        app.processEvents()
        raise SystemExit(0)
    if args.self_test:
        from chem_wh.selftest import append_log, run_self_test

        log_path = (args.self_test_report + ".log") if args.self_test_report else None
        append_log(log_path, "main entered self-test")
        try:
            code = run_self_test(args.db_path, args.self_test_report, log_path)
        except Exception:
            append_log(log_path, traceback.format_exc())
            code = 1
        raise SystemExit(code)
    db_path, demo = _resolve_db(args)
    raise SystemExit(run(db_path, demo=demo))


if __name__ == "__main__":
    main()
