"""Read a DOCX package into anchored paragraphs, tables, comments and revisions.

The original zip is opened read-only. List numbers are the labels Word would
show, not the raw ``numId``. Accepted text keeps insertions and drops
deletions; original text does the opposite. Both are source observations.
"""

from __future__ import annotations

from lxml import etree

from office_kit.models import (
    Cell,
    Comment,
    Document,
    HeaderFooter,
    OutlineItem,
    Paragraph,
    Revision,
    Section,
    SourceInfo,
    Table,
    TextNode,
    WordBody,
)
from office_kit.numbering import Numbering, paragraph_numpr
from office_kit.ooxml import (
    R,
    Package,
    attr,
    child,
    element_children,
    indexed_children,
    local,
    package_feature_codes,
)
from office_kit.styles import StyleSet, effective_formatting, heading_level, load_theme_fonts, read_rpr

_DOC = "word/document.xml"


def _id(path: str | None) -> str | None:
    if not path or "#" in path:
        return path
    return f"{_DOC}#{path}"


def parse_docx(
    path,
    sha256: str,
    *,
    source_format: str = "docx",
    converter: str | None = None,
    converted_from: str | None = None,
    size: int | None = None,
) -> Document:
    path_str = str(path)
    source = SourceInfo(
        path=path_str,
        filename=path.name,
        format=source_format,
        sha256=sha256,
        size=size if size is not None else path.stat().st_size,
        converter=converter,
        converted_from=converted_from,
    )
    document = Document(source=source, kind="word", status="ok", word=WordBody())
    with Package(path) as package:
        root = package.xml("word/document.xml")
        if root is None:
            document.status = "error"
            document.warnings.append(
                {"code": "missing_document", "message": "包内没有 word/document.xml，无法按 DOCX 解析。"}
            )
            return document
        theme = load_theme_fonts(package.xml("word/theme/theme1.xml"))
        styles = StyleSet.from_xml(package.xml("word/styles.xml"))
        numbering = Numbering.from_xml(package.xml("word/numbering.xml"))
        comments = _load_comments(package.xml("word/comments.xml"))
        ctx = _Ctx(styles=styles, numbering=numbering, theme=theme, comments=comments)
        ctx.paragraphs = document.word.paragraphs
        body = child(root, "body")
        if body is None:
            document.status = "error"
            document.warnings.append({"code": "missing_body", "message": "word/document.xml 没有 w:body。"})
            return document
        _consume_blocks(body, "/document/body[0]", ctx, document.word, in_table=False, table_anchor=None, section=0)
        _attach_section_story(package, ctx, document.word)
        for warning in numbering.warnings:
            document.warnings.append(warning)
        _finish_comments(document.word, comments, ctx.comment_anchors)
        document.word.styles = styles.public_styles()
        document.word.revisions = ctx.revisions
        features = set(package_feature_codes(package.names))
        if document.word.comments:
            features.add("comments")
        if document.word.revisions:
            features.add("revisions")
        if any(p.fields for p in document.word.paragraphs):
            features.add("fields")
        if any(s.headers or s.footers for s in document.word.sections):
            features.add("headers")
        if document.word.tables:
            features.add("tables")
        document.features = sorted(features)
    return document


class _Ctx:
    def __init__(self, styles: StyleSet, numbering: Numbering, theme: dict, comments: dict[str, Comment]):
        self.styles = styles
        self.numbering = numbering
        self.theme = theme
        self.comments = comments
        self.comment_anchors: dict[str, str] = {}
        self.revisions: list[Revision] = []
        self.paragraphs: list[Paragraph] = []
        self.paragraph_index = 0
        self.table_index = 0
        self.heading_stack: list[dict] = []
        self.section_breaks: list[tuple[int, etree._Element, str]] = []


