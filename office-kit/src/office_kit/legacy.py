"""Optional .doc conversion.

LibreOffice is an external process (MPL-2.0). It is not imported and not
required. The original file is copied into a temp directory first; the
converter only sees that copy. If ``soffice`` is missing, the result says so
and the original bytes are left untouched.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from office_kit.models import Document, SourceInfo
from office_kit.ooxml import sha256_file
from office_kit.word import parse_docx


def converter_command() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def parse_doc(path: Path, sha256: str) -> Document:
    before = sha256_file(path)
    source = SourceInfo(
        path=str(path),
        filename=path.name,
        format="doc",
        sha256=before,
        size=path.stat().st_size,
    )
    command = converter_command()
    if command is None:
        return Document(
            source=source,
            kind="word",
            status="converter_unavailable",
            warnings=[
                {
                    "code": "doc_converter_missing",
                    "message": "未找到 LibreOffice（soffice 或 libreoffice）。.doc 需要可选的外部转换，原文件未读取内容也未修改。请安装 LibreOffice，或先把文件另存为 .docx。",
                }
            ],
        )
    with tempfile.TemporaryDirectory(prefix="office-kit-doc-") as tmp:
        folder = Path(tmp)
        copy = folder / path.name
        copy.write_bytes(path.read_bytes())
        proc = subprocess.run(
            [command, "--headless", "--norestore", "--convert-to", "docx", "--outdir", str(folder), str(copy)],
            capture_output=True,
            timeout=120,
            check=False,
        )
        produced = folder / f"{path.stem}.docx"
        after = sha256_file(path)
        if after != before or after != sha256:
            return Document(
                source=source,
                kind="word",
                status="error",
                warnings=[
                    {
                        "code": "source_changed_during_conversion",
                        "message": "转换过程中原文件的 SHA-256 发生了变化，已停止解析。",
                    }
                ],
            )
        if proc.returncode != 0 or not produced.exists():
            detail = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace")[-500:]
            return Document(
                source=source,
                kind="word",
                status="error",
                warnings=[
                    {
                        "code": "doc_convert_failed",
                        "message": f"LibreOffice 未能把副本转成 docx。原文件未修改。{detail}",
                    }
                ],
            )
        document = parse_docx(
            produced,
            before,
            source_format="doc",
            converter="libreoffice",
            converted_from=str(path),
            size=path.stat().st_size,
        )
    document.source.path = str(path)
    document.source.filename = path.name
    document.source.sha256 = before
    document.warnings.insert(
        0,
        {
            "code": "doc_converted",
            "message": "已用 LibreOffice 把临时副本转为 docx 再解析。原文件未修改。修订、宏和部分版式可能在转换中变化，不能把转换结果当成与 .doc 字节级一致。",
        },
    )
    return document
