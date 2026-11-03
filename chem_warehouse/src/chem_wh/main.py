"""应用程序入口。"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running without install
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from chem_wh.app_context import AppContext
from chem_wh.ui.login_dialog import LoginDialog
from chem_wh.ui.main_window import MainWindow


def run(db_path: str | None = None) -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("危化品仓库管理系统")
    app.setStyle("Fusion")

    ctx = AppContext(db_path)
    ctx.ensure_seed()

    login = LoginDialog(ctx)
    if login.exec() != LoginDialog.Accepted:
        ctx.close()
        return 0

    win = MainWindow(ctx)
    win.show()
    code = app.exec()
    ctx.close()
    return code


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
