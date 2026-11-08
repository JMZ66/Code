"""命令行与图形入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bid-review",
        description="招投标文件格式与一致性审查助手（只读、离线）",
    )
    p.add_argument(
        "inputs",
        nargs="*",
        help="待审查的 DOCX/PDF/XLSX 文件",
    )
    p.add_argument(
        "-t",
        "--template",
        help="官方 Word 模板 DOCX（可选）",
    )
    p.add_argument(
        "-o",
        "--output",
        default="审查输出",
        help="报告输出目录（默认：审查输出）",
    )
    p.add_argument(
        "--gui",
        action="store_true",
        help="启动图形界面",
    )
    p.add_argument(
        "--version",
        action="store_true",
        help="显示版本",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        from bid_review import __version__

        print(__version__)
        return 0

    if args.gui or not args.inputs:
        from bid_review.gui.app import run_gui

        run_gui(
            initial_files=args.inputs or None,
            template=args.template,
            output=args.output,
        )
        return 0

    from bid_review.pipeline import run_review

    missing = [p for p in args.inputs if not Path(p).is_file()]
    if missing:
        print("找不到文件:", ", ".join(missing), file=sys.stderr)
        return 2
    if args.template and not Path(args.template).is_file():
        print("找不到模板:", args.template, file=sys.stderr)
        return 2

    result, paths = run_review(args.inputs, args.output, args.template)
    print("审查完成。")
    print("摘要:", result.summary())
    intact = all(i.unchanged for i in result.integrity)
    print("原文件未改动:" , "是" if intact else "否")
    for k, v in paths.items():
        print(f"报告[{k}]: {v}")
    # 有确定错误时返回 1，便于脚本化
    if any(i.severity.value == "确定错误" for i in result.issues):
        return 1
    if not intact:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
