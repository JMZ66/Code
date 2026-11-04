"""可选的外部程序。只在用户填了本机路径且文件存在时启动，不打包、不下载。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from lcms_kb.errors import ConverterUnavailable


def launch_tool(executable: str, tool_name: str) -> None:
    path = Path(executable) if executable else None
    if path is None or not executable.strip() or not path.is_file():
        raise ConverterUnavailable(
            f"未安装或未填写 {tool_name}。本程序不附带该软件，也不会联网下载。"
        )
    subprocess.Popen([str(path)])  # noqa: S603  路径来自用户本机设置，不经 shell
