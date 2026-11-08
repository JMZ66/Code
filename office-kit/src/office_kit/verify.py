"""Byte and structural checks around a minimal edit."""

from __future__ import annotations

import zipfile
from pathlib import Path

from lxml import etree

from office_kit.ooxml import element_children, local, package_feature_codes, parse_xml, part_hashes

_COMPLEX = {
    "calc_chain": "含 xl/calcChain.xml。本次没有改它，但 Excel 打开后可能重算。",
    "formulas": "含公式。未改到的公式单元格仍保留缓存；打开 Excel 后可能重算，界面结果不保证与缓存相同。",
    "revisions": "含修订（插入、删除或格式修订）。本次没有接受或拒绝修订。",
    "fields": "含域（PAGE、REF 等）。Word 打开后可能更新域结果。",
    "embeddings": "含嵌入对象。其部件未改，但不能保证宿主程序不刷新它们。",
    "charts": "含图表。图表部件未改，但不能保证与数据始终一致。",
    "smartart": "含 SmartArt / diagram。其部件未改，文本可能不在正文 XML 中。",
    "media": "含图片或媒体。这些部件未改。",
    "notes": "含脚注或尾注。",
    "threaded_comments": "含线程批注。",
    "vml": "含 VML 绘图。",
    "custom_xml": "含自定义 XML。",
}


def complexity_warnings(path: Path) -> list[dict]:
    warnings = []
    try:
        archive = zipfile.ZipFile(path, "r")
    except zipfile.BadZipFile:
        return [{"code": "not_ooxml", "message": "不是 OOXML 压缩包，无法做部件级字节比对。"}]
    with archive:
        names = [info.filename for info in archive.infolist() if not info.is_dir()]
        codes = set(package_feature_codes(names))
        for name in names:
            if not name.endswith(".xml"):
                continue
            if name != "word/document.xml" and not name.startswith("xl/worksheets/"):
                continue
            data = archive.read(name)
            if b"w:ins" in data or b"w:del" in data or b"w:moveFrom" in data or b"w:rPrChange" in data:
                codes.add("revisions")
            if b"w:fldChar" in data or b"w:instrText" in data or b"w:fldSimple" in data:
                codes.add("fields")
            if b"<f" in data or b"<f " in data or b":f>" in data:
                codes.add("formulas")
    for code in sorted(codes):
        message = _COMPLEX.get(code)
        if message:
            warnings.append({"code": code, "message": message})
    return warnings


def snapshot(root: etree._Element) -> dict[str, tuple]:
    return _walk(root, "/" + local(root))


def _walk(node: etree._Element, path: str) -> dict[str, tuple]:
    attrs = tuple(sorted((key, value) for key, value in node.attrib.items()))
    items = {path: (local(node), attrs, node.text or "", node.tail or "")}
    counts: dict[str, int] = {}
    for child in element_children(node):
        name = local(child)
        index = counts.get(name, 0)
        counts[name] = index + 1
        items.update(_walk(child, f"{path}/{name}[{index}]"))
    return items


def structural_changes(before: dict, after: dict) -> list[dict]:
    changes = []
    for path in sorted(set(before) | set(after)):
        left = before.get(path)
        right = after.get(path)
        if left == right or _equivalent(left, right):
            continue
        changes.append({"path": path, "before": _public(left), "after": _public(right)})
    return changes


def outside(changes: list[dict], allowed: str) -> list[dict]:
    leaked = []
    for change in changes:
        path = change["path"]
        if path == allowed or path.startswith(allowed + "/"):
            continue
        leaked.append(change)
    return leaked


def verify_package(
    source: Path,
    output: Path,
    intended_parts: list[str],
    *,
    source_sha_before: str,
    source_sha_after: str,
    structural: list[dict],
    leaked: list[dict],
    serialization_ok: bool,
) -> dict:
    before = part_hashes(source) if source.resolve() != output.resolve() else None
    after = part_hashes(output)
    unexpected = []
    if before is not None:
        for name, digest in before.items():
            if name in intended_parts:
                continue
            if after.get(name) != digest:
                unexpected.append(name)
        for name in after:
            if name not in before and name not in intended_parts:
                unexpected.append(name)
    source_unchanged = source_sha_before == source_sha_after
    ok = source_unchanged and serialization_ok and not unexpected and not leaked
    return {
        "ok": ok,
        "source_unchanged": source_unchanged,
        "source_sha256": source_sha_after,
        "output_sha256": _file_sha(output),
        "intended_parts": intended_parts,
        "unexpected_part_changes": unexpected,
        "structural_diff": structural[:80],
        "structural_diff_outside_target": leaked[:40],
        "serialization_matches_tree": serialization_ok,
        "warnings": complexity_warnings(source if source.exists() else output),
    }


def _file_sha(path: Path) -> str:
    from office_kit.ooxml import sha256_file

    return sha256_file(path)


def _equivalent(left, right) -> bool:
    if left is None or right is None:
        return False
    if left[0] != right[0] or left[1] != right[1]:
        return False
    return _blank(left[2], right[2]) and _blank(left[3], right[3])


def _blank(left: str, right: str) -> bool:
    return left == right or (left.strip() == "" and right.strip() == "")


def _public(item) -> dict | None:
    if item is None:
        return None
    return {"name": item[0], "text": item[2]}


def reparsed_matches(data: bytes, modified: etree._Element) -> bool:
    try:
        again = parse_xml(data)
    except etree.XMLSyntaxError:
        return False
    return not structural_changes(snapshot(modified), snapshot(again))
