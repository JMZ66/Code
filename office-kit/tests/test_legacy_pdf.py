from office_kit.ooxml import sha256_file
from office_kit.parse import UnsupportedFormat, parse_path


def test_doc_without_converter_is_explicit(tmp_path, monkeypatch):
    path = tmp_path / "old.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0not-a-real-doc")
    before = sha256_file(path)
    monkeypatch.setattr("office_kit.legacy.converter_command", lambda: None)
    document = parse_path(path)
    assert document.status == "converter_unavailable"
    assert document.warnings[0]["code"] == "doc_converter_missing"
    assert "LibreOffice" in document.warnings[0]["message"]
    assert sha256_file(path) == before
    assert document.word is None


def test_pdf_interface_is_reserved(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF")
    document = parse_path(path)
    assert document.status == "reserved"
    assert document.kind == "pdf"
    assert document.pdf == {"implemented": False}
    assert document.source.sha256 == sha256_file(path)
    assert document.word is None
    assert document.excel is None


def test_unknown_extension(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("hello", encoding="utf-8")
    try:
        parse_path(path)
    except UnsupportedFormat as exc:
        assert ".txt" in str(exc)
    else:
        raise AssertionError("expected UnsupportedFormat")
