# -*- mode: python ; coding: utf-8 -*-
# Onedir layout. Distribute the whole BidReview folder, not the exe alone.

from pathlib import Path

root = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(root / "src" / "bidreview" / "__main__.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[
        (str(root / "docs"), "docs"),
        (str(root / "README.md"), "."),
        (str(root / "LICENSE"), "."),
        (str(root / "packaging" / "使用说明.txt"), "."),
    ],
    hiddenimports=[
        "bidreview",
        "bidreview.gui",
        "bidreview.cli",
        "bidreview.selftest",
        "bidreview.ooxml_build",
        "openpyxl",
        "lxml",
        "lxml.etree",
        "pypdf",
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "docx", "reportlab", "tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BidReview",
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
    name="BidReview",
)
