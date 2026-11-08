"""Command line wrapper around the same functions the MCP server calls."""

from __future__ import annotations

import argparse
import json
import sys

from office_kit.api import (
    apply_edit,
    check_files,
    diff_files,
    document_outline,
    parse_document,
    propose_edit,
    search_document,
)
from office_kit.mcp_server import main as mcp_main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="office-kit", description="招投标 Word/Excel 解析、核对与最小改写")
    sub = parser.add_subparsers(dest="cmd", required=True)

    parse_cmd = sub.add_parser("parse", help="解析单个文件并输出 JSON")
    parse_cmd.add_argument("path")
    parse_cmd.add_argument("--out")

    outline = sub.add_parser("outline", help="输出大纲")
    outline.add_argument("path")
    outline.add_argument("--limit", type=int, default=40)

    search = sub.add_parser("search", help="按原文搜索并返回位置")
    search.add_argument("path")
    search.add_argument("query")
    search.add_argument("--regex", action="store_true")
    search.add_argument("--limit", type=int, default=20)

    check = sub.add_parser("check", help="对多个文件做确定性核对")
    check.add_argument("paths", nargs="+")
    check.add_argument("--profile")

    diff = sub.add_parser("diff", help="比较两个文件")
    diff.add_argument("left")
    diff.add_argument("right")

    edit = sub.add_parser("edit", help="最小替换并写出新文件")
    edit.add_argument("path")
    edit.add_argument("--anchor", required=True)
    edit.add_argument("--text", required=True)
    edit.add_argument("--old")
    edit.add_argument("--output", required=True)
    edit.add_argument("--overwrite", action="store_true")
    edit.add_argument("--allow-formula", action="store_true")
    edit.add_argument("--dry-run", action="store_true")

    sub.add_parser("mcp", help="以 stdio 启动 MCP 服务")

    args = parser.parse_args(argv)
    if args.cmd == "mcp":
        mcp_main()
        return 0
    if args.cmd == "parse":
        payload = parse_document(args.path)
        _emit(payload, args.out)
        return 0 if payload["status"] in {"ok", "reserved", "converter_unavailable"} else 1
    if args.cmd == "outline":
        _emit(document_outline(args.path, limit=args.limit))
        return 0
    if args.cmd == "search":
        _emit(search_document(args.path, args.query, regex=args.regex, limit=args.limit))
        return 0
    if args.cmd == "check":
        profile = json.loads(PathText.read(args.profile)) if args.profile else None
        payload = check_files(args.paths, profile=profile)
        _emit(payload)
        return 1 if any(item["severity"] == "error" and item["origin"] == "source" for item in payload["findings"]) else 0
    if args.cmd == "diff":
        _emit(diff_files(args.left, args.right))
        return 0
    if args.cmd == "edit":
        if args.dry_run:
            _emit(propose_edit(args.path, args.anchor, args.text, args.old, allow_formula=args.allow_formula))
            return 0
        payload = apply_edit(
            args.path,
            args.anchor,
            args.text,
            args.output,
            args.old,
            overwrite=args.overwrite,
            allow_formula=args.allow_formula,
        )
        _emit(payload)
        return 0 if payload.get("ok") else 1
    return 2


class PathText:
    @staticmethod
    def read(path: str) -> str:
        from pathlib import Path

        return Path(path).read_text(encoding="utf-8")


def _emit(payload: dict, out: str | None = None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if out:
        from pathlib import Path

        Path(out).write_text(text, encoding="utf-8")
        return
    sys.stdout.write(text + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
