"""调用用户安装的 ProteoWizard msconvert。

不附带 msconvert，也不附带各厂商 DLL。默认不加峰提取滤镜，
避免在用户没有选择的情况下改变谱图形态。输出目录必须由调用方指定，
不能是原始文件所在目录。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from lcms_kb.errors import ConverterUnavailable, LCMSError
from lcms_kb.hashing import sha256_file
from lcms_kb.vendor.base import AdapterStatus, ConversionResult

# 这些参数会让转换结果不再是“按原始记录写出”。只有用户在界面里另行填写才使用。
UNSAFE_UNLESS_EXPLICIT = ("--filter", "peakPicking")


class MsConvertAdapter:
    key = "msconvert"
    display_name = "ProteoWizard msconvert"

    def status(self, executable: str) -> AdapterStatus:
        path = Path(executable) if executable else None
        if path is None or not executable.strip():
            return AdapterStatus(False, "", "尚未填写 msconvert 路径。请安装 ProteoWizard 后在设置里选择 msconvert.exe。")
        if not path.is_file():
            return AdapterStatus(False, str(path), f"找不到 msconvert：{path}")
        return AdapterStatus(True, str(path), "已找到 msconvert。厂商 DLL 是否齐全由该安装包决定，本程序不检查授权。")

    def convert(self, source: Path, output_dir: Path, *, executable: str,
                extra_args: list[str] | None = None) -> ConversionResult:
        state = self.status(executable)
        if not state.available:
            raise ConverterUnavailable(state.message)
        source = Path(source)
        output_dir = Path(output_dir)
        if not source.exists():
            raise LCMSError(f"找不到原始文件：{source}")
        if source.resolve().parent == output_dir.resolve():
            raise LCMSError("转换输出不能写在原始文件所在目录。")
        output_dir.mkdir(parents=True, exist_ok=True)
        before_names = {item.name for item in source.parent.iterdir()}
        before_hash = sha256_file(source)
        command = [str(Path(executable)), str(source), "--mzML", "--outdir", str(output_dir)]
        if extra_args:
            command.extend(extra_args)
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        after_hash = sha256_file(source)
        if before_hash != after_hash:
            raise LCMSError("msconvert 运行后原始文件哈希变了。已停止使用转换结果。")
        warnings = []
        after_names = {item.name for item in source.parent.iterdir()}
        new_beside = sorted(after_names - before_names)
        if new_beside:
            warnings.append(
                "原始文件目录里出现了新文件：" + ", ".join(new_beside)
                + "。本程序没有删除它们。请确认转换程序没有把结果写到原始数据旁边。"
            )
        if completed.returncode != 0:
            raise LCMSError(
                "msconvert 退出码 "
                f"{completed.returncode}。原始文件未修改。\n{completed.stderr[-2000:]}"
            )
        produced = sorted(output_dir.glob("*.mzML"), key=lambda item: item.stat().st_mtime)
        if not produced:
            produced = sorted(output_dir.glob("*.mzml"), key=lambda item: item.stat().st_mtime)
        if not produced:
            raise LCMSError("msconvert 没有在指定目录写出 mzML。原始文件未修改。")
        return ConversionResult(
            output_mzml=produced[-1],
            source_sha256_before=before_hash,
            source_sha256_after=after_hash,
            command=command,
            stdout=completed.stdout[-4000:],
            stderr=completed.stderr[-4000:],
            warnings=warnings,
        )
