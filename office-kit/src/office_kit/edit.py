"""Minimal OOXML edits.

Only the targeted text node or cell is changed. The package is written to a
new file unless ``overwrite`` is explicitly set. Other parts are copied
through and then checked byte for byte.
"""

from __future__ import annotations

import os
import re
import tempfile
import zipfile
from pathlib import Path

from lxml import etree

from office_kit.ooxml import XML_SPACE, element_children, local, parse_xml, qn, sha256_file
from office_kit.verify import outside, reparsed_matches, snapshot, structural_changes, verify_package

_SPREADSHEET = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


class EditError(ValueError):
    pass


def propose_edit(path: str | Path, anchor: str, new_text: str, old_text: str | None = None, *, allow_formula: bool = False) -> dict:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    part, inner = _split_anchor(anchor)
    try:
        with zipfile.ZipFile(source, "r") as archive:
            if part not in archive.namelist():
                raise EditError(f"包内没有部件 {part}")
            original = archive.read(part)
            shared = _load_shared(archive.read("xl/sharedStrings.xml")) if "xl/sharedStrings.xml" in archive.namelist() else []
        root = parse_xml(original)
        if inner.startswith("cell:"):
            coordinate = inner.split(":", 1)[1]
            cell, cell_path = _find_cell(root, coordinate)
            current = _cell_text(cell, shared)
            if old_text is not None and current != old_text:
                raise EditError(f"单元格现有文本与 old_text 不一致：{current!r}")
            _ensure_formula_allowed(cell, new_text, allow_formula)
            return {
                "ok": True,
                "anchor": anchor,
                "part": part,
                "target_path": cell_path,
                "old_text": current,
                "new_text": new_text,
                "allow_formula": allow_formula,
                "warnings": _cell_warnings(cell, new_text, allow_formula),
            }
        node = _locate(root, inner)
        if local(node) not in {"t", "delText"}:
            raise EditError("Word 替换只允许落在 w:t 或 w:delText 上，避免改到样式或结构。")
        current = node.text or ""
        if old_text is not None and current != old_text:
            raise EditError(f"现有文本与 old_text 不一致：{current!r}")
        return {
            "ok": True,
            "anchor": anchor,
            "part": part,
            "target_path": inner,
            "old_text": current,
            "new_text": new_text,
            "allow_formula": False,
            "warnings": [],
        }
    except EditError as exc:
        return {"ok": False, "error": str(exc), "anchor": anchor, "part": part}