def _consume_blocks(parent, parent_path: str, ctx: _Ctx, word: WordBody, *, in_table: bool, table_anchor: str | None, section: int) -> int:
    for node, path in indexed_children(parent, parent_path):
        name = local(node)
        if name == "p":
            paragraph = _parse_paragraph(
                node, path, ctx, in_table=in_table, table_anchor=table_anchor, section=section
            )
            word.paragraphs.append(paragraph)
            if not in_table:
                word.blocks.append({"type": "paragraph", "anchor": paragraph.anchor, "paragraph_index": paragraph.index})
                if paragraph.heading_level:
                    _push_heading(ctx, paragraph)
                    word.outline.append(
                        OutlineItem(
                            level=paragraph.heading_level,
                            text=paragraph.text_accepted,
                            display=paragraph.display,
                            anchor=paragraph.anchor,
                            number_label=paragraph.number_label,
                            paragraph_index=paragraph.index,
                        )
                    )
            sect = child(child(node, "pPr"), "sectPr")
            if sect is not None and not in_table:
                sect_path = _child_path(child(node, "pPr"), f"{path}/pPr[0]", sect)
                ctx.section_breaks.append((section, sect, sect_path))
                section += 1
        elif name == "tbl":
            table = _parse_table(node, path, ctx, section=section, nested=in_table, parent_anchor=table_anchor)
            if in_table:
                # Nested tables are stored on the parent cell. Reaching here
                # means a caller passed the table's own children; ignore.
                continue
            word.tables.append(table)
            word.blocks.append({"type": "table", "anchor": table.anchor, "table_index": table.index})
        elif name == "sdt":
            content = child(node, "sdtContent")
            if content is not None:
                content_path = _child_path(node, path, content)
                section = _consume_blocks(
                    content, content_path, ctx, word, in_table=in_table, table_anchor=table_anchor, section=section
                )
        elif name == "AlternateContent":
            chosen = child(node, "Choice") or child(node, "Fallback")
            if chosen is not None:
                chosen_path = _child_path(node, path, chosen)
                section = _consume_blocks(
                    chosen, chosen_path, ctx, word, in_table=in_table, table_anchor=table_anchor, section=section
                )
        elif name == "sectPr" and not in_table:
            ctx.section_breaks.append((section, node, path))
    return section


def _child_path(parent, parent_path: str, target) -> str:
    for node, path in indexed_children(parent, parent_path):
        if node is target:
            return path
    return parent_path


def _push_heading(ctx: _Ctx, paragraph: Paragraph) -> None:
    level = paragraph.heading_level or 1
    ctx.heading_stack = [item for item in ctx.heading_stack if item["level"] < level]
    ctx.heading_stack.append({"level": level, "text": paragraph.text_accepted, "anchor": paragraph.anchor})


def _parse_paragraph(p, path: str, ctx: _Ctx, *, in_table: bool, table_anchor: str | None, section: int) -> Paragraph:
    p_pr = child(p, "pPr")
    style_id = attr(child(p_pr, "pStyle"), "val")
    if style_id is None and not in_table:
        style_id = ctx.styles.default_paragraph_id
    chain = ctx.styles.chain(style_id)
    numbering = paragraph_numpr(p, chain)
    label = None
    ilvl = None
    suffix = None
    if numbering is not None:
        num_id, ilvl_text = numbering
        ilvl = int(ilvl_text or "0")
        label = ctx.numbering.next_label(num_id, ilvl)
        suffix = ctx.numbering.suffix(num_id, ilvl)
    level = heading_level(p, chain)
    layers = [ctx.styles.doc_defaults]
    for info in reversed(chain):
        layers.append(info.rpr)
    layers.append(read_rpr(child(p_pr, "rPr")))
    formatting = effective_formatting(layers, ctx.theme)
    accepted: list[str] = []
    original: list[str] = []
    runs: list[TextNode] = []
    fields: list[str] = []
    _walk_paragraph(
        p,
        path,
        revision=None,
        base_layers=layers,
        theme=ctx.theme,
        chain_lookup=ctx.styles,
        accepted=accepted,
        original=original,
        runs=runs,
        fields=fields,
        revisions=ctx.revisions,
        comment_anchors=ctx.comment_anchors,
        paragraph_anchor=_id(path),
    )
    _paragraph_mark_changes(p, path, ctx.revisions)
    paragraph = Paragraph(
        anchor=_id(path),
        index=ctx.paragraph_index,
        text_accepted="".join(accepted),
        text_original="".join(original),
        number_label=label,
        number_ilvl=ilvl,
        number_suffix=suffix,
        style_id=style_id,
        style_name=chain[0].name if chain else None,
        heading_level=level,
        heading_path=list(ctx.heading_stack),
        section_index=section,
        in_table=in_table,
        table_anchor=table_anchor,
        formatting=formatting,
        runs=runs,
        fields=fields,
    )
    ctx.paragraph_index += 1
    return paragraph


