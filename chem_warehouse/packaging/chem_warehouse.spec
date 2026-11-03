# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Windows offline EXE
# Build on Windows: pyinstaller packaging/chem_warehouse.spec

block_cipher = None

a = Analysis(
    ['../src/chem_wh/main.py'],
    pathex=['../src'],
    binaries=[],
    datas=[],
    hiddenimports=['PySide6', 'openpyxl', 'reportlab', 'qrcode', 'PIL'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ChemWarehouse',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
