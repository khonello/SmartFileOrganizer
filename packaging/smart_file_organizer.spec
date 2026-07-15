# PyInstaller spec skeleton for Smart File Organizer.
#
# SKELETON -- NOT YET VERIFIED. This has never produced a working build: the
# GUI is still a stub (gui/main_window.py raises NotImplementedError), so the
# frozen exe cannot open a window and the build cannot be smoke-tested. See
# PACKAGING.md for what is guesswork and what is grounded.
#
# Build (from the repo root, once PyInstaller is a dev dependency):
#     environ\Scripts\python.exe -m PyInstaller packaging/smart_file_organizer.spec
#
# Output lands in dist/ and build/ at the repo root (both already gitignored).

import os

# SPECPATH is injected by PyInstaller and points at this file's directory.
PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821

block_cipher = None


# -- data files --------------------------------------------------------------
# (source_on_disk, destination_dir_inside_the_bundle)
#
# rules/presets must keep its relative layout: rule_loader resolves presets via
#     PRESETS_DIR = Path(__file__).parent / "presets"
# which under a freeze evaluates to <bundle>/rules/presets. The mapping below is
# what makes that path real.
datas = [
    (os.path.join(PROJECT_ROOT, "rules", "presets"), "rules/presets"),
    (os.path.join(PROJECT_ROOT, "config"), "config"),
]


# -- imports -----------------------------------------------------------------
# PySide6 ships PyInstaller hooks, so Qt itself needs no hidden imports.
# These cover the metadata extractors' optional deps: core/metadata.py imports
# them lazily and swallows ImportError, so if they ever move to an
# importlib-style lookup PyInstaller's static analysis will miss them and the
# extractors will silently degrade to {} in the frozen build. Listed defensively.
hiddenimports = [
    "PIL.Image",
    "PIL.ExifTags",
    "PyPDF2",
    "mutagen",
]

# Trim the Qt surface to what a QWidgets app uses. Each of these is dead weight
# for this app, and QtWebEngineCore alone is a ~130 MB swing.
# NOTE: unverified -- confirm the app still starts after excluding these.
excludes = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtSerialPort",
    "PySide6.QtPositioning",
    "PySide6.QtSql",  # history/ uses stdlib sqlite3, not QtSql
    "PySide6.QtTest",
    # Dev-only tooling that must never reach a user machine.
    "pytest",
    "ruff",
    "tkinter",
]


a = Analysis(  # noqa: F821
    [os.path.join(PROJECT_ROOT, "main.py")],
    pathex=[PROJECT_ROOT],  # flat layout: top-level modules live at the root
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821


# -- one-dir build (recommended -- see PACKAGING.md "One-file vs one-dir") ----
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SmartFileOrganizer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX + Qt DLLs is a known source of corrupt builds
    console=False,  # GUI app: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="packaging/app.ico",  # TODO: no app icon exists yet (no visual design)
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SmartFileOrganizer",
)
