from pathlib import Path

from bidreview.engine import review
from bidreview.numbers import parse_chinese_number
from bidreview.ooxml_build import write_minimal_docx


def test_chinese_numerals():
    assert parse_chinese_number("一百八十") == 180
    assert parse_chinese_number("十二") == 12
    assert parse_chinese_number("五十") == 50
    assert parse_chinese_number("两千") == 2000
    assert parse_chinese_number("一千二百八十万") == 12800000
    assert parse_chinese_number("壹仟贰佰") == 1200


def _review_pair(tmp_path: Path, left: list[str], right: list[str], rules: dict | None = None):
    template = tmp_path / "template.docx"
    a = tmp_path / "a.docx"
    b = tmp_path / "b.docx"
    write_minimal_docx(template, ["模板"])
    write_minimal_docx(a, left)
    write_minimal_docx(b, right)
    return review(
        template=template,
        documents=[(a, "tender", ""), (b, "contract", "")],
        conforming=set(),
        rules=rules or {},
        out_dir=tmp_path / "out",
    )


def test_ceiling_is_not_a_conflict_when_plan_is_inside_it(tmp_path: Path):
    result = _review_pair(
        tmp_path,
        ["本项目总工期为180日历天。"],
        ["总工期最长不超过210日历天。"],
    )
    assert not any(finding.rule_id == "VALUE_CONFLICT" and finding.details.get("subject") == "总工期" for finding in result.findings)


def test_assignment_above_ceiling_is_a_conflict(tmp_path: Path):
    result = _review_pair(
        tmp_path,
        ["本项目总工期为180日历天。"],
        ["总工期最长不超过100日历天。"],
    )
    assert any(finding.key == "VALUE_CONFLICT:总工期" for finding in result.findings)


def test_length_units_that_convert_are_not_conflicts(tmp_path: Path):
    result = _review_pair(
        tmp_path,
        ["光缆长度为2千米。"],
        ["光缆长度为2000米。"],
    )
    assert not any("光缆" in (finding.details.get("subject") or "") for finding in result.findings)


def test_months_are_not_converted_into_days(tmp_path: Path):
    result = _review_pair(
        tmp_path,
        ["服务期为12个月。"],
        ["服务期为360日历天。"],
    )
    finding = next(item for item in result.findings if item.key == "UNIT_FAMILY:服务期")
    assert finding.category == "需要人工判断"
    assert not any(item.rule_id == "VALUE_CONFLICT" and item.details.get("subject") == "服务期" for item in result.findings)


def test_user_alias_is_explicit(tmp_path: Path):
    no_alias = _review_pair(
        tmp_path / "no",
        ["考核工期为100日历天。"],
        ["本项目总工期为80日历天。"],
    )
    assert not any(item.details.get("subject") == "总工期" and item.rule_id == "VALUE_CONFLICT" for item in no_alias.findings)
    aliased = _review_pair(
        tmp_path / "yes",
        ["考核工期为100日历天。"],
        ["本项目总工期为80日历天。"],
        rules={"subject_aliases": [{"family": "duration", "canonical": "总工期", "labels": ["考核工期"]}]},
    )
    assert any(item.key == "VALUE_CONFLICT:总工期" for item in aliased.findings)


def test_minimum_allows_a_higher_assignment(tmp_path: Path):
    result = _review_pair(
        tmp_path,
        ["精密空调制冷量不低于20kW。"],
        ["精密空调制冷量为25kW。"],
    )
    assert not any("精密空调" in (item.details.get("subject") or "") for item in result.findings)


def test_blank_pdf_is_human_review(tmp_path: Path):
    from pypdf import PdfWriter

    from bidreview.engine import review as review_again

    template = tmp_path / "template.docx"
    blank = tmp_path / "blank.pdf"
    write_minimal_docx(template, ["模板"])
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with blank.open("wb") as handle:
        writer.write(handle)
    result = review_again(
        template=template,
        documents=[(blank, "attachment", "")],
        conforming=set(),
        rules={},
        out_dir=tmp_path / "out",
    )
    assert any(item.key == "NO_TEXT_LAYER:blank" for item in result.findings)
    assert result.inputs_unchanged


def test_sources_do_not_import_network_clients():
    root = Path(__file__).resolve().parents[1] / "src" / "bidreview"
    banned = ("import requests", "import httpx", "import urllib.request", "import openai", "import socket")
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for item in banned:
            assert item not in text, f"{path.name} contains {item}"
