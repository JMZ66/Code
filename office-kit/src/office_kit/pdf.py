"""Reserved PDF entry point. No extractor is bundled."""

from __future__ import annotations

from pathlib import Path

from office_kit.models import Document, SourceInfo


def parse_pdf(path: Path, sha256: str) -> Document:
    return Document(
        source=SourceInfo(
            path=str(path),
            filename=path.name,
            format="pdf",
            sha256=sha256,
            size=path.stat().st_size,
        ),
        kind="pdf",
        status="reserved",
        pdf={"implemented": False},
        warnings=[
            {
                "code": "pdf_reserved",
                "message": "PDF 解析接口已预留，当前版本不抽取文本、版面或坐标。文件已记录 SHA-256，内容为空。",
            }
        ],
    )
