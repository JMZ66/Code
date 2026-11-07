# -*- mode: python ; coding: utf-8 -*-
# Onedir layout. Copy the whole folder, not the exe alone.

from pathlib import Path

root = Path(SPECPATH).resolve().parent

datas = [
    (str(root / "assets" / "fonts" / "wqy-microhei.ttc"), "assets/fonts"),
    (str(root / "assets" / "fonts" / "NOTICE-WenQuanYi.txt"), "assets/fonts"),
    (str(root / "src" / "labuv" / "data" / "examples"), "examples"),
    (str(root / "docs"), "docs"),
]

a = Analysis(
    [str(root / "src" / "labuv" / "main.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "labuv.selftest",
        "labuv.gui.window",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "pint",
        "scipy.stats",
        "numpy",
        "pandas",
        "openpyxl",
        "reportlab.pdfbase.ttfonts",
        "pypdf",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LabUncertainty",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="LabUncertainty",
)
