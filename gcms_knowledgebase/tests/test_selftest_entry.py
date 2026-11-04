import os
import subprocess
import sys
from pathlib import Path

PUBLIC_MZML = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "gcms_kb"
    / "resources"
    / "testdata"
    / "public"
    / "small.pwiz.1.1.mzML"
)


def test_self_test_entrypoint_imports_public_mzml(tmp_path):
    log = tmp_path / "selftest.log"
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["MPLBACKEND"] = "Agg"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "gcms_kb",
            "--self-test",
            str(PUBLIC_MZML),
            "--self-test-log",
            str(log),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    text = log.read_text(encoding="utf-8")
    assert "SELF_TEST_OK" in text
    assert "FTMS" in text
    assert "synthetic=0" in text