def _paragraph_mark_changes(p, path: str, revisions: list[Revision]) -> None:
    p_pr = child(p, "pPr")
    change = child(p_pr, "pPrChange")
    if change is None:
        return
    previous = child(change, "pPr")
    revisions.append(
        Revision(
            kind="pPrChange",
            author=attr(change, "author") or "",
            date=attr(change, "date"),
            rev_id=attr(change, "id"),
            text="",
            anchor=_id(path),
            previous={"jc": attr(child(previous, "jc"), "val")} if previous is not None else {},
        )
    )


def _walk_paragraph(
    node,
    path: str,
    *,
    revision: str | None,
    base_layers: list,
    theme: dict,
    chain_lookup: StyleSet,
    accepted: list[str],
    original: list[str],
    runs: list[TextNode],
    fields: list[str],
    revisions: list[Revision],
    comment_anchors: dict[str, str],
    paragraph_anchor: str,
) -> None:
    for child_node, child_path in indexed_children(node, path):
        name = local(child_node)
        next_revision = revision
        run_layers = base_layers
        if name in {"ins", "del", "moveFrom", "moveTo"}:
            next_revision = name
            revisions.append(
                Revision(
                    kind=name,
                    author=attr(child_node, "author") or "",
                    date=attr(child_node, "date"),
                    rev_id=attr(child_node, "id"),
                    text=_revision_text(child_node),
                    anchor=_id(child_path),
                )
            )
        elif name == "r":
            r_pr = child(child_node, "rPr")
            change = child(r_pr, "rPrChange")
            if change is not None:
                revisions.append(
                    Revision(
                        kind="rPrChange",
                        author=attr(change, "author") or "",
                        date=attr(change, "date"),
                        rev_id=attr(change, "id"),
                        text=_direct_run_text(child_node),
                        anchor=_id(child_path),
                        previous=effective_formatting(base_layers + [read_rpr(child(change, "rPr"))], theme),
                    )
                )
            style_id = attr(child(r_pr, "rStyle"), "val")
            char_layers = []
            if style_id:
                for info in reversed(chain_lookup.chain(style_id)):
                    char_layers.append(info.rpr)
            run_layers = base_layers + char_layers + [read_rpr(r_pr)]
        elif name == "commentRangeStart":
            comment_id = attr(child_node, "id")
            if comment_id:
                comment_anchors.setdefault(comment_id, paragraph_anchor)
        elif name == "instrText":
            text = (child_node.text or "").strip()
            if text:
                fields.append(text)
        if name in {"t", "delText", "tab", "br", "cr"}:
            if name == "tab":
                text = "\t"
                kind = "tab"
            elif name in {"br", "cr"}:
                text = "\n"
                kind = name
            else:
                text = child_node.text or ""
                kind = name
            deleted = next_revision in {"del", "moveFrom"} or name == "delText"
            inserted = next_revision in {"ins", "moveTo"}
            if not deleted:
                accepted.append(text)
            if not inserted:
                original.append(text)
            if name in {"t", "delText"}:
                runs.append(
                    TextNode(
                        anchor=_id(child_path),
                        text=text,
                        kind=name,
                        revision=next_revision or ("del" if name == "delText" else None),
                        formatting=effective_formatting(run_layers, theme),
                    )
                )
            continue
        _walk_paragraph(
            child_node,
            child_path,
            revision=next_revision,
            base_layers=run_layers,
            theme=theme,
            chain_lookup=chain_lookup,
            accepted=accepted,
            original=original,
            runs=runs,
            fields=fields,
            revisions=revisions,
            comment_anchors=comment_anchors,
            paragraph_anchor=paragraph_anchor,
        )


