from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_standards_record_says_what_was_and_was_not_read():
    text = (ROOT / "docs" / "标准与公式清单.md").read_text(encoding="utf-8")
    assert "Evaluation of measurement uncertainty from in-house precision and recovery data" in text
    assert "2026-03-15" in text
    assert "978-972-9348-30-3" in text
    assert "未取得官方全文" in text
    assert "未取得修订全文" in text
    assert "不是法律" in text
    assert "0.049246827308974936" in (ROOT / "docs" / "数值验证.md").read_text(encoding="utf-8")
    assert "1.0079006591337099" in (ROOT / "docs" / "数值验证.md").read_text(encoding="utf-8")
