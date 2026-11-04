# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).resolve().parent
src = root / "src"
datas = [(str(src / "gcms_kb" / "resources"), "gcms_kb/resources")]
binaries = []
hidden = [
    "gcms_kb",
    "gcms_kb.app",
    "gcms_kb.gui.main_window",
    "gcms_kb.gui.dialogs",
    "gcms_kb.gui.plots",
    "matchms.similarity.CosineGreedy",
    "matchms.importing.load_from_msp",
    "matchms.exporting.save_as_msp",
    "pyteomics.mzml",
    "psims",
    "scipy.signal",
    "scipy.optimize",
    "openpyxl",
    "reportlab.pdfbase.ttfonts",
    "pyqtgraph",
]
for package in ("rdkit", "matchms"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hidden += package_hidden

a = Analysis(
    [str(src / "gcms_kb" / "__main__.py")],
    pathex=[str(src)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GCMS_KnowledgeBase",
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="GCMS_KnowledgeBase",
)
