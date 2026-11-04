"""适配器登记。其他厂商走 msconvert 加用户自己安装的厂商 DLL，不在这里写解码器。"""

from __future__ import annotations

from lcms_kb.vendor.msconvert import MsConvertAdapter
from lcms_kb.vendor.thermo import ThermoRawFileParserAdapter

ADAPTERS = {
    MsConvertAdapter.key: MsConvertAdapter(),
    ThermoRawFileParserAdapter.key: ThermoRawFileParserAdapter(),
}

# 扩展名只用来提示该找哪个外部程序，不表示本程序能直接解码。
EXTENSION_HINTS = {
    ".raw": "Thermo 或 Waters 都可能使用 .raw。请自行选择 msconvert 或 ThermoRawFileParser，本程序不根据扩展名假定厂商。",
    ".d": "Agilent 或 Bruker 的 .d 目录通常由安装了对应厂商库的 msconvert 读取。",
    ".wiff": "SCIEX .wiff 通常由安装了 SCIEX 库的 msconvert 读取。",
    ".wiff2": "SCIEX .wiff2 通常由安装了 SCIEX 库的 msconvert 读取。",
    ".tdf": "Bruker timsTOF .tdf 通常由安装了 Bruker TDF 库的 msconvert 读取。",
    ".baf": "Bruker .baf 通常由 msconvert 读取。",
    ".yep": "Agilent / Bruker .yep 通常由 msconvert 读取。",
}


def hint_for(suffix: str) -> str:
    return EXTENSION_HINTS.get(suffix.lower(), "这个扩展名没有内置解码器。请先转成 mzML。")
