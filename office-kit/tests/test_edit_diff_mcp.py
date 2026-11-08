import json
import os
import subprocess
import sys
from pathlib import Path

from office_kit.api import document_outline, read_cells, read_paragraphs, read_section, read_table, search_document
from office_kit.diffing import diff_paths
from office_kit.edit import apply_edit, propose_edit
from office_kit.mcp_server import call_tool
from office_kit.ooxml import part_hashes, sha256_file
from office_kit.parse import parse_path

from tests.factory import bill_xlsx, complex_docx


def _frame(payload: dict) -> bytes:
    data = json.dumps(payload).encode("utf-8")
    return f"Content-Length: {len(data)}\r\n\r\n".encode("ascii") + data


def _read_frame(stream) -> dict:
    headers = {}
    while True:
        line = stream.readline()
        if line in (b"\r\n", b"\n"):
            break
        key, value = line.split(b":", 1)
        headers[key.strip().lower()] = value.strip()
    length = int(headers[b"content-length"])
    return json.loads(stream.read(length).decode("utf-8"))


def test_word_edit_keeps_other_parts_and_refuses_overwrite(tmp_path):
    source = complex_docx(tmp_path / "complex.docx")
    before = sha256_file(source)
    before_parts = part_hashes(source)
    anchor = "word/document.xml#/document/body[0]/p[0]/r[0]/t[0]"
    output = tmp_path / "complex.edited.docx"
    refused = apply_edit(source, anchor, "封面标题修订", source)
    assert refused["ok"] is False
    assert sha256_file(source) == before
    plan = propose_edit(source, anchor, "封面标题修订", "封面标题")
    assert plan["ok"] is True
    result = apply_edit(source, anchor, "封面标题修订", output, "封面标题")
    assert result["ok"] is True
    assert result["written"] is True
    assert sha256_file(source) == before
    after_parts = part_hashes(output)
    for name, digest in before_parts.items():
        if name != "word/document.xml":
            assert after_parts[name] == digest
    edited = parse_path(output)
    assert edited.word.paragraphs[0].text_accepted == "封面标题修订"
    assert edited.word.paragraphs[1].text_accepted == "投标人须知"
    diff = result["verification"]["structural_diff"]
    assert diff
    assert all(item["path"] == "/document/body[0]/p[0]/r[0]/t[0]" or item["path"].startswith("/document/body[0]/p[0]/r[0]/t[0]/") for item in diff)
    assert result["verification"]["unexpected_part_changes"] == []
    compared = diff_paths(source, output)
    assert "word/document.xml" in compared["parts"]["modified"]
    assert any(item["op"] == "modified" and item["right"] == "封面标题修订" for item in compared["changes"])


def test_excel_edit_does_not_rewrite_shared_strings_or_formulas(tmp_path):
    source = bill_xlsx(tmp_path / "bill.xlsx")
    before = sha256_file(source)
    before_parts = part_hashes(source)
    document = parse_path(source)
    sheet = document.excel.sheets[0]
    shared_cells = [cell for cell in sheet.cells if cell.cached_text == "共用标签"]
    assert [cell.coordinate for cell in shared_cells] == ["H3", "I3"]
    anchor = shared_cells[0].anchor
    output = tmp_path / "bill.edited.xlsx"
    result = apply_edit(source, anchor, "共用标签-改", output, "共用标签")
    assert result["ok"] is True, result
    assert sha256_file(source) == before
    after_parts = part_hashes(output)
    assert after_parts["xl/sharedStrings.xml"] == before_parts["xl/sharedStrings.xml"]
    edited = parse_path(output)
    by_coord = {cell.coordinate: cell.cached_text for cell in edited.excel.sheets[0].cells}
    assert by_coord["H3"] == "共用标签-改"
    assert by_coord["I3"] == "共用标签"
    formula = next(cell for cell in document.excel.sheets[0].cells if cell.formula)
    refused = apply_edit(source, formula.anchor, "文本", tmp_path / "no.xlsx")
    assert refused["ok"] is False
    assert not (tmp_path / "no.xlsx").exists()
    assert sha256_file(source) == before


def test_scoped_reads_and_mcp(tmp_path):
    path = complex_docx(tmp_path / "complex.docx")
    outline = document_outline(path, limit=2)
    assert outline["total"] > 2
    assert outline["truncated"] is True
    assert outline["next_offset"] == 2
    assert outline["source"]["sha256"] == sha256_file(path)
    section = read_section(path, anchor=outline["items"][0]["anchor"])
    assert section["items"]
    paragraphs = read_paragraphs(path, 0, 3)
    assert len(paragraphs["items"]) == 3
    table = read_table(path, index=0, limit=2)
    assert table["items"][0]["cells"][0]["grid_span"] == 2
    assert table["total"] == 3
    found = search_document(path, "被批注的句子")
    assert found["items"][0]["anchor"]
    bill = bill_xlsx(tmp_path / "bill.xlsx")
    cells = read_cells(bill, "清单", "A3:D4", limit=10)
    assert {item["coordinate"] for item in cells["items"]} <= {"A3", "B3", "C3", "D3", "A4", "B4", "C4", "D4"}
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    proc = subprocess.Popen(
        [sys.executable, "-m", "office_kit.mcp_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        cwd=tmp_path,
        env=env,
    )
    assert proc.stdin and proc.stdout
    proc.stdin.write(
        _frame(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
            }
        )
    )
    proc.stdin.write(_frame({"jsonrpc": "2.0", "method": "notifications/initialized"}))
    proc.stdin.write(_frame({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))
    proc.stdin.write(
        _frame(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "search", "arguments": {"path": str(path), "query": "页眉甲", "limit": 5}},
            }
        )
    )
    proc.stdin.close()
    first = _read_frame(proc.stdout)
    second = _read_frame(proc.stdout)
    third = _read_frame(proc.stdout)
    proc.wait(timeout=20)
    assert first["result"]["serverInfo"]["name"] == "office-kit"
    names = [item["name"] for item in second["result"]["tools"]]
    assert "list_outline" in names and "apply_edit" in names and "run_checks" in names
    body = json.loads(third["result"]["content"][0]["text"])
    assert any("页眉" in item["snippet"] for item in body["items"])
    direct = call_tool("list_outline", {"path": str(path), "limit": 1})
    assert direct["truncated"] is True

