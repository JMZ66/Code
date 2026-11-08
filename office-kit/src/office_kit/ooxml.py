"""OOXML package helpers. Parts are read as zip entries; nothing is written here."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
XML_SPACE = "http://www.w3.org/XML/1998/namespace"

PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    huge_tree=True,
    remove_blank_text=False,
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local(el: etree._Element) -> str:
    tag = el.tag
    if not isinstance(tag, str):
        return ""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def qn(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def element_children(el: etree._Element) -> list[etree._Element]:
    return [child for child in el if isinstance(child.tag, str)]


def attr(el: etree._Element | None, name: str, ns: str | None = None) -> str | None:
    """Read an OOXML attribute.

    Word attributes are usually in the element's namespace (``w:val``).
    Relationship ids are in the relationships namespace and need ``ns=R``.
    Unprefixed attributes (spreadsheet ``r``, package rels) have no namespace.
    """

    if el is None:
        return None
    if ns is not None:
        return el.get(qn(ns, name))
    plain = el.get(name)
    if plain is not None:
        return plain
    tag = el.tag if isinstance(el.tag, str) else ""
    if tag.startswith("{"):
        element_ns = tag[1 : tag.index("}")]
        return el.get(qn(element_ns, name))
    return None


def on_off(el: etree._Element | None) -> bool | None:
    if el is None:
        return None
    value = attr(el, "val")
    if value is None:
        return True
    return value.lower() not in {"0", "false", "off", "none"}


def child(el: etree._Element | None, name: str) -> etree._Element | None:
    if el is None:
        return None
    for item in element_children(el):
        if local(item) == name:
            return item
    return None


def children_named(el: etree._Element, name: str) -> list[etree._Element]:
    return [item for item in element_children(el) if local(item) == name]


def indexed_children(el: etree._Element, parent_path: str) -> list[tuple[etree._Element, str]]:
    counts: dict[str, int] = {}
    found: list[tuple[etree._Element, str]] = []
    for item in element_children(el):
        name = local(item)
        index = counts.get(name, 0)
        counts[name] = index + 1
        found.append((item, f"{parent_path}/{name}[{index}]"))
    return found


def parse_xml(data: bytes) -> etree._Element:
    return etree.fromstring(data, PARSER)


def join_target(base_part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    base_dir = base_part.rsplit("/", 1)[0] if "/" in base_part else ""
    pieces = base_dir.split("/") if base_dir else []
    for piece in target.split("/"):
        if piece == "..":
            if pieces:
                pieces.pop()
        elif piece and piece != ".":
            pieces.append(piece)
    return "/".join(pieces)


class Package:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.zip = zipfile.ZipFile(self.path, "r")
        self.names = [info.filename for info in self.zip.infolist() if not info.is_dir()]
        self.name_set = set(self.names)

    def close(self) -> None:
        self.zip.close()

    def __enter__(self) -> "Package":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def read(self, name: str) -> bytes | None:
        if name not in self.name_set:
            return None
        return self.zip.read(name)

    def xml(self, name: str) -> etree._Element | None:
        data = self.read(name)
        if not data:
            return None
        return parse_xml(data)

    def rels(self, part: str) -> dict[str, str]:
        directory, _, filename = part.rpartition("/")
        rels_name = f"{directory}/_rels/{filename}.rels" if directory else f"_rels/{filename}.rels"
        root = self.xml(rels_name)
        mapping: dict[str, str] = {}
        if root is None:
            return mapping
        for rel in root:
            if local(rel) != "Relationship":
                continue
            rel_id = rel.get("Id")
            target = rel.get("Target")
            if rel_id and target:
                mapping[rel_id] = join_target(part, target)
        return mapping


def part_hashes(path: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    with zipfile.ZipFile(path, "r") as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            hashes[info.filename] = sha256_bytes(archive.read(info.filename))
    return hashes


def package_feature_codes(names: list[str]) -> list[str]:
    features: set[str] = set()
    for name in names:
        lowered = name.lower()
        if "/embeddings/" in lowered:
            features.add("embeddings")
        if "/charts/" in lowered:
            features.add("charts")
        if "/diagrams/" in lowered:
            features.add("smartart")
        if name == "xl/calcChain.xml":
            features.add("calc_chain")
        if "threadedcomment" in lowered:
            features.add("threaded_comments")
        if "vml" in lowered:
            features.add("vml")
        if "/media/" in lowered:
            features.add("media")
        if name.startswith("word/footnotes") or name.startswith("word/endnotes"):
            features.add("notes")
        if "customxml" in lowered:
            features.add("custom_xml")
    return sorted(features)


def col_letter(index: int) -> str:
    """1-based column index to Excel letters."""

    if index <= 0:
        raise ValueError("column index must be positive")
    letters = []
    while index:
        index, remainder = divmod(index - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))


def col_index(letters: str) -> int:
    value = 0
    for char in letters.upper():
        if not ("A" <= char <= "Z"):
            raise ValueError(f"bad column {letters}")
        value = value * 26 + (ord(char) - 64)
    return value


def split_cell(coordinate: str) -> tuple[int, int]:
    letters = []
    digits = []
    for char in coordinate:
        if char.isalpha():
            letters.append(char)
        elif char.isdigit():
            digits.append(char)
        else:
            raise ValueError(f"bad cell {coordinate}")
    if not letters or not digits:
        raise ValueError(f"bad cell {coordinate}")
    return int("".join(digits)), col_index("".join(letters))
