from bid_review.main import _run_self_test


def test_self_test_pipeline(tmp_path):
    assert _run_self_test(str(tmp_path / "out")) == 0
