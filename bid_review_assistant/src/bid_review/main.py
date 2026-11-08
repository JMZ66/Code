"""入口：CLI 与 GUI。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _configure_stdio() -> None:
    """避免 Windows 默认 cp1252 控制台无法打印中文进度。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def _safe_print(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        sys.stdout.buffer.write((msg + "\n").encode(encoding, errors="replace"))
        sys.stdout.buffer.flush()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bid-review",
        description="招投标文件审查助手（只读·离线·中文）",
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="待审查的 DOCX/PDF/XLSX 文件",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=str(Path.cwd() / "bid_review_reports"),
        help="报告输出目录",
    )
    parser.add_argument(
        "-t",
        "--template",
        default=None,
        help="官方 Word 模板 DOCX（用于反推格式要求）",
    )
    parser.add_argument(
        "-p",
        "--profile",
        default=None,
        help="格式配置 JSON（可与模板叠加）",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="启动图形界面",
    )
    parser.add_argument(
        "--json-summary",
        action="store_true",
        help="在标准输出打印 JSON 摘要",
    )
    parser.add_argument(
        "--role",
        action="append",
        default=[],
        metavar="FILENAME=ROLE",
        help="指定文件角色，如 招标正文.docx=正文；可重复",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="运行内置只读自检（用于打包冒烟）",
    )
    parser.add_argument(
        "--gui-probe",
        action="store_true",
        help="创建并立即关闭 GUI（打包探针）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.gui_probe:
        from PySide6.QtWidgets import QApplication

        from bid_review.gui.app import MainWindow

        app = QApplication([])
        win = MainWindow()
        win.show()
        win.close()
        app.quit()
        print("gui-probe: ok")
        return 0

    if args.self_test:
        return _run_self_test(args.output)

    if args.gui or not args.inputs:
        # 无输入文件时进入图形界面；显式 --gui 同样如此
        from bid_review.gui import launch_gui

        return launch_gui()

    role_hints = {}
    for item in args.role:
        if "=" not in item:
            parser.error(f"--role 格式应为 FILENAME=ROLE，收到: {item}")
        name, role = item.split("=", 1)
        role_hints[name.strip()] = role.strip()

    from bid_review.pipeline import run_review

    result, paths = run_review(
        args.inputs,
        args.output,
        template_docx=args.template,
        profile_json=args.profile,
        role_hints=role_hints,
        progress=_safe_print,
    )
    _safe_print("—— 审查完成 ——")
    for k, v in result.summary().items():
        _safe_print(f"{k}: {v}")
    _safe_print("报告：")
    for kind, path in paths.items():
        _safe_print(f"  [{kind}] {path}")
    if args.json_summary:
        _safe_print(json.dumps(result.to_dict()["summary"], ensure_ascii=False))
    return 0


def _run_self_test(output_dir: str) -> int:
    """打包后离线冒烟：生成最小样例并跑通审查流水线。"""
    import tempfile
    from docx import Document
    from docx.shared import Cm, Pt
    from docx.oxml.ns import qn
    from openpyxl import Workbook

    from bid_review.hashutil import sha256_file
    from bid_review.pipeline import run_review

    with tempfile.TemporaryDirectory(prefix="bid_review_selftest_") as tmp:
        tmp_path = Path(tmp)
        main_doc = tmp_path / "正文.docx"
        budget = tmp_path / "预算.xlsx"
        template = tmp_path / "模板.docx"

        def _font(run, name="宋体", size=12):
            run.font.name = name
            run.font.size = Pt(size)
            rPr = run._element.get_or_add_rPr()
            rFonts = rPr.get_or_add_rFonts()
            rFonts.set(qn("w:eastAsia"), name)

        doc = Document()
        for s in doc.sections:
            s.top_margin = Cm(2.54)
            s.bottom_margin = Cm(2.54)
            s.left_margin = Cm(3.17)
            s.right_margin = Cm(3.17)
        p = doc.add_paragraph()
        r = p.add_run("项目名称：自检项目")
        _font(r)
        p2 = doc.add_paragraph()
        r2 = p2.add_run("工期：30天；预算金额：10万元；不接受联合体投标。")
        _font(r2)
        p3 = doc.add_paragraph()
        r3 = p3.add_run("联系人：【请填写】")
        _font(r3)
        doc.save(main_doc)

        tdoc = Document()
        tp = tdoc.add_paragraph()
        tr = tp.add_run("模板正文")
        _font(tr)
        tdoc.save(template)

        wb = Workbook()
        ws = wb.active
        ws.append(["名称", "数量", "单位", "合价"])
        ws.append(["设备A", 2, "台", 120000])
        ws.append(["合计", "", "", 120000])
        wb.save(budget)

        before = {p.name: sha256_file(p) for p in (main_doc, budget, template)}
        result, paths = run_review(
            [main_doc, budget],
            output_dir or str(tmp_path / "out"),
            template_docx=template,
            role_hints={"正文.docx": "正文", "预算.xlsx": "预算"},
            progress=_safe_print,
        )
        after = {p.name: sha256_file(p) for p in (main_doc, budget, template)}
        assert before == after
        assert all(i.unchanged for i in result.integrity)
        assert paths["excel"]
        _safe_print(json.dumps({"ok": True, "summary": result.summary(), "reports": paths}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
