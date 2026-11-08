"""Minimal MCP stdio server (Content-Length framing, no network).

Configure a client with::

    {"mcpServers": {"office-kit": {"command": "python", "args": ["-m", "office_kit.mcp_server"]}}}
"""

from __future__ import annotations

import json
import sys
from typing import Any

from office_kit import __version__
from office_kit.api import (
    apply_edit,
    check_files,
    diff_files,
    document_outline,
    propose_edit,
    read_cells,
    read_paragraphs,
    read_section,
    read_table,
    search_document,
)

_PROTOCOL = "2024-11-05"


def tools() -> list[dict]:
    return [
        _tool("list_outline", "列出 Word 标题大纲或 Excel 工作表，分页返回。", {"path": _str, "offset": _int, "limit": _int, "max_chars": _int}, ["path"]),
        _tool("read_section", "按大纲锚点或序号读取该节，直到下一个同级或更高级标题。", {"path": _str, "anchor": _str, "index": _int, "max_chars": _int, "max_table_rows": _int}, ["path"]),
        _tool("read_paragraphs", "按段落序号读取半开区间 [start, end)。", {"path": _str, "start": _int, "end": _int, "max_chars": _int}, ["path"]),
        _tool("read_table", "按锚点或顶层表序号读取表格，含合并信息和嵌套表锚点。", {"path": _str, "anchor": _str, "index": _int, "row_offset": _int, "limit": _int, "max_chars": _int}, ["path"]),
        _tool("read_cells", "按工作表和 A1 区域读取单元格，不返回区域外的格子。", {"path": _str, "sheet": _str, "cell_range": _str, "limit": _int, "max_chars": _int}, ["path", "sheet", "cell_range"]),
        _tool("search", "搜索正文、原文（含删除）、批注和单元格，返回锚点与片段。", {"path": _str, "query": _str, "regex": _bool, "limit": _int, "max_chars": _int}, ["path", "query"]),
        _tool("run_checks", "对一个或多个文件运行确定性核对。推断接口默认关闭。", {"paths": {"type": "array", "items": {"type": "string"}}, "profile": {"type": "object"}}, ["paths"]),
        _tool("diff_documents", "比较两个文件的部件哈希和同锚点文本。", {"left": _str, "right": _str, "limit": _int}, ["left", "right"]),
        _tool("propose_edit", "检查一处最小替换是否可做，不写文件。", {"path": _str, "anchor": _str, "new_text": _str, "old_text": _str, "allow_formula": _bool}, ["path", "anchor", "new_text"]),
        _tool(
            "apply_edit",
            "把一处替换写到新文件并做完整性检查。默认不覆盖原文件。",
            {"path": _str, "anchor": _str, "new_text": _str, "output": _str, "old_text": _str, "overwrite": _bool, "allow_formula": _bool},
            ["path", "anchor", "new_text", "output"],
        ),
    ]


def call_tool(name: str, arguments: dict[str, Any]) -> dict:
    args = arguments or {}
    if name == "list_outline":
        return document_outline(args["path"], offset=args.get("offset") or 0, limit=args.get("limit") or 40, max_chars=args.get("max_chars") or 8000)
    if name == "read_section":
        return read_section(args["path"], anchor=args.get("anchor"), index=args.get("index") or 0, max_chars=args.get("max_chars") or 8000, max_table_rows=args.get("max_table_rows") or 20)
    if name == "read_paragraphs":
        return read_paragraphs(args["path"], start=args.get("start") or 0, end=args.get("end"), max_chars=args.get("max_chars") or 8000)
    if name == "read_table":
        return read_table(args["path"], anchor=args.get("anchor"), index=args.get("index"), row_offset=args.get("row_offset") or 0, limit=args.get("limit") or 40, max_chars=args.get("max_chars") or 8000)
    if name == "read_cells":
        return read_cells(args["path"], args["sheet"], args["cell_range"], limit=args.get("limit") or 200, max_chars=args.get("max_chars") or 8000)
    if name == "search":
        return search_document(args["path"], args["query"], regex=bool(args.get("regex")), limit=args.get("limit") or 20, max_chars=args.get("max_chars") or 8000)
    if name == "run_checks":
        return check_files(args["paths"], profile=args.get("profile"))
    if name == "diff_documents":
        return diff_files(args["left"], args["right"], limit=args.get("limit") or 100)
    if name == "propose_edit":
        return propose_edit(args["path"], args["anchor"], args["new_text"], args.get("old_text"), allow_formula=bool(args.get("allow_formula")))
    if name == "apply_edit":
        return apply_edit(
            args["path"],
            args["anchor"],
            args["new_text"],
            args["output"],
            args.get("old_text"),
            overwrite=bool(args.get("overwrite")),
            allow_formula=bool(args.get("allow_formula")),
        )
    raise KeyError(name)


def serve(stdin=None, stdout=None) -> None:
    reader = stdin if stdin is not None else sys.stdin.buffer
    writer = stdout if stdout is not None else sys.stdout.buffer
    while True:
        message = _read(reader)
        if message is None:
            return
        if message.get("method") == "notifications/initialized":
            continue
        response = _dispatch(message)
        if response is not None:
            _write(writer, response)


def _dispatch(message: dict) -> dict | None:
    method = message.get("method")
    msg_id = message.get("id")
    if method == "initialize":
        return _result(msg_id, {"protocolVersion": _PROTOCOL, "capabilities": {"tools": {}}, "serverInfo": {"name": "office-kit", "version": __version__}})
    if method == "tools/list":
        return _result(msg_id, {"tools": tools()})
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            payload = call_tool(params.get("name") or "", params.get("arguments") or {})
            return _result(msg_id, {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}], "isError": False})
        except Exception as exc:
            return _result(msg_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
    if msg_id is None:
        return None
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"未知方法 {method}"}}


def _result(msg_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _read(reader) -> dict | None:
    headers = {}
    while True:
        line = reader.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        if b":" in line:
            key, value = line.split(b":", 1)
            headers[key.strip().lower()] = value.strip()
    length = int(headers.get(b"content-length", b"0"))
    if length <= 0:
        return None
    body = reader.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _write(writer, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    writer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    writer.write(data)
    writer.flush()


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
    }


_str = {"type": "string"}
_int = {"type": "integer"}
_bool = {"type": "boolean"}


def main() -> None:
    serve()


if __name__ == "__main__":
    main()
