# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for BlenderQueue.

Produces ``dist/BlenderQueue/BlenderQueue.exe`` plus its support files.

This is deliberately a one-folder build rather than a single file: a one-file
build unpacks ~46 MB into %TEMP% on every single launch, which Defender then
rescans, and startup drags on for a minute or more.  The folder build starts in
a couple of seconds.  ``install.bat`` copies the whole folder into
%LOCALAPPDATA%\\Programs, which is how most Windows apps install anyway.

The two Blender-side scripts ship as data so the app can hand their paths to
blender.exe at runtime; ``blenderqueue.blender.script_path`` finds them under
``scripts/``.
"""

block_cipher = None

# Qt modules PySide6 ships that this app never touches.  Excluding them keeps
# the build to a sane size.  Note that shiboken6 is PySide6's native binding
# layer and must never be excluded.
EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2", "PySide6.QtQml",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtBluetooth",
    "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSerialPort",
    "PySide6.QtSerialBus", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtHelp",
    "PySide6.QtScxml", "PySide6.QtSensors", "PySide6.QtStateMachine",
    "PySide6.QtHttpServer", "PySide6.QtNetworkAuth",
    "PySide6.QtDesigner", "PySide6.QtUiTools", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech", "PySide6.QtRemoteObjects",
    # scientific / packaging stacks that sometimes get pulled in transitively
    "numpy", "scipy", "pandas", "matplotlib", "PIL", "tkinter", "unittest",
    "pydoc_data", "setuptools", "pip", "distutils", "lib2to3", "test",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("blenderqueue/scripts/bq_inspect.py", "scripts"),
        ("blenderqueue/scripts/bq_render.py", "scripts"),
        ("blenderqueue/scripts/bq_analyze.py", "scripts"),
        ("assets/app.ico", "assets"),
    ],
    hiddenimports=["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
                   "shiboken6", "shiboken6.Shiboken"],
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
    name="BlenderQueue",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,               # GUI app: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/app.ico",
    version="version_info.txt",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="BlenderQueue",
)
