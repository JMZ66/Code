"""调用用户安装的 ThermoRawFileParser。

该程序自带 Thermo RawFileReader，许可不允许本软件再分发，因此这里只保留调用接口。
参数形式采用官方要求的 ``-选项=值``。默认 ``-f=2``（indexed mzML）和 ``-p``
（不用 Thermo 库做峰提取），输出目录单独指定，避免写回原始文件旁边。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from lcms_kb.errors import ConverterUnavailable, LCMSError
from lcms_kb.hashing import sha256_file
from lcms_kb.vendor.base import AdapterStatus, ConversionResult


class ThermoRawFileParserAdapter:
    key = "thermo_raw_file_parser"
    display_name = "ThermoRawFileParser"

    def status(self, executable: str) -> AdapterStatus:
        if not executable or not executable.strip():
            return AdapterStatus(
                False, "",
                "尚未填写 ThermoRawFileParser 路径。该工具及其 Thermo 库需由用户自行安装，本程序不附带。",
            )
        path = Path(executable)
        if not path.is_file():
            return AdapterStatus(False, str(path), f"找不到 ThermoRawFileParser：{path}")
        return AdapterStatus(True, str(path), "已找到 ThermoRawFileParser。它只能读取 Thermo RAW，不能代表其他厂商。")

    def convert(self, source: Path, output_dir: Path, *, executable: str,
                extra_args: list[str] | None = None, peak_picking: bool = False) -> ConversionResult:
        state = self.status(executable)
        if not state.available:
            raise ConverterUnavailable(state.message)
        source = Path(source)
        output_dir = Path(output_dir)
        if not source.is_file():
            raise LCMSError(f"找不到原始文件：{source}")
        if source.resolve().parent == output_dir.resolve():
            raise LCMSError("转换输出不能写在原始文件所在目录。")
        output_dir.mkdir(parents=True, exist_ok=True)
        before_names = {item.name for item in source.parent.iterdir()}
        before_hash = sha256_file(source)
        # -m=2：不另写元数据文件。-f=2：indexed mzML。默认 -p 关闭厂商峰提取。
        command = [
            str(Path(executable)),
            f"-i={source}",
            f"-o={output_dir}",
            "-f=2",
            "-m=2",
        ]
        if not peak_picking:
            command.append("-p")
        if extra_args:
            command.extend(extra_args)
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        after_hash = sha256_file(source)
        if before_hash != after_hash:
            raise LCMSError("ThermoRawFileParser 运行后原始文件哈希变了。已停止使用转换结果。")
        warnings = []
        new_beside = sorted({item.name for item in source.parent.iterdir()} - before_names)
        if new_beside:
            warnings.append("原始文件目录出现新文件：" + ", ".join(new_beside) + "。本程序没有删除它们。")
        if completed.returncode != 0:
            raise LCMSError(
                "ThermoRawFileParser 退出码 "
                f"{completed.returncode}。原始文件未修改。\n{completed.stderr[-2000:]}"
            )
        produced = sorted(output_dir.glob("*.mzML"), key=lambda item: item.stat().st_mtime)
        if not produced:
            raise LCMSError("ThermoRawFileParser 没有在指定目录写出 mzML。原始文件未修改。")
        return ConversionResult(
            output_mzml=produced[-1],
            source_sha256_before=before_hash,
            source_sha256_after=after_hash,
            command=command,
            stdout=completed.stdout[-4000:],
            stderr=completed.stderr[-4000:],
            warnings=warnings,
        )
