"""Entry point for the desktop application and the packaged self-test."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="labuv")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--gui-probe", action="store_true")
    parser.add_argument("--self-test-report", default="")
    parser.add_argument("--db", default="")
    args = parser.parse_args(argv)
    if args.self_test or args.gui_probe:
        from labuv.selftest import run_gui_probe, run_self_test

        code = 0
        if args.self_test:
            code = run_self_test(args.db or None, args.self_test_report or None)
        if code == 0 and args.gui_probe:
            code = run_gui_probe(args.db or None)
        return code
    from PySide6.QtWidgets import QApplication

    from labuv.gui.window import MainWindow
    from labuv.paths import bundle_root

    application = QApplication(sys.argv)
    database = args.db or str(Path.home() / "labuv-projects.sqlite")
    if getattr(sys, "frozen", False):
        database = args.db or str(Path(sys.executable).resolve().parent / "labuv-projects.sqlite")
    window = MainWindow(database)
    window.show()
    window.statusBar().showMessage("离线运行。不申报 CNAS 认可。")
    _ = bundle_root()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
