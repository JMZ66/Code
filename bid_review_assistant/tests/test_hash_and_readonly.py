from __future__ import annotations

from pathlib import Path

from bid_review.hashutil import sha256_file
from bid_review.pipeline import run_review


def test_sha256_unchanged_after_review(tmp_path, fixture_pack):
    inputs = [
        fixture_pack / "01_招标正文.docx",
        fixture_pack / "02_预算与采购清单.xlsx",
        fixture_pack / "04_合同条款.docx",
    ]
    before = {p.name: sha256_file(p) for p in inputs}
    out = tmp_path / "reports"
    result, paths = run_review(
        inputs,
        out,
        template_docx=fixture_pack / "00_官方模板.docx",
        profile_json=fixture_pack / "profile.json",
        role_hints={
            "01_招标正文.docx": "正文",
            "02_预算与采购清单.xlsx": "预算",
            "04_合同条款.docx": "合同",
        },
    )
    after = {p.name: sha256_file(p) for p in inputs}
    assert before == after
    assert all(i.unchanged for i in result.integrity)
    assert Path(paths["markdown"]).exists()
    assert Path(paths["html"]).exists()
    assert Path(paths["excel"]).exists()
