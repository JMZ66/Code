import os
import stat
from pathlib import Path

from bidreview.engine import review
from bidreview.integrity import sha256_file
from tests.corpus_builder import EXPECTED, NEGATIVES, build_corpus
from tests.scoring import score


def test_synthetic_package_miss_and_false_positive_rates(tmp_path: Path):
    corpus = build_corpus(tmp_path / "corpus")
    sources = [path for path in corpus.iterdir() if path.suffix.lower() in {".docx", ".pdf", ".xlsx"}]
    before = {path.name: sha256_file(path) for path in sources}
    for path in sources:
        path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    try:
        result = review(
            template=corpus / "00_投标文件格式模板.docx",
            documents=[
                (corpus / "01_招标文件.docx", "tender", "招标文件"),
                (corpus / "02_投标文件格式响应.docx", "conforming", "投标文件格式响应"),
                (corpus / "03_采购清单及预算.xlsx", "budget", "采购清单及预算"),
                (corpus / "04_合同条款.docx", "contract", "合同条款"),
                (corpus / "05_技术标准和要求.docx", "technical", "技术标准和要求"),
                (corpus / "06_技术标准和要求摘录.pdf", "technical", "技术标准和要求摘录"),
                (corpus / "07_附件_营业执照.pdf", "attachment", "营业执照"),
            ],
            conforming={"02_投标文件格式响应.docx"},
            rules={"external_basis": [{"title": "GB/T 50314 智能建筑设计标准"}]},
            out_dir=tmp_path / "out",
        )
    finally:
        for path in sources:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    after = {path.name: sha256_file(path) for path in sources}
    assert before == after
    assert result.inputs_unchanged
    metrics = score(result.findings, EXPECTED, NEGATIVES)
    debug = {
        "missed": metrics["missed"],
        "false_positives": metrics["false_positives"],
        "extras": metrics["extras"],
        "keys": sorted(finding.key + " | " + finding.category + " | " + finding.title for finding in result.findings),
    }
    assert metrics["miss_count"] == 0, debug
    assert metrics["false_positive_count"] == 0, debug
    assert metrics["extra_count"] == 0, debug
    assert metrics["miss_rate"] == 0
    assert metrics["false_positive_rate"] == 0

    for finding in result.findings:
        assert finding.category in {"确定错误", "疑似冲突", "缺少依据", "需要人工判断"}
        assert finding.original_text.strip()
        assert finding.files
        assert finding.sections
        assert finding.locations
        assert finding.basis.strip()
        assert finding.suggestion.strip()
        assert "本工具" in finding.suggestion

    duration = next(finding for finding in result.findings if finding.key == "VALUE_CONFLICT:总工期")
    assert 2 in duration.pdf_pages
    assert duration.original_text
    assert duration.locations
    assert duration.basis
    assert "01_招标文件.docx" in duration.files
    assert any(path.name.endswith(".html") or path.suffix == ".html" for path in Path(result.out_dir).iterdir())
    report = (tmp_path / "out" / "审查报告.md").read_text(encoding="utf-8")
    assert "总工期" in report
    assert "确定错误" in report
    workbook_text = (tmp_path / "out" / "审查报告.html").read_text(encoding="utf-8")
    assert "http://" not in workbook_text
    assert "https://" not in workbook_text
    index = (tmp_path / "out" / "index.json").read_text(encoding="utf-8")
    assert "投标人须知前附表" in index
    assert "采购清单及预算" in index