def _revision_text(node) -> str:
    parts: list[str] = []
    for item in node.iter():
        if not isinstance(item.tag, str):
            continue
        if local(item) in {"t", "delText"} and item.text:
            parts.append(item.text)
    return "".join(parts)


def _direct_run_text(run) -> str:
    parts: list[str] = []
    for item in element_children(run):
        if local(item) in {"t", "delText"} and item.text:
            parts.append(item.text)
    return "".join(parts)


def _parse_table(tbl, path: str, ctx: _Ctx, *, section: int, nested: bool, parent_anchor: str | None) -> Table:
    index = None if nested else ctx.table_index
    if not nested:
        ctx.table_index += 1
    rows: list[list[Cell]] = []
    for tr, tr_path in indexed_children(tbl, path):
        if local(tr) != "tr":
            continue
        cells: list[Cell] = []
        for tc, tc_path in indexed_children(tr, tr_path):
            if local(tc) != "tc":
                continue
            tc_pr = child(tc, "tcPr")
            span_text = attr(child(tc_pr, "gridSpan"), "val")
            grid_span = int(span_text or "1")
            merge_el = child(tc_pr, "vMerge")
            v_merge = None
            if merge_el is not None:
                v_merge = attr(merge_el, "val") or "continue"
            paragraphs: list[Paragraph] = []
            nested_tables: list[Table] = []
            saved_stack = list(ctx.heading_stack)
            for node, node_path in indexed_children(tc, tc_path):
                name = local(node)
                if name == "p":
                    paragraph = _parse_paragraph(
                        node, node_path, ctx, in_table=True, table_anchor=_id(path), section=section
                    )
                    paragraphs.append(paragraph)
                    ctx.paragraphs.append(paragraph)
                elif name == "tbl":
                    nested_tables.append(
                        _parse_table(
                            node, node_path, ctx, section=section, nested=True, parent_anchor=_id(tc_path)
                        )
                    )
            ctx.heading_stack = saved_stack
            text = "\n".join(item.text_accepted for item in paragraphs if item.text_accepted)
            cells.append(
                Cell(
                    anchor=_id(tc_path),
                    text=text,
                    grid_span=max(grid_span, 1),
                    v_merge=v_merge,
                    paragraphs=paragraphs,
                    nested_tables=nested_tables,
                )
            )
        rows.append(cells)
    table = Table(
        anchor=_id(path),
        index=index,
        section_index=section,
        rows=rows,
        nested=nested,
        parent_anchor=parent_anchor,
    )
    table.coverage = _coverage(table)
    # Paragraphs inside the table must remain searchable on the document.
    return table


def _coverage(table: Table) -> list[list[dict]]:
    occupied: dict[tuple[int, int], tuple[Cell, int, int]] = {}
    issues = table.issues
    for row_index, row in enumerate(table.rows):
        column = 0
        for cell in row:
            while (row_index, column) in occupied:
                column += 1
            origin_cell = cell
            origin_pos = (row_index, column)
            if cell.v_merge == "continue":
                above = occupied.get((row_index - 1, column))
                if above is None:
                    issues.append(f"第{row_index + 1}行的纵向合并没有找到上方起点")
                else:
                    origin_cell, origin_pos = above[0], (above[1], above[2])
                    cell.cover_origin = origin_cell.anchor
            for offset in range(cell.grid_span):
                occupied[(row_index, column + offset)] = (origin_cell, origin_pos[0], origin_pos[1])
            column += cell.grid_span
    if not occupied:
        return []
    width = max(column for _, column in occupied) + 1
    height = max(row for row, _ in occupied) + 1
    matrix = []
    for row_index in range(height):
        slots = []
        for column in range(width):
            found = occupied.get((row_index, column))
            if found is None:
                slots.append({"origin_anchor": None, "is_origin": False, "text": ""})
                continue
            cell, origin_row, origin_column = found
            slots.append(
                {
                    "origin_anchor": cell.anchor,
                    "is_origin": (row_index, column) == (origin_row, origin_column),
                    "text": cell.text,
                }
            )
        matrix.append(slots)
    return matrix


