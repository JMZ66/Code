# -*- mode: python ; coding: utf-8 -*-
# Onedir build for PySide6 stability.

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).resolve().parent

datas = [
    (str(root / "config" / "default_template_profile.json"), "config"),
]

a = Analysis(
    [str(root / "src" / "bid_review" / "main.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "bid_review",
        "bid_review.main",
        "bid_review.gui.app",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "docx",
        "openpyxl",
        "pypdf",
        "lxml",
        "_hashlib",
    ]
    + collect_submodules("bid_review"),
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
    name="BidReviewAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="BidReviewAssistant",
)
