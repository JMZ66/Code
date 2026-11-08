"""Command line entry. No network."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bidreview.engine import hash_paths, load_rules, review
from bidreview.version import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bidreview",
        description="招投标文件审查助手：只读、离线，不改原文件。",
    )
    parser.add_argument("--version", action="version", version=f"招投标文件审查助手 {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="审查一组文件并写出报告")
    check.add_argument("--template", help="官方 Word 模板（.docx）。使用 --manifest 时可省略")
    check.add_argument("--manifest", help="JSON 任务清单")
    check.add_argument("--out", required=True, help="报告输出目录，不要指向原文件本身")
    check.add_argument("--rules", help="用户规则 JSON")
    check.add_argument("--conforming", action="append", default=[], help="需要按模板核对版式的文件名，可重复")
    check.add_argument("--file", action="append", default=[], help="角色=路径，例如 tender=01_招标文件.docx")

    sub.add_parser("gui", help="打开图形界面")
    sub.add_parser("self-test", help="用临时文件做离线自检，不读取用户文档")

    digest = sub.add_parser("hash", help="计算文件 SHA-256")
    digest.add_argument("paths", nargs="+")
    return parser


def _from_manifest(path: Path) -> tuple[Path, list[tuple[Path, str, str]], set[str], Path | None]:
    data = json.loads(path.read_text(encoding="utf-8"))
    root = path.parent
    template = (root / data["template"]).resolve()
    documents = []
    for item in data.get("documents") or []:
        documents.append(((root / item["path"]).resolve(), item.get("role") or "other", item.get("title") or ""))
    conforming = {name for name in data.get("conforming") or []}
    rules = (root / data["rules"]).resolve() if data.get("rules") else None
    return template, documents, conforming, rules


def _from_files(pairs: list[str], root: Path) -> list[tuple[Path, str, str]]:
    documents = []
    for item in pairs:
        if "=" not in item:
            raise SystemExit(f"--file 需要 角色=路径，收到：{item}")
        role, raw = item.split("=", 1)
        documents.append(((root / raw).resolve(), role.strip(), ""))
    return documents


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "gui":
        from bidreview.gui import main as gui_main

        return gui_main()
    if args.command == "self-test":
        from bidreview.selftest import run_self_test

        return run_self_test()
    if args.command == "hash":
        for digest, file_path in hash_paths([Path(item) for item in args.paths]):
            print(f"{digest}  {file_path}")
        return 0

    template = None
    documents = []
    conforming: set[str] = set()
    rules_path = None
    if args.manifest:
        template, documents, conforming, rules_path = _from_manifest(Path(args.manifest))
        if args.rules:
            rules_path = Path(args.rules)
        conforming.update(args.conforming)
    else:
        if not args.file:
            raise SystemExit("请提供 --manifest，或同时提供 --template 和至少一个 --file 角色=路径")
        if not args.template:
            raise SystemExit("没有 --manifest 时必须提供 --template")
        documents = _from_files(args.file, Path.cwd())
        conforming = set(args.conforming)
        rules_path = Path(args.rules).resolve() if args.rules else None
    if args.template:
        template = Path(args.template).resolve()
    if template is None:
        raise SystemExit("未指定模板")
    rules = load_rules(rules_path) if rules_path else {}
    result = review(
        template=template,
        documents=documents,
        conforming=conforming,
        rules=rules,
        out_dir=Path(args.out),
    )
    summary = result.to_summary()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"报告目录：{result.out_dir}")
    return 0 if result.inputs_unchanged else 2


if __name__ == "__main__":
    sys.exit(main())
