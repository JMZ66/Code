from office_kit.checks import run_checks
from office_kit.models import Evidence
from office_kit.parse import parse_path
from office_kit.semantic import DisabledSemanticProvider

from tests.factory import bill_xlsx, simple_docx


class _PretendSource:
    name = "fake"

    def infer(self, request):
        excerpt = request["excerpts"][0]
        return [
            {
                "origin": "source",
                "message": "这两句可能矛盾",
                "evidence": [
                    {
                        "source_path": excerpt["path"],
                        "sha256": excerpt["sha256"],
                        "anchor": excerpt["anchor"],
                        "quote": excerpt["quote"],
                    }
                ],
            },
            {"origin": "source", "message": "没有位置", "evidence": []},
        ]


def _tender(path):
    simple_docx(
        path,
        [
            ("p", "Heading1", "投标人须知"),
            ("p", None, "1.1 业绩要求：近三年同类业绩不少于3个，单项合同金额不低于100万元。"),
            ("p", None, "1.2 评分：同类业绩每提供1个得2分，最高6分。"),
            ("p", None, "1.3 人员要求：项目经理须具备一级建造师证书。"),
            ("p", None, "1.4 人员要求：技术负责人须具备高级工程师职称。"),
            (
                "tbl",
                [
                    ["参数名称", "招标要求", "投标响应"],
                    ["扬程", "≥50m", "45m"],
                    ["流量", "≥100m³/h", "120m³/h"],
                ],
            ),
            ("p", None, "投标总价：人民币1,250,000.00元（大写：壹佰贰拾伍万元整）"),
            ("p", None, "质保金为100元（大写：贰佰元整）"),
            ("p", "Heading1", "合同条款"),
            ("p", None, "2.1 工期为90日历天，不得延误。"),
            ("p", "Heading1", "通用条款"),
            ("p", None, "3.1 付款方式为验收合格后支付。"),
        ],
    )


def _response(path):
    simple_docx(
        path,
        [
            ("p", "Heading1", "合同条款"),
            ("p", None, "2.1 工期为120日历天，不得延误。"),
            ("p", "Heading1", "通用条款"),
            ("p", None, "3.1 付款方式为验收合格后支付。"),
            (
                "tbl",
                [
                    ["职务", "姓名", "资格证书"],
                    ["项目经理", "张三", "二级建造师"],
                    ["技术负责人", "李四", "高级工程师"],
                ],
            ),
            ("p", None, "投标总价：人民币1300000元（大写：壹佰叁拾万元整）"),
        ],
    )


def test_cross_file_rules_and_inference_label(tmp_path):
    tender = tmp_path / "招标文件.docx"
    response = tmp_path / "投标文件.docx"
    bill = tmp_path / "清单.xlsx"
    _tender(tender)
    _response(response)
    bill_xlsx(bill)
    report = run_checks([parse_path(tender), parse_path(response), parse_path(bill)], semantic=_PretendSource())
    rules = {item["rule_id"] for item in report["findings"]}
    assert "param.compare" in rules
    assert "amount.line" in rules
    assert "amount.cross_file" in rules
    assert "amount.capital" in rules
    assert "threshold.vs_scoring" in rules
    assert "personnel.qualification" in rules
    assert "clause.consistency" in rules
    param = next(item for item in report["findings"] if item["rule_id"] == "param.compare" and item["details"].get("name") == "扬程")
    assert param["origin"] == "source"
    assert param["category"] == "确定错误"
    assert len(param["evidence"]) == 2
    assert all(item["sha256"] and item["anchor"] for item in param["evidence"])
    assert not any(item["rule_id"] == "param.compare" and item["details"].get("name") == "流量" and item["severity"] == "error" for item in report["findings"])
    people = [item for item in report["findings"] if item["rule_id"] == "personnel.qualification"]
    assert any(item["details"]["role"] == "项目经理" for item in people)
    assert not any(item["details"]["role"] == "技术负责人" and item["severity"] == "error" for item in people)
    clause = next(item for item in report["findings"] if item["rule_id"] == "clause.consistency")
    assert clause["details"]["label"] == "2.1"
    assert not any(item["rule_id"] == "clause.consistency" and item["details"]["label"] == "3.1" for item in report["findings"])
    capital = next(item for item in report["findings"] if item["rule_id"] == "amount.capital")
    assert capital["details"]["arabic_yuan"] == 100
    assert capital["details"]["capital_yuan"] == 200
    cross = next(item for item in report["findings"] if item["rule_id"] == "amount.cross_file")
    assert cross["category"] == "确定错误"
    assert 1250000 in cross["details"]["yuan"]
    assert 1300000 in cross["details"]["yuan"]
    inferred = [item for item in report["findings"] if item["origin"] == "inference"]
    assert len(inferred) == 1
    assert inferred[0]["message"].startswith("【推断】")
    assert inferred[0]["origin"] == "inference"
    assert any(item["code"] == "inference_dropped" for item in report["warnings"])
    quiet = run_checks([parse_path(tender)], semantic=DisabledSemanticProvider())
    assert all(item["origin"] == "source" for item in quiet["findings"])


def test_evidence_shape():
    evidence = Evidence(source_path="a", sha256="abc", anchor="part#/p", quote="原文")
    assert evidence.anchor.startswith("part#")
