"""Render the Chinese manuals to PDF with the bundled font."""

from __future__ import annotations

import argparse
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from chem_wh.constants import DISCLAIMER
from chem_wh.services.reports import register_chinese_font
from chem_wh.utils.resources import source_root


def render_markdown_pdf(md_path: Path, pdf_path: Path) -> Path:
    font = register_chinese_font()
    text = Path(md_path).read_text(encoding="utf-8")
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=48,
        rightMargin=48,
        topMargin=48,
        bottomMargin=42,
    )
    h1 = ParagraphStyle("h1", fontName=font, fontSize=16, leading=22, spaceAfter=8)
    h2 = ParagraphStyle("h2", fontName=font, fontSize=13, leading=18, spaceBefore=8, spaceAfter=4)
    body = ParagraphStyle("body", fontName=font, fontSize=10, leading=15, spaceAfter=3)
    story = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            story.append(Spacer(1, 6))
            continue
        if line.startswith("# "):
            story.append(Paragraph(escape(line[2:].strip()), h1))
        elif line.startswith("## "):
            story.append(Paragraph(escape(line[3:].strip()), h2))
        elif line.startswith("### "):
            story.append(Paragraph(escape(line[4:].strip()), h2))
        else:
            story.append(Paragraph(escape(line), body))
    if not story:
        story.append(Paragraph(escape(DISCLAIMER), body))

    def footer(pdf, doc_):
        pdf.saveState()
        pdf.setFont(font, 8)
        pdf.drawString(48, 22, "本手册不能替代危险化学品法定安全管理要求")
        pdf.drawRightString(A4[0] - 48, 22, f"第 {doc_.page} 页")
        pdf.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return pdf_path


def render_packaged_docs(out_dir: Path) -> list[Path]:
    out_dir = Path(out_dir)
    docs = source_root() / "docs"
    written = []
    for name in ("用户手册.md", "测试报告.md"):
        src = docs / name
        if src.is_file():
            written.append(render_markdown_pdf(src, out_dir / (src.stem + ".pdf")))
    return written


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="生成中文手册 PDF")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    paths = render_packaged_docs(Path(args.out))
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
