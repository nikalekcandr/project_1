# -*- mode: python ; coding: utf-8 -*-
# Сборка: pyinstaller MindForge.spec --noconfirm
#   по умолчанию — один переносимый файл dist/MindForge.exe;
#   MINDFORGE_ONEDIR=1 — папка dist/MindForge/ (быстрый старт, используется инсталлятором).
import os

ONEDIR = os.environ.get("MINDFORGE_ONEDIR") == "1"

# Крупные модули Qt, которые приложению не нужны.
EXCLUDES = [
    "tkinter",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtWebView", "PySide6.QtHttpServer",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.Qt3DExtras", "PySide6.Qt3DAnimation", "PySide6.QtQuick3D",
    "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2", "PySide6.QtQml",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtGraphsWidgets",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSerialBus", "PySide6.QtPositioning",
    "PySide6.QtLocation", "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine",
    "PySide6.QtSpatialAudio", "PySide6.QtVirtualKeyboard", "PySide6.QtDesigner", "PySide6.QtUiTools",
    "PySide6.QtHelp", "PySide6.QtSql", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtNetworkAuth", "PySide6.QtCanvasPainter",
]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=["PySide6.QtSvg", "PySide6.QtTextToSpeech", "PySide6.QtTest"],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

common = dict(
    name="MindForge",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icon.ico",
    version="assets/version_info.txt",
)

if ONEDIR:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="MindForge")
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], runtime_tmpdir=None, **common)
