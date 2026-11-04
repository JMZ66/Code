from __future__ import annotations

import argparse
import os
import sys
import tempfile
import traceback
from pathlib import Path


def _emit(message: str, log_path: str | None) -> None:
    try:
        print(message, flush=True)
    except Exception:
        pass
    if log_path:
        Path(log_path).write_text(message + "\n", encoding="utf-8")


def _install_crash_log(data_dir: Path) -> None:
    log = data_dir / "logs" / "crash.log"
    log.parent.mkdir(parents=True, exist_ok=True)

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            log.write_text(text, encoding="utf-8")
        except OSError:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def run_self_test(mzml: Path, log_path: str | None) -> int:
    # Windows 上使用 Qt 自带的 windows 平台插件。强制 offscreen 需要额外的 qoffscreen 插件，
    # 打包后不一定在。Linux 测试机没有桌面，才使用 offscreen。
    if sys.platform != "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from gcms_kb.gui.main_window import MainWindow

    data_dir = Path(tempfile.mkdtemp(prefix="gcms_selftest_"))
    app = QApplication(["GCMS_KnowledgeBase"])
    window = MainWindow(data_dir=data_dir, interactive_notices=False)
    window.show()
    app.processEvents()
    results = window.import_paths_sync([mzml], "self-test")
    app.processEvents()
    if not results or not results[0].get("ok"):
        error = "" if not results else results[0].get("error")
        _emit(f"SELF_TEST_FAIL {error}", log_path)
        return 1
    sample_id = results[0]["id"]
    _sample, run = window.kb.load_sample_run(sample_id)
    if run.n_scans < 1 or float(run.tic.sum()) <= 0:
        _emit("SELF_TEST_FAIL empty chromatogram", log_path)
        return 1
    hint = run.file_hint.replace("\n", " ")
    _emit(
        f"SELF_TEST_OK scans={run.n_scans} tic_sum={float(run.tic.sum()):.6g} synthetic={int(run.is_synthetic)} hint={hint}",
        log_path,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("MPLBACKEND", "Agg")
    os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")
    parser = argparse.ArgumentParser(prog="GCMS_KnowledgeBase")
    parser.add_argument("--self-test", nargs="?", const="__bundled__", default=None)
    parser.add_argument("--self-test-log", default=None)
    parser.add_argument("--net-probe", action="store_true")
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args(argv)
    if args.net_probe:
        from gcms_kb.net_probe import net_probe

        return net_probe()
    if args.self_test:
        if args.self_test == "__bundled__":
            from gcms_kb.paths import resource_path

            mzml = resource_path("testdata", "public", "small.pwiz.1.1.mzML")
        else:
            mzml = Path(args.self_test)
        if not mzml.is_file():
            _emit(f"SELF_TEST_FAIL missing {mzml}", args.self_test_log)
            return 1
        return run_self_test(mzml, args.self_test_log)

    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    from gcms_kb.gui.main_window import MainWindow
    from gcms_kb.paths import app_data_dir, resource_path

    data_dir = Path(args.data_dir) if args.data_dir else app_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    _install_crash_log(data_dir)
    app = QApplication(sys.argv if argv is None else ["GCMS_KnowledgeBase", *argv])
    font_file = resource_path("fonts", "wqy-microhei.ttc")
    if font_file.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_file))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 10))
    window = MainWindow(data_dir=data_dir, interactive_notices=True)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
