# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir build. UPX stays off: it breaks Qt and onnxruntime DLLs."""

from PyInstaller.utils.hooks import collect_all

datas = [("packaging/使用说明.txt", ".")]
binaries = []
hiddenimports = [
    "app",
    "core",
    "extraction",
    "batch_export",
    "template_io",
    "catalog_map",
    "catalog_defaults",
    "errors",
    "status_model",
    "unit_link",
    "rapidocr_onnxruntime",
    "onnxruntime",
    "cv2",
    "fitz",
    "PIL",
    "openpyxl",
    "numpy",
    "tools.offline_guard",
    "tools.smoke_batch",
    "tools.ocr_fields",
]

for package in (
    "rapidocr_onnxruntime",
    "onnxruntime",
    "cv2",
    "fitz",
    "PySide6",
    "shiboken6",
    "PIL",
    "numpy",
    "openpyxl",
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ArchiveDesk",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ArchiveDesk",
)
