from office_kit.ooxml import sha256_file
from office_kit.parse import parse_path

from tests.factory import complex_docx


def test_word_numbering_tables_revisions_and_fonts(tmp_path):
    path = complex_docx(tmp_path / "complex.docx")
    before = sha256_file(path)
    document = parse_path(path)
    assert sha256_file(path) == before
    assert document.status == "ok"
    assert document.source.sha256 == before
    labels = [item.number_label for item in document.word.paragraphs if item.number_label]
    assert labels == ["第一章", "1.1", "（1）", "（2）", "1.2", "第二章", "2.1", "（1）"]
    suppressed = next(item for item in document.word.paragraphs if item.text_accepted == "无编号标题")
    assert suppressed.number_label is None
    assert suppressed.heading_level == 1
    cover = document.word.paragraphs[0]
    assert cover.text_accepted == "封面标题"
    assert cover.runs[0].anchor == "word/document.xml#/document/body[0]/p[0]/r[0]/t[0]"
    chapter = next(item for item in document.word.paragraphs if item.text_accepted == "投标人须知")
    assert chapter.display == "第一章 投标人须知"
    assert chapter.formatting["bold"] is True
    assert chapter.formatting["size_pt"] == 16
    assert chapter.formatting["resolved_east_asia"] == "等线"
    fonts = next(item for item in document.word.paragraphs if "默认字体" in item.text_accepted)
    assert fonts.runs[0].formatting["resolved_east_asia"] == "等线"
    assert fonts.runs[1].formatting["resolved_east_asia"] == "黑体"
    emph = next(item for item in document.word.paragraphs if item.text_accepted == "仿宋强调")
    assert emph.runs[0].formatting["resolved_east_asia"] == "仿宋"
    kai = next(item for item in document.word.paragraphs if item.text_accepted == "楷体段")
    assert kai.formatting["resolved_east_asia"] == "楷体"
    comment = document.word.comments[0]
    assert comment.author == "李四"
    assert comment.text == "请确认参数"
    assert comment.range_anchor
    revised = next(item for item in document.word.paragraphs if "格式变更" in item.text_accepted)
    assert revised.text_accepted == "保留新增文字移入格式变更"
    assert revised.text_original == "保留删除文字移出格式变更"
    kinds = {item.kind for item in document.word.revisions}
    assert {"ins", "del", "moveFrom", "moveTo", "rPrChange", "pPrChange"} <= kinds
    assert any("PAGE" in item for item in next(p.fields for p in document.word.paragraphs if p.fields))
    table = document.word.tables[0]
    assert table.rows[0][0].grid_span == 2
    assert table.rows[0][0].v_merge == "restart"
    assert table.rows[1][0].v_merge == "continue"
    assert table.rows[1][0].cover_origin == table.rows[0][0].anchor
    assert table.coverage[0][0]["is_origin"] is True
    assert table.coverage[0][1]["origin_anchor"] == table.rows[0][0].anchor
    assert table.coverage[0][1]["is_origin"] is False
    assert table.coverage[1][2]["text"] == "右下"
    nested = table.rows[2][0].nested_tables[0]
    assert nested.rows[0][0].text == "内嵌单元格"
    assert any(item.text_accepted == "内嵌单元格" and item.in_table for item in document.word.paragraphs)
    assert document.word.sections[0].headers[0].text == "页眉甲"
    assert document.word.sections[0].footers[0].text == "页脚甲"
    assert document.word.sections[1].headers[0].text == "页眉乙"
    assert document.word.sections[0].margins["left"] == 1800
    second = next(item for item in document.word.paragraphs if item.text_accepted == "第二节正文")
    assert second.section_index == 1
    assert "revisions" in document.features
    assert "comments" in document.features
    assert "fields" in document.features
