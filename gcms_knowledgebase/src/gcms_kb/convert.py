from __future__ import annotations

import subprocess
from pathlib import Path

from gcms_kb.errors import ConversionFailed, ConverterNotConfigured, OriginalModified, UnsafePath
from gcms_kb.hashing import assert_unchanged, file_size, sha256_file
from gcms_kb.paths import assert_under
from gcms_kb.settings import Settings


def build_thermo_command(executable: str, raw_path: Path, out_dir: Path) -> list[str]:
    """ThermoRawFileParser：-f=1 是普通 mzML。输出目录必须是调用者指定的目录。"""
    return [
        str(executable),
        f"-i={raw_path}",
        f"-o={out_dir}",
        "-f=1",
        "-m=0",
    ]


def build_msconvert_command(executable: str, raw_path: Path, out_dir: Path) -> list[str]:
    return [str(executable), str(raw_path), "--mzML", "-o", str(out_dir)]


def _existing_mzml(out_dir: Path) -> set[Path]:
    found = set()
    for pattern in ("*.mzML", "*.mzml"):
        found.update(path.resolve() for path in out_dir.glob(pattern))
    return found


def convert_raw_to_mzml(raw_path: Path, out_dir: Path, settings: Settings, data_dir: Path) -> Path:
    """调用本机已安装的转换器。不修改 RAW。转换结果只写到数据目录。"""
    raw_path = Path(raw_path).resolve()
    out_dir = assert_under(data_dir, Path(out_dir))
    if not raw_path.is_file():
        raise ConversionFailed(f"找不到 RAW 文件：{raw_path}")
    if raw_path.parent == out_dir or out_dir in raw_path.parents:
        raise UnsafePath("转换输出不能放在原始文件所在目录内。")
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = sha256_file(raw_path)
    size = file_size(raw_path)
    before = _existing_mzml(out_dir)
    if settings.thermo_parser_path:
        command = build_thermo_command(settings.thermo_parser_path, raw_path, out_dir)
        tool = "ThermoRawFileParser"
    elif settings.msconvert_path:
        command = build_msconvert_command(settings.msconvert_path, raw_path, out_dir)
        tool = "msconvert"
    else:
        raise ConverterNotConfigured(
            "没有配置 RAW 转换器。本程序不附带 Thermo RawFileReader 或 ProteoWizard。"
            "请在设置中填写本机 ThermoRawFileParser 或 msconvert 的路径。"
        )
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=int(settings.convert_timeout_sec),
        )
    except subprocess.TimeoutExpired as exc:
        raise ConversionFailed(f"{tool} 超时。") from exc
    except OSError as exc:
        raise ConversionFailed(f"无法启动 {tool}：{exc}") from exc
    try:
        assert_unchanged(raw_path, digest, size)
    except OriginalModified:
        raise
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise ConversionFailed(f"{tool} 转换失败（退出码 {completed.returncode}）。\n{message[-2000:]}")
    after = _existing_mzml(out_dir)
    created = sorted(after - before, key=lambda path: path.stat().st_mtime)
    if not created:
        stem_matches = [
            path
            for path in after
            if path.stem.lower() == raw_path.stem.lower()
        ]
        created = stem_matches
    if not created:
        raise ConversionFailed(f"{tool} 没有在输出目录产生 mzML。")
    produced = created[-1]
    assert_under(data_dir, produced)
    if produced.resolve() == raw_path:
        raise UnsafePath("转换器试图覆盖原始文件，已拒绝。")
    assert_unchanged(raw_path, digest, size)
    return produced
