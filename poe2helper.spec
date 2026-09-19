# -*- mode: python ; coding: utf-8 -*-
"""Сборка PyInstaller: папка dist/PoE2Helper с PoE2Helper.exe внутри."""

import os
import sys

block_cipher = None

ROOT = os.path.abspath(os.getcwd())
ICON = os.path.join(ROOT, "resources", "icon.ico")

# Всё лишнее из Qt выкидываем — иначе папка распухает до полугигабайта.
EXCLUDES = [
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtSerialPort",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtUiTools",
    # ВНИМАНИЕ: shiboken6 и shiboken6.Shiboken исключать нельзя — это ядро
    # привязки PySide6 к Qt, без него не импортируется ни один модуль Qt.
    "tkinter",
    "unittest",
    "pydoc_data",
    "email.test",
    "test",
    "distutils",
    "setuptools",
    "pip",
    "numpy",
    "PIL",
]

a = Analysis(
    ["src/poe2helper/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=[(ICON, "resources")],
    hiddenimports=["poe2helper"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PoE2Helper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=ICON if os.path.exists(ICON) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PoE2Helper",
)
