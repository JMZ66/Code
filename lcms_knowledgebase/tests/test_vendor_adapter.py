"""外部转换程序只按给定路径调用，并且不改原始文件。"""

import os
import stat
from pathlib import Path

import pytest

from lcms_kb.errors import ConverterUnavailable, LCMSError
from lcms_kb.hashing import sha256_file
from lcms_kb.vendor.msconvert import MsConvertAdapter
from lcms_kb.vendor.thermo import ThermoRawFileParserAdapter


def _fake_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def test_msconvert_missing_and_fake_conversion(tmp_path):
    adapter = MsConvertAdapter()
    assert adapter.status("").available is False
    source = tmp_path / "sample.raw"
    source.write_bytes(b"raw-bytes-not-modified")
    before = sha256_file(source)
    out = tmp_path / "out"
    script = tmp_path / "msconvert"
    _fake_executable(script, """#!/bin/sh
# 假的 msconvert：把参数写到日志，并在 --outdir 里放一个 mzML。不碰输入文件。
out=""
while [ $# -gt 0 ]; do
  if [ "$1" = "--outdir" ]; then
    out="$2"
    shift 2
  else
    shift
  fi
done
mkdir -p "$out"
printf '<?xml version="1.0"?><mzML></mzML>' > "$out/sample.mzML"
""")
    result = adapter.convert(source, out, executable=str(script))
    assert result.output_mzml.name == "sample.mzML"
    assert result.source_sha256_before == before
    assert sha256_file(source) == before
    assert "--mzML" in result.command
    assert "--outdir" in result.command
    with pytest.raises(LCMSError):
        adapter.convert(source, source.parent, executable=str(script))


def test_thermo_parser_uses_equals_form_and_refuses_missing(tmp_path):
    adapter = ThermoRawFileParserAdapter()
    with pytest.raises(ConverterUnavailable):
        adapter.convert(tmp_path / "a.raw", tmp_path / "out", executable="")
    source = tmp_path / "a.raw"
    source.write_bytes(b"thermo")
    out = tmp_path / "out"
    script = tmp_path / "ThermoRawFileParser"
    _fake_executable(script, """#!/bin/sh
out=""
for arg in "$@"; do
  case "$arg" in
    -o=*) out="${arg#-o=}" ;;
  esac
done
mkdir -p "$out"
printf '<?xml version="1.0"?><mzML></mzML>' > "$out/a.mzML"
printf '%s\n' "$@" > "$out/args.txt"
""")
    result = adapter.convert(source, out, executable=str(script))
    args = (out / "args.txt").read_text(encoding="utf-8")
    assert f"-i={source}" in args
    assert f"-o={out}" in args
    assert "-f=2" in args
    assert "-p" in args
    assert sha256_file(source) == result.source_sha256_after
    assert os.name  # 避免未使用导入的告警；平台无关
