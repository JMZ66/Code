from bid_review.consistency.engine import _compatible_conditions, _condition_signature
from bid_review.extract.fields import extract_fields
from bid_review.models import DocumentIndex, ExtractedField, Location


def _field(value: str, ctx: str, key: str = "duration") -> ExtractedField:
    return ExtractedField(
        key=key,
        label="工期",
        value=value,
        normalized=value,
        location=Location(filename="a.docx", file_type="docx", excerpt=ctx),
        confidence=0.8,
        context=ctx,
        conditions=[],
    )


def test_conditioned_durations_not_compatible():
    a = _field("180天", "本项目工期为 180 天。")
    b = _field("30天", "若含安装调试服务，则调试期为 30 天。")
    assert _compatible_conditions(a, b) is False


def test_same_matter_durations_compatible():
    a = _field("180天", "本项目工期为 180 天。")
    b = _field("120天", "本项目工期为 120 天。")
    assert _compatible_conditions(a, b) is True


def test_extract_project_and_consortium():
    doc = DocumentIndex(
        path="x",
        filename="招标文件.docx",
        file_type="docx",
        sha256="0",
        size_bytes=1,
        blocks=[],
    )
    from bid_review.models import Block

    texts = [
        "项目名称：智慧实验室设备升级采购项目",
        "本项目不接受联合体投标。",
        "预算金额：人民币 1,200,000 元。",
    ]
    for i, t in enumerate(texts):
        doc.blocks.append(
            Block(
                block_id=str(i),
                kind="paragraph",
                text=t,
                location=Location(
                    filename=doc.filename,
                    file_type="docx",
                    paragraph_index=i,
                    excerpt=t,
                ),
            )
        )
    fields = extract_fields([doc])
    keys = {f.key for f in fields}
    assert "project_name" in keys
    assert "consortium" in keys
    assert "amount" in keys
    assert any(f.normalized == "1200000" for f in fields if f.key == "amount")