def _load_comments(root) -> dict[str, Comment]:
    found: dict[str, Comment] = {}
    if root is None:
        return found
    for index, node in enumerate(children_comment(root)):
        comment_id = attr(node, "id") or str(index)
        parts = []
        for item in node.iter():
            if isinstance(item.tag, str) and local(item) == "t" and item.text:
                parts.append(item.text)
        found[comment_id] = Comment(
            comment_id=comment_id,
            author=attr(node, "author") or "",
            date=attr(node, "date"),
            text="".join(parts),
            anchor=f"word/comments.xml#/comments/comment[{index}]",
        )
    return found


def children_comment(root):
    return [node for node in element_children(root) if local(node) == "comment"]


def _finish_comments(word: WordBody, comments: dict[str, Comment], anchors: dict[str, str]) -> None:
    for comment in comments.values():
        comment.range_anchor = anchors.get(comment.comment_id)
        word.comments.append(comment)


def _attach_section_story(package: Package, ctx: _Ctx, word: WordBody) -> None:
    rels = package.rels("word/document.xml")
    if not ctx.section_breaks:
        word.sections.append(Section(index=0, anchor="word/document.xml#/document/body[0]"))
        return
    for section_index, sect, sect_path in ctx.section_breaks:
        section = Section(index=section_index, anchor=f"word/document.xml#{sect_path}")
        page = child(sect, "pgSz")
        if page is not None:
            section.page = {
                "width_twip": _int_attr(page, "w"),
                "height_twip": _int_attr(page, "h"),
                "orient": attr(page, "orient"),
            }
        margins = child(sect, "pgMar")
        if margins is not None:
            section.margins = {
                name: _int_attr(margins, name)
                for name in ("top", "bottom", "left", "right", "header", "footer")
            }
        for ref in element_children(sect):
            name = local(ref)
            if name not in {"headerReference", "footerReference"}:
                continue
            rel_id = attr(ref, "id", R)
            target = rels.get(rel_id or "")
            kind = "header" if name == "headerReference" else "footer"
            hf_type = attr(ref, "type") or "default"
            text, paragraphs = _story_text(package, target)
            item = HeaderFooter(kind=kind, type=hf_type, part=target or "", text=text, paragraphs=paragraphs)
            if kind == "header":
                section.headers.append(item)
            else:
                section.footers.append(item)
        word.sections.append(section)


def _story_text(package: Package, part: str | None) -> tuple[str, list[dict]]:
    if not part:
        return "", []
    root = package.xml(part)
    if root is None:
        return "", []
    paragraphs = []
    texts = []
    for node, path in _flat_paragraphs(root, "/" + local(root)):
        text = _plain_text(node)
        paragraphs.append({"anchor": f"{part}#{path}", "text": text})
        if text:
            texts.append(text)
    return "\n".join(texts), paragraphs


def _flat_paragraphs(parent, parent_path: str):
    for node, path in indexed_children(parent, parent_path):
        name = local(node)
        if name == "p":
            yield node, path
        elif name in {"tbl", "sdt", "sdtContent", "hdr", "ftr"}:
            yield from _flat_paragraphs(node, path)


def _plain_text(p) -> str:
    parts = []
    for item in p.iter():
        if not isinstance(item.tag, str):
            continue
        if local(item) == "t" and item.text:
            parts.append(item.text)
    return "".join(parts)


def _int_attr(node, name: str) -> int | None:
    value = attr(node, name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def iter_tables(tables: list[Table]):
    for table in tables:
        yield table
        for row in table.rows:
            for cell in row:
                yield from iter_tables(cell.nested_tables)