def apply_edit(
    path: str | Path,
    anchor: str,
    new_text: str,
    output: str | Path,
    old_text: str | None = None,
    *,
    overwrite: bool = False,
    allow_formula: bool = False,
) -> dict:
    source = Path(path)
    destination = Path(output)
    plan = propose_edit(source, anchor, new_text, old_text, allow_formula=allow_formula)
    if not plan.get("ok"):
        return plan
    if destination.resolve() == source.resolve() and not overwrite:
        return {
            **plan,
            "ok": False,
            "error": "默认不覆盖原文件。请指定另一个输出路径，或显式传入 overwrite=true。",
            "written": False,
        }
    before_sha = sha256_file(source)
    part = plan["part"]
    with zipfile.ZipFile(source, "r") as archive:
        original = archive.read(part)
    root = parse_xml(original)
    before_tree = snapshot(root)
    if plan["target_path"].startswith("/") and not str(plan["anchor"]).split("#", 1)[1].startswith("cell:"):
        node = _locate(root, plan["target_path"])
        node.text = new_text
        if new_text[:1].isspace() or (new_text and new_text[-1].isspace()):
            node.set(qn(XML_SPACE, "space"), "preserve")
    else:
        cell, _cell_path = _find_cell(root, plan["anchor"].split("#", 1)[1].split(":", 1)[1])
        _write_cell(cell, new_text, allow_formula)
    modified = snapshot(root)
    new_bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    changes = structural_changes(before_tree, modified)
    leaked = outside(changes, plan["target_path"])
    serialization_ok = reparsed_matches(new_bytes, root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".office-kit-", suffix=destination.suffix, dir=destination.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        _rewrite(source, temp_path, {part: new_bytes})
        after_sha = sha256_file(source)
        if destination.resolve() == source.resolve():
            # Compare against the snapshot taken before this function, using the
            # temp file as the candidate package. The source hash is still the
            # original until os.replace.
            report = verify_package(
                source,
                temp_path,
                [part],
                source_sha_before=before_sha,
                source_sha_after=after_sha,
                structural=changes,
                leaked=leaked,
                serialization_ok=serialization_ok,
            )
        else:
            report = verify_package(
                source,
                temp_path,
                [part],
                source_sha_before=before_sha,
                source_sha_after=after_sha,
                structural=changes,
                leaked=leaked,
                serialization_ok=serialization_ok,
            )
        report["warnings"] = _merge_warnings(plan.get("warnings") or [], report["warnings"])
        if not report["ok"]:
            temp_path.unlink(missing_ok=True)
            return {**plan, "ok": False, "written": False, "output": None, "verification": report, "error": "完整性检查未通过，未写出文件。"}
        os.replace(temp_path, destination)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    written_sha = sha256_file(source)
    report["source_unchanged"] = written_sha == before_sha or destination.resolve() == source.resolve()
    report["source_sha256"] = written_sha
    if destination.resolve() != source.resolve() and written_sha != before_sha:
        report["ok"] = False
        report["source_unchanged"] = False
    return {
        **plan,
        "ok": report["ok"],
        "written": True,
        "output": str(destination),
        "overwrite": destination.resolve() == source.resolve(),
        "verification": report,
    }


def _rewrite(source: Path, destination: Path, replacements: dict[str, bytes]) -> None:
    with zipfile.ZipFile(source, "r") as zin, zipfile.ZipFile(destination, "w") as zout:
        seen = set()
        for info in zin.infolist():
            seen.add(info.filename)
            data = replacements.get(info.filename)
            if data is None:
                if info.is_dir():
                    continue
                data = zin.read(info.filename)
            cloned = zipfile.ZipInfo(filename=info.filename, date_time=info.date_time)
            cloned.compress_type = info.compress_type or zipfile.ZIP_DEFLATED
            cloned.external_attr = info.external_attr
            cloned.flag_bits = (info.flag_bits | 0x800) & ~0x8
            zout.writestr(cloned, data)
        missing = set(replacements) - seen
        if missing:
            raise EditError(f"不能新增部件：{sorted(missing)}")


def _split_anchor(anchor: str) -> tuple[str, str]:
    if "#" not in anchor:
        raise EditError("锚点格式应为 部件名#路径，例如 word/document.xml#/document/body[0]/p[0]/r[0]/t[0]")
    part, inner = anchor.split("#", 1)
    if not part or part.startswith("/") or ".." in part.split("/"):
        raise EditError("部件名非法")
    return part, inner


def _locate(root, path: str):
    bits = [bit for bit in path.split("/") if bit]
    if not bits:
        raise EditError("空路径")
    head = re.fullmatch(r"([A-Za-z_][\w.-]*)(?:\[(\d+)\])?", bits[0])
    if head is None or local(root) != head.group(1):
        raise EditError(f"路径与根元素不一致：{path}")
    node = root
    for bit in bits[1:]:
        match = re.fullmatch(r"([A-Za-z_][\w.-]*)\[(\d+)\]", bit)
        if match is None:
            raise EditError(f"无法解析路径段 {bit}")
        name, index = match.group(1), int(match.group(2))
        kids = [child for child in element_children(node) if local(child) == name]
        if index >= len(kids):
            raise EditError(f"路径不存在：{path}")
        node = kids[index]
    return node


def _find_cell(root, coordinate: str):
    found = _search_cell(root, "/" + local(root), coordinate)
    if found is None:
        raise EditError(f"工作表中没有单元格 {coordinate}")
    return found


def _search_cell(node, path: str, coordinate: str):
    if local(node) == "c" and node.get("r") == coordinate:
        return node, path
    counts: dict[str, int] = {}
    for child in element_children(node):
        name = local(child)
        index = counts.get(name, 0)
        counts[name] = index + 1
        found = _search_cell(child, f"{path}/{name}[{index}]", coordinate)
        if found is not None:
            return found
    return None


def _load_shared(data: bytes) -> list[str]:
    root = parse_xml(data)
    strings = []
    for item in element_children(root):
        if local(item) != "si":
            continue
        parts = []
        for node in item.iter():
            if isinstance(node.tag, str) and local(node) == "t" and node.text:
                parts.append(node.text)
        strings.append("".join(parts))
    return strings


def _cell_text(cell, shared: list[str]) -> str:
    inline = None
    for child in element_children(cell):
        if local(child) == "is":
            inline = child
    if inline is not None:
        return "".join(item.text or "" for item in inline.iter() if isinstance(item.tag, str) and local(item) == "t")
    if (cell.get("t") or "") == "s":
        value = _child_text(cell, "v")
        try:
            index = int(value)
        except ValueError:
            return value
        if 0 <= index < len(shared):
            return shared[index]
        return value
    return _child_text(cell, "v")


def _child_text(node, name: str) -> str:
    for child in element_children(node):
        if local(child) == name:
            return child.text or ""
    return ""


def _ensure_formula_allowed(cell, new_text: str, allow_formula: bool) -> None:
    has_formula = any(local(child) == "f" for child in element_children(cell))
    if has_formula and not allow_formula:
        raise EditError("该单元格含公式。默认拒绝修改，以免留下过期的计算链。若确实要改，请传 allow_formula=true。")
    if has_formula and allow_formula and not str(new_text).startswith("="):
        raise EditError("allow_formula 时新文本必须以 = 开头，表示替换公式本身，而不是把公式改成普通文本。")


def _cell_warnings(cell, new_text: str, allow_formula: bool) -> list[dict]:
    warnings = []
    if allow_formula and str(new_text).startswith("="):
        warnings.append({"code": "formula_cache_stale", "message": "已替换公式文本，缓存值和计算链未更新。"})
    if (cell.get("t") or "") == "s":
        warnings.append(
            {
                "code": "inline_string",
                "message": "原单元格使用共享字符串。为避免改到其他单元格，只把这一格改成 inlineStr，sharedStrings.xml 保持不动。",
            }
        )
    return warnings


def _write_cell(cell, new_text: str, allow_formula: bool) -> None:
    has_formula = any(local(child) == "f" for child in element_children(cell))
    if has_formula and allow_formula and str(new_text).startswith("="):
        for child in element_children(cell):
            if local(child) == "f":
                child.text = str(new_text)[1:]
        return
    namespace = cell.tag[1 : cell.tag.index("}")] if isinstance(cell.tag, str) and cell.tag.startswith("{") else _SPREADSHEET
    for child in list(element_children(cell)):
        cell.remove(child)
    cell.set("t", "inlineStr")
    inline = etree.SubElement(cell, qn(namespace, "is"))
    text = etree.SubElement(inline, qn(namespace, "t"))
    text.text = str(new_text)
    if str(new_text)[:1].isspace() or (new_text and str(new_text)[-1].isspace()):
        text.set(qn(XML_SPACE, "space"), "preserve")


def _merge_warnings(extra: list[dict], existing: list[dict]) -> list[dict]:
    seen = {(item.get("code"), item.get("message")) for item in existing}
    for item in extra:
        key = (item.get("code"), item.get("message"))
        if key not in seen:
            existing.append(item)
            seen.add(key)
    return existing
