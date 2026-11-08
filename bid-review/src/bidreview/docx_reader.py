"""Read-only OOXML reader.

The file is opened with ZipFile mode ``r`` only. Formatting, numbering,
sections, comments and revisions are taken from the package XML so the
checker does not depend on Word and does not rewrite the document.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from lxml import etree

from bidreview.models import (
    CommentNote,
    Document,
    EffectiveFormat,
    Location,
    Paragraph,
    RevisionNote,
    RunFormat,
    SectionInfo,
    StyleInfo,
    Table,
)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XML_NS = "http://www.w3.org/XML/1998/namespace"
W = "{%s}" % W_NS
_CHAPTER = re.compile(r"^第[一二三四五六七八九十百零〇0-9]+[章节篇]")


def w(tag: str) -> str:
    return f"{W}{tag}"


def aval(el: etree._Element | None, name: str) -> str | None:
    if el is None:
        return None
    value = el.get(w(name))
    if value is None:
        value = el.get(name)
    return value


def _local(el: etree._Element) -> str:
    return etree.QName(el).localname


class _Pkg:
    def __init__(self, path: Path):
        self.path = path
        self.zip = zipfile.ZipFile(path, "r")
        self.rels = self._rels("word/_rels/document.xml.rels")

    def close(self) -> None:
        self.zip.close()

    def read(self, name: str) -> bytes | None:
        try:
            return self.zip.read(name)
        except KeyError:
            return None

    def xml(self, name: str) -> etree._Element | None:
        raw = self.read(name)
        if raw is None:
            return None
        return etree.fromstring(raw)

    def _rels(self, name: str) -> dict[str, str]:
        root = self.xml(name)
        found: dict[str, str] = {}
        if root is None:
            return found
        for rel in root:
            rid = rel.get("Id")
            target = rel.get("Target")
            if not rid or not target:
                continue
            if target.startswith("/"):
                found[rid] = target.lstrip("/")
            elif target.startswith("../"):
                found[rid] = target[3:]
            else:
                found[rid] = "word/" + target
        return found


def _text_of(el: etree._Element, *, include_deleted: bool = False) -> tuple[str, str, str, bool, bool]:
    """Return accepted text, inserted text, deleted text, has_ins, has_del.

    Accepted text is what remains if tracked insertions are not treated as
    effective and tracked deletions are not treated as effective. Callers that
    pass ``include_deleted`` are tests; the reader keeps the two streams apart.
    """
    del include_deleted
    accepted: list[str] = []
    inserted: list[str] = []
    deleted: list[str] = []

    def walk(node: etree._Element, in_ins: bool, in_del: bool) -> None:
        for child in node:
            name = _local(child)
            if name == "ins":
                walk(child, True, in_del)
                continue
            if name == "del":
                walk(child, in_ins, True)
                continue
            if name == "t":
                chunk = child.text or ""
                if in_del:
                    deleted.append(chunk)
                elif in_ins:
                    inserted.append(chunk)
                else:
                    accepted.append(chunk)
            elif name == "delText":
                deleted.append(child.text or "")
            elif name == "tab" and not in_del and not in_ins:
                accepted.append("\t")
            elif name == "br" and not in_del and not in_ins:
                accepted.append("\n")
            else:
                walk(child, in_ins, in_del)

    walk(el, False, False)
    ins = "".join(inserted)
    dele = "".join(deleted)
    return "".join(accepted), ins, dele, bool(ins), bool(dele)


def _rfonts(rPr: etree._Element | None) -> tuple[str | None, str | None]:
    if rPr is None:
        return None, None
    fonts = rPr.find(w("rFonts"))
    if fonts is None:
        return None, None
    east = aval(fonts, "eastAsia")
    ascii_font = aval(fonts, "ascii") or aval(fonts, "hAnsi")
    return east, ascii_font


def _sz(rPr: etree._Element | None) -> int | None:
    if rPr is None:
        return None
    sz = rPr.find(w("sz"))
    raw = aval(sz, "val")
    if raw and raw.isdigit():
        return int(raw)
    return None


def _bold(rPr: etree._Element | None) -> bool | None:
    if rPr is None:
        return None
    b = rPr.find(w("b"))
    if b is None:
        return None
    val = aval(b, "val")
    if val is None:
        return True
    return val not in {"0", "false", "off"}


def _spacing(pPr: etree._Element | None) -> tuple[int | None, str | None, str | None]:
    if pPr is None:
        return None, None, None
    spacing = pPr.find(w("spacing"))
    line = aval(spacing, "line")
    rule = aval(spacing, "lineRule")
    jc = pPr.find(w("jc"))
    align = aval(jc, "val")
    line_i = int(line) if line and line.lstrip("-").isdigit() else None
    return line_i, rule, align


def _numpr(pPr: etree._Element | None) -> tuple[str | None, str | None]:
    if pPr is None:
        return None, None
    num = pPr.find(w("numPr"))
    if num is None:
        return None, None
    ilvl = aval(num.find(w("ilvl")), "val")
    num_id = aval(num.find(w("numId")), "val")
    return num_id, ilvl


def _runs(p: etree._Element) -> list[RunFormat]:
    found: list[RunFormat] = []

    def walk(node: etree._Element, in_del: bool) -> None:
        for child in node:
            name = _local(child)
            if name == "del":
                walk(child, True)
                continue
            if name == "r" and not in_del:
                rPr = child.find(w("rPr"))
                east, _ascii = _rfonts(rPr)
                texts: list[str] = []
                for t in child.iter(w("t")):
                    # skip text that is inside a nested del; iter is flat
                    texts.append(t.text or "")
                text = "".join(texts)
                if text.strip():
                    found.append(RunFormat(text=text, east_asia=east, size_half=_sz(rPr), bold=_bold(rPr)))
            elif name != "r":
                walk(child, in_del)

    walk(p, False)
    return found


def _part_text(root: etree._Element | None) -> tuple[str, bool]:
    if root is None:
        return "", False
    chunks: list[str] = []
    has_page = False
    for instr in root.iter(w("instrText")):
        if instr.text and "PAGE" in instr.text.upper():
            has_page = True
    for p in root.iter(w("p")):
        accepted, _ins, _dele, _hi, _hd = _text_of(p)
        if accepted.strip():
            chunks.append(accepted.strip())
    return "\n".join(chunks), has_page


def _load_numbering(pkg: _Pkg) -> dict[str, dict[str, tuple[str | None, str | None]]]:
    """numId -> ilvl -> (numFmt, lvlText)."""
    root = pkg.xml("word/numbering.xml")
    if root is None:
        return {}
    abstracts: dict[str, dict[str, tuple[str | None, str | None]]] = {}
    for abs_el in root.findall(w("abstractNum")):
        aid = aval(abs_el, "abstractNumId")
        if aid is None:
            continue
        levels: dict[str, tuple[str | None, str | None]] = {}
        for lvl in abs_el.findall(w("lvl")):
            ilvl = aval(lvl, "ilvl") or "0"
            fmt = aval(lvl.find(w("numFmt")), "val")
            text = aval(lvl.find(w("lvlText")), "val")
            levels[ilvl] = (fmt, text)
        abstracts[aid] = levels
    nums: dict[str, dict[str, tuple[str | None, str | None]]] = {}
    for num in root.findall(w("num")):
        nid = aval(num, "numId")
        aid = aval(num.find(w("abstractNumId")), "val")
        if nid and aid and aid in abstracts:
            nums[nid] = abstracts[aid]
    return nums


def _explicit_style(el: etree._Element) -> dict:
    pPr = el.find(w("pPr"))
    rPr = el.find(w("rPr"))
    line, rule, align = _spacing(pPr)
    east, _ascii = _rfonts(rPr)
    num_id, ilvl = _numpr(pPr)
    outline = pPr.find(w("outlineLvl")) if pPr is not None else None
    outline_raw = aval(outline, "val")
    return {
        "east_asia": east,
        "size_half": _sz(rPr),
        "line": line,
        "line_rule": rule,
        "align": align,
        "num_id": num_id,
        "ilvl": ilvl,
        "outline_lvl": int(outline_raw) if outline_raw and outline_raw.isdigit() else None,
    }


def _load_styles(pkg: _Pkg, numbering: dict) -> dict[str, StyleInfo]:
    root = pkg.xml("word/styles.xml")
    styles: dict[str, StyleInfo] = {}
    if root is None:
        return styles
    defaults = root.find(w("docDefaults"))
    default_explicit = _explicit_style(defaults) if defaults is not None else {}
    raw: dict[str, tuple[str, str | None, dict]] = {}
    for st in root.findall(w("style")):
        if aval(st, "type") not in (None, "paragraph"):
            continue
        sid = aval(st, "styleId")
        if not sid:
            continue
        name = aval(st.find(w("name")), "val") or sid
        based = aval(st.find(w("basedOn")), "val")
        raw[sid] = (name, based, _explicit_style(st))

    def resolve(sid: str, seen: set[str]) -> dict:
        if sid in seen or sid not in raw:
            return dict(default_explicit)
        seen.add(sid)
        _name, based, explicit = raw[sid]
        base = resolve(based, seen) if based else dict(default_explicit)
        for key, value in explicit.items():
            if value is not None:
                base[key] = value
        return base

    for sid, (name, based, _explicit) in raw.items():
        props = resolve(sid, set())
        num_id = props.get("num_id")
        ilvl = props.get("ilvl") or "0"
        fmt = None
        lvl_text = None
        has_num = bool(num_id) and num_id != "0"
        if has_num and num_id in numbering:
            fmt, lvl_text = numbering[num_id].get(str(ilvl), (None, None))
        styles[sid] = StyleInfo(
            style_id=sid,
            name=name,
            based_on=based,
            outline_lvl=props.get("outline_lvl"),
            east_asia=props.get("east_asia"),
            size_half=props.get("size_half"),
            line=props.get("line"),
            line_rule=props.get("line_rule"),
            align=props.get("align"),
            has_numbering=has_num,
            num_id=num_id if has_num else None,
            ilvl=str(ilvl) if has_num else None,
            num_fmt=fmt,
            lvl_text=lvl_text,
        )
    return styles


def _heading_level(style_id: str | None, styles: dict[str, StyleInfo]) -> int | None:
    seen: set[str] = set()
    sid = style_id
    while sid and sid not in seen:
        seen.add(sid)
        style = styles.get(sid)
        if style is None:
            break
        if style.outline_lvl is not None:
            return style.outline_lvl + 1
        match = re.search(r"(?:heading|标题)\s*(\d+)", f"{style.name} {sid}", re.I)
        if match:
            return int(match.group(1))
        sid = style.based_on
    return None


def _style_effective(style: StyleInfo | None) -> EffectiveFormat:
    if style is None:
        return EffectiveFormat()
    return EffectiveFormat(
        east_asia=style.east_asia,
        size_half=style.size_half,
        line=style.line,
        line_rule=style.line_rule or ("auto" if style.line else None),
        align=style.align,
    )


def _paragraph_effective(p: etree._Element, style: StyleInfo | None, runs: list[RunFormat]) -> EffectiveFormat:
    base = _style_effective(style)
    pPr = p.find(w("pPr"))
    line, rule, align = _spacing(pPr)
    if line is not None:
        base.line = line
        base.line_rule = rule or "auto"
    if align:
        base.align = align
    for run in runs:
        if run.east_asia:
            base.east_asia = run.east_asia
        if run.size_half is not None:
            base.size_half = run.size_half
        break
    return base


def _twip(sect: etree._Element, name: str) -> int | None:
    mar = sect.find(w("pgMar"))
    raw = aval(mar, name)
    if raw and raw.lstrip("-").isdigit():
        return int(raw)
    return None


def _header_footer(pkg: _Pkg, sect: etree._Element, kind: str) -> tuple[str, bool]:
    tag = "headerReference" if kind == "header" else "footerReference"
    chosen = None
    for ref in sect.findall(w(tag)):
        if aval(ref, "type") in (None, "default"):
            chosen = ref
            break
    if chosen is None:
        refs = sect.findall(w(tag))
        chosen = refs[0] if refs else None
    if chosen is None:
        return "", False
    rid = chosen.get(f"{{{R_NS}}}id")
    target = pkg.rels.get(rid or "")
    if not target:
        return "", False
    root = pkg.xml(target)
    return _part_text(root)


def _comments(pkg: _Pkg) -> dict[str, tuple[str, str]]:
    root = pkg.xml("word/comments.xml")
    found: dict[str, tuple[str, str]] = {}
    if root is None:
        return found
    for comment in root.findall(w("comment")):
        cid = aval(comment, "id")
        if cid is None:
            continue
        author = aval(comment, "author") or ""
        texts: list[str] = []
        for t in comment.iter(w("t")):
            texts.append(t.text or "")
        found[cid] = (author, "".join(texts))
    return found


def _revisions_in(p: etree._Element) -> list[tuple[str, str, str]]:
    notes: list[tuple[str, str, str]] = []

    def walk(node: etree._Element) -> None:
        for child in node:
            name = _local(child)
            if name in {"ins", "del"}:
                author = aval(child, "author") or ""
                chunks: list[str] = []
                tag = w("t") if name == "ins" else w("delText")
                # Insertions use w:t; some producers use w:t inside w:ins.
                if name == "ins":
                    for t in child.iter(w("t")):
                        chunks.append(t.text or "")
                else:
                    for t in child.iter(w("delText")):
                        chunks.append(t.text or "")
                    if not chunks:
                        for t in child.iter(w("t")):
                            chunks.append(t.text or "")
                notes.append((name, "".join(chunks), author))
            else:
                walk(child)

    walk(p)
    return notes


def _cell_text(tc: etree._Element) -> str:
    parts: list[str] = []
    for p in tc.findall(w("p")):
        accepted, _i, _d, _hi, _hd = _text_of(p)
        parts.append(accepted)
    return "\n".join(parts).strip()


def _make_location(doc_path: Path, file_name: str, sha: str, **kwargs) -> Location:
    return Location(
        file_name=file_name,
        file_path=str(doc_path),
        sha256=sha,
        kind="docx",
        **kwargs,
    )


def read_docx(path: Path, *, role: str, title: str, sha256: str) -> Document:
    file_name = path.name
    doc = Document(
        path=str(path),
        file_name=file_name,
        role=role,
        title=title or path.stem,
        sha256=sha256,
        kind="docx",
    )
    pkg = _Pkg(path)
    try:
        root = pkg.xml("word/document.xml")
        if root is None:
            doc.unreadable = "DOCX 中没有 word/document.xml"
            return doc
        numbering = _load_numbering(pkg)
        styles = _load_styles(pkg, numbering)
        doc.styles = styles
        comment_map = _comments(pkg)
        body = root.find(w("body"))
        if body is None:
            doc.unreadable = "DOCX 正文为空"
            return doc

        section_idx = 0
        current_title = "（文首）"
        last_heading = ""
        p_index = 0
        t_index = 0
        seen_comment_paras: dict[str, Location] = {}
        sect_elements: list[tuple[int, etree._Element]] = []

        def handle_paragraph(p: etree._Element, *, in_table: bool, table_index: int | None, row: int | None, col: int | None, xml_path: str) -> None:
            nonlocal current_title, last_heading
            accepted, inserted, deleted, has_ins, has_del = _text_of(p)
            pPr = p.find(w("pPr"))
            style_id = aval(pPr.find(w("pStyle")) if pPr is not None else None, "val")
            style = styles.get(style_id) if style_id else styles.get("Normal")
            runs = _runs(p)
            level = _heading_level(style_id, styles)
            if level is None and _CHAPTER.match(accepted.strip()):
                level = 1
            loc = _make_location(
                path,
                file_name,
                sha256,
                part="word/document.xml",
                xml_path=xml_path,
                section_title=current_title,
                section_index=section_idx,
                paragraph_index=p_index,
                table_index=table_index,
                row=row,
                col=col,
            )
            if level == 1 and accepted.strip() and not in_table:
                current_title = accepted.strip()
                last_heading = current_title
            loc.section_title = current_title
            paragraph = Paragraph(
                text=accepted,
                accepted_text=accepted,
                location=loc,
                style_id=style_id or ("Normal" if "Normal" in styles else None),
                style_name=style.name if style else None,
                heading_level=level,
                in_table=in_table,
                has_insert=has_ins,
                has_delete=has_del,
                inserted_text=inserted,
                deleted_text=deleted,
                section_index=section_idx,
                section_title=current_title,
                effective=_paragraph_effective(p, style, runs),
                runs=runs,
            )
            if accepted.strip() or inserted.strip() or deleted.strip():
                doc.paragraphs.append(paragraph)
            if level and accepted.strip() and not in_table:
                doc.headings.append((level, accepted.strip(), loc))
            for kind, text, author in _revisions_in(p):
                if text.strip():
                    doc.revisions.append(RevisionNote(kind=kind, text=text.strip(), author=author, location=loc))
            for marker in p.iter(w("commentRangeStart")):
                cid = aval(marker, "id")
                if cid:
                    seen_comment_paras[cid] = loc

        for child in list(body):
            name = _local(child)
            if name == "p":
                handle_paragraph(child, in_table=False, table_index=None, row=None, col=None, xml_path=f"body/p[{p_index}]")
                p_index += 1
                sect = child.find(f"{w('pPr')}/{w('sectPr')}")
                if sect is not None:
                    sect_elements.append((section_idx, sect))
                    section_idx += 1
            elif name == "tbl":
                rows: list[list[str]] = []
                for r_i, tr in enumerate(child.findall(w("tr")), start=1):
                    cells: list[str] = []
                    for c_i, tc in enumerate(tr.findall(w("tc")), start=1):
                        cells.append(_cell_text(tc))
                        for p_i, p in enumerate(tc.findall(w("p"))):
                            handle_paragraph(
                                p,
                                in_table=True,
                                table_index=t_index,
                                row=r_i,
                                col=c_i,
                                xml_path=f"body/tbl[{t_index}]/tr[{r_i}]/tc[{c_i}]/p[{p_i}]",
                            )
                    rows.append(cells)
                header = [c.strip() for c in rows[0]] if rows else []
                loc = _make_location(
                    path,
                    file_name,
                    sha256,
                    part="word/document.xml",
                    xml_path=f"body/tbl[{t_index}]",
                    section_title=current_title,
                    section_index=section_idx,
                    table_index=t_index,
                )
                doc.tables.append(
                    Table(
                        location=loc,
                        rows=rows,
                        header=header,
                        preceding_heading=last_heading,
                        section_title=current_title,
                        section_index=section_idx,
                    )
                )
                t_index += 1
            elif name == "sectPr":
                sect_elements.append((section_idx, child))
            elif name == "sdt":
                content = child.find(w("sdtContent"))
                if content is not None:
                    for inner in list(content):
                        if _local(inner) == "p":
                            handle_paragraph(
                                inner,
                                in_table=False,
                                table_index=None,
                                row=None,
                                col=None,
                                xml_path=f"body/sdt/p[{p_index}]",
                            )
                            p_index += 1

        for index, sect in sect_elements:
            header_text, _hp = _header_footer(pkg, sect, "header")
            footer_text, has_page = _header_footer(pkg, sect, "footer")
            doc.sections.append(
                SectionInfo(
                    index=index,
                    top=_twip(sect, "top"),
                    bottom=_twip(sect, "bottom"),
                    left=_twip(sect, "left"),
                    right=_twip(sect, "right"),
                    header=_twip(sect, "header"),
                    footer=_twip(sect, "footer"),
                    header_text=header_text,
                    footer_text=footer_text,
                    footer_has_page_field=has_page,
                )
            )
        for cid, (author, text) in comment_map.items():
            loc = seen_comment_paras.get(cid)
            if loc is None:
                loc = _make_location(
                    path,
                    file_name,
                    sha256,
                    part="word/comments.xml",
                    xml_path=f"comment[{cid}]",
                    section_title="批注",
                )
            doc.comments.append(CommentNote(comment_id=cid, author=author, text=text, location=loc))
        return doc
    finally:
        pkg.close()
