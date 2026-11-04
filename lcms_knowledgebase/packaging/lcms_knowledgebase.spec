# -*- mode: python ; coding: utf-8 -*-
"""便携目录，而不是单文件。Qt 的 LGPL 库以独立 DLL 形式放在目录里，便于替换。"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).resolve().parent
src = root / "src"
font = src / "lcms_kb" / "resources" / "fonts" / "wqy-microhei.ttc"

datas = [(str(font), "lcms_kb/resources/fonts")]
binaries = []
hiddenimports = collect_submodules("lcms_kb")
for package in ("pyteomics", "psims", "matchms", "matplotlib", "numba", "llvmlite"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    [str(src / "lcms_kb" / "main.py")],
    pathex=[str(src)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6.QtWebEngine",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LCMS_KnowledgeBase",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LCMS_KnowledgeBase",
)
