from lxml import etree

from office_kit.numbers import chinese_int, parse_chinese_money, parse_chinese_number
from office_kit.numbering import Numbering
from office_kit.styles import effective_formatting

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def test_chinese_counting_and_money():
    assert chinese_int(1) == "一"
    assert chinese_int(10) == "十"
    assert chinese_int(11) == "十一"
    assert chinese_int(20) == "二十"
    assert chinese_int(21) == "二十一"
    assert chinese_int(101) == "一百零一"
    assert chinese_int(110) == "一百一十"
    assert chinese_int(1001) == "一千零一"
    assert chinese_int(1010) == "一千零一十"
    assert chinese_int(10000) == "一万"
    assert chinese_int(10001) == "一万零一"
    assert chinese_int(100000) == "十万"
    assert chinese_int(200010) == "二十万零一十"
    assert chinese_int(1250000, legal=True) == "壹佰贰拾伍万"
    assert parse_chinese_number("壹佰贰拾伍万") == 1_250_000
    assert parse_chinese_money("壹佰贰拾伍万元整") == 1_250_000
    assert parse_chinese_money("贰佰元整") == 200
    assert parse_chinese_money("贰佰元伍角") == 200.5


def test_numbering_labels_restart_and_legal_decimal():
    root = etree.fromstring(
        f"""<w:numbering xmlns:w="{W}">
          <w:abstractNum w:abstractNumId="0">
            <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="chineseCounting"/><w:lvlText w:val="第%1章"/></w:lvl>
            <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:isLgl/><w:lvlText w:val="%1.%2"/></w:lvl>
            <w:lvl w:ilvl="2"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="（%3）"/></w:lvl>
          </w:abstractNum>
          <w:abstractNum w:abstractNumId="1">
            <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="chineseCounting"/><w:lvlText w:val="第%1章"/></w:lvl>
            <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2"/></w:lvl>
          </w:abstractNum>
          <w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
          <w:num w:numId="2"><w:abstractNumId w:val="0"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="3"/></w:lvlOverride></w:num>
          <w:num w:numId="3"><w:abstractNumId w:val="1"/></w:num>
        </w:numbering>"""
    )
    engine = Numbering.from_xml(root)
    assert [engine.next_label("1", level) for level in (0, 1, 2, 2, 1, 0, 1, 2)] == [
        "第一章",
        "1.1",
        "（1）",
        "（2）",
        "1.2",
        "第二章",
        "2.1",
        "（1）",
    ]
    assert engine.next_label("2", 0) == "第三章"
    assert engine.next_label("3", 0) == "第一章"
    assert engine.next_label("3", 1) == "一.1"


def test_font_cascade_explicit_beats_theme():
    theme = {"major": {}, "minor": {"latin": "Calibri", "ea": "等线"}}
    base = {"fonts": {"eastAsiaTheme": "minorEastAsia", "asciiTheme": "minorHAnsi"}, "size_pt": 12}
    explicit = {"fonts": {"eastAsia": "黑体"}, "bold": True}
    formatted = effective_formatting([base, explicit], theme)
    assert formatted["resolved_east_asia"] == "黑体"
    assert formatted["resolved_ascii"] == "Calibri"
    assert formatted["bold"] is True
    assert formatted["size_pt"] == 12
    inherited = effective_formatting([base, {"italic": False}], theme)
    assert inherited["resolved_east_asia"] == "等线"
    assert inherited["bold"] is False
