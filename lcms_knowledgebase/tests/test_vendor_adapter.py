"""外部转换程序的命令行和只读约束。

不启动真实的 msconvert。测试用替身完成子进程调用，因此在 Windows 上
也不依赖 shell 脚本。替身只按参数把 mzML 写到指定输出目录。
"""

from pathlib import Path

import pytest

from lcms_kb.errors import ConverterUnavailable, LCMSError
from lcms_kb.hashing import sha256_file
from lcms_kb.vendor.msconvert import MsConvertAdapter
from lcms_kb.vendor.thermo import ThermoRawFileParserAdapter


class _Completed:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _fake_msconvert(command, **_kwargs):
    out = None
    args = list(command)
    index = 0
    while index < len(args):
        if args[index] == "--outdir" and index + 1 < len(args):
            out = Path(args[index + 1])
            index += 2
            continue
        index += 1
    assert out is not None
    out.mkdir(parents=True, exist_ok=True)
    (out / "sample.mzML").write_text('<?xml version="1.0"?><mzML></mzML>', encoding="utf-8")
    return _Completed()


def _fake_thermo(command, **_kwargs):
    out = None
    for arg in command:
        text = str(arg)
        if text.startswith("-o="):
            out = Path(text[3:])
    assert out is not None
    out.mkdir(parents=True, exist_ok=True)
    (out / "a.mzML").write_text('<?xml version="1.0"?><mzML></mzML>', encoding="utf-8")
    (out / "args.txt").write_text("\n".join(str(item) for item in command), encoding="utf-8")
    return _Completed()


def test_msconvert_missing_and_fake_conversion(tmp_path, monkeypatch):
    adapter = MsConvertAdapter()
    assert adapter.status("").available is False
    source = tmp_path / "sample.raw"
    source.write_bytes(b"raw-bytes-not-modified")
    before = sha256_file(source)
    out = tmp_path / "out"
    script = tmp_path / "msconvert.exe"
    script.write_bytes(b"not-a-real-binary")
    monkeypatch.setattr("lcms_kb.vendor.msconvert.subprocess.run", _fake_msconvert)
    result = adapter.convert(source, out, executable=str(script))
    assert result.output_mzml.name == "sample.mzML"
    assert result.source_sha256_before == before
    assert sha256_file(source) == before
    assert "--mzML" in result.command
    assert "--outdir" in result.command
    assert str(out) in result.command
    with pytest.raises(LCMSError):
        adapter.convert(source, source.parent, executable=str(script))


def test_thermo_parser_uses_equals_form_and_refuses_missing(tmp_path, monkeypatch):
    adapter = ThermoRawFileParserAdapter()
    with pytest.raises(ConverterUnavailable):
        adapter.convert(tmp_path / "a.raw", tmp_path / "out", executable="")
    source = tmp_path / "a.raw"
    source.write_bytes(b"thermo")
    out = tmp_path / "out"
    script = tmp_path / "ThermoRawFileParser.exe"
    script.write_bytes(b"not-a-real-binary")
    monkeypatch.setattr("lcms_kb.vendor.thermo.subprocess.run", _fake_thermo)
    result = adapter.convert(source, out, executable=str(script))
    args = (out / "args.txt").read_text(encoding="utf-8")
    assert f"-i={source}" in args
    assert f"-o={out}" in args
    assert "-f=2" in args
    assert "-p" in args
    assert sha256_file(source) == result.source_sha256_after
    assert result.command[0] == str(script)
