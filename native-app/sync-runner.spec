# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for building the bundled sync executable.

Run from the native-app/ directory (the build scripts do this automatically):

  pyinstaller sync-runner.spec \\
    --distpath python-bin \\
    --workpath build/pyinstaller \\
    --clean --noconfirm

The output is placed in native-app/python-bin/sync (macOS/Linux) or
native-app/python-bin/sync.exe (Windows).

electron-builder then picks up the python-bin/ directory via the
extraResources config in package.json and embeds it in the final installer.
"""

import os
import sys

# Path to the Python source package (repo root / src/)
_here = os.path.abspath(os.path.dirname(SPEC))          # native-app/
_src  = os.path.abspath(os.path.join(_here, '..', 'src'))  # repo/src/

block_cipher = None

a = Analysis(
    ['python-bridge/sync_runner.py'],
    pathex=[_src],
    binaries=[],
    datas=[],
    hiddenimports=[
        'scouting_db',
        'scouting_db.api',
        'scouting_db.db',
        'scouting_db.native_sync',
        # click is a runtime dependency (imported transitively)
        'click',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Exclude heavy packages that are not needed
    excludes=[
        'tkinter', 'matplotlib', 'numpy', 'pandas',
        'scipy', 'PIL', 'PyQt5', 'wx',
    ],
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
    name='sync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # console=True so the Electron main process can capture stdout/stderr
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
