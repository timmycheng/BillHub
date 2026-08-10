# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

rapidocr_datas = collect_data_files('rapidocr_onnxruntime')
rapidocr_binaries = collect_dynamic_libs('rapidocr_onnxruntime')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=rapidocr_binaries,
    datas=[('templates', 'templates')] + rapidocr_datas,
    hiddenimports=['PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets', 'pymupdf', 'openpyxl', 'rapidocr_onnxruntime', 'onnxruntime', 'rapidocr_onnxruntime.ch_ppocr_v3_det.text_detect', 'rapidocr_onnxruntime.ch_ppocr_v2_cls.text_cls', 'rapidocr_onnxruntime.ch_ppocr_v3_rec.text_recognize'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WZBill',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
