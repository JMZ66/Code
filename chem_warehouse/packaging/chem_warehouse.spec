# -*- mode: python ; coding: utf-8 -*-
# Onedir build. onefile is a poor fit for PySide6 (slow start, fragile plugin extraction).
# PyInstaller injects Analysis, PYZ, EXE, COLLECT and SPECPATH.

from pathlib import Path

root = Path(SPECPATH).resolve().parent

datas = [
    (str(root / "assets" / "fonts" / "DroidSansFallbackFull.ttf"), "assets/fonts"),
    (str(root / "assets" / "fonts" / "NOTICE-DroidSans.txt"), "assets/fonts"),
    (str(root / "assets" / "fonts" / "Apache-2.0.txt"), "assets/fonts"),
]

a = Analysis(
    [str(root / "src" / "chem_wh" / "main.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "chem_wh.selftest",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "reportlab.graphics.barcode.qr",
        "reportlab.graphics.barcode.code128",
        "reportlab.pdfbase.ttfonts",
        "PIL.Image",
        "openpyxl",
        "_hashlib",
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
    name="ChemWarehouse",
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
    name="ChemWarehouse",
)
