"""厂商原始数据适配器接口。

实现类只负责调用用户自己安装的转换程序，把结果写到本程序的目录。
不得修改、覆盖或删除原始文件。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class AdapterStatus:
    available: bool
    executable: str
    message: str


@dataclass
class ConversionResult:
    output_mzml: Path
    source_sha256_before: str
    source_sha256_after: str
    command: list[str]
    stdout: str
    stderr: str
    warnings: list[str] = field(default_factory=list)


class VendorRawAdapter(Protocol):
    key: str
    display_name: str

    def status(self, executable: str) -> AdapterStatus:
        """executable 为空或文件不存在时，available 为 False。"""

    def convert(self, source: Path, output_dir: Path, *, executable: str,
                extra_args: list[str] | None = None) -> ConversionResult:
        """把原始数据转成 mzML，写到 output_dir。"""
