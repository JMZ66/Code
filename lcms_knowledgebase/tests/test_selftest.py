"""安装包自检入口。不依赖界面。"""

from lcms_kb.selftest import run_self_test


def test_self_test_passes(capsys):
    assert run_self_test() == 0
    output = capsys.readouterr().out
    assert "SELF_TEST_OK" in output
    assert "network_required" in output
