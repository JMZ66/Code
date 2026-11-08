from pathlib import Path

from bid_review.integrity import IntegrityGuard, sha256_file


def test_sha256_stable(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_text("招投标", encoding="utf-8")
    assert sha256_file(f) == sha256_file(f)


def test_guard_detects_change(tmp_path: Path):
    f = tmp_path / "b.docx"
    f.write_bytes(b"PK\x03\x04demo")
    g = IntegrityGuard()
    g.snapshot_before([f])
    f.write_bytes(b"PK\x03\x04changed")
    result = g.verify_after()
    assert len(result) == 1
    assert result[0].unchanged is False
