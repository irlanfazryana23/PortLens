# -*- mode: python ; coding: utf-8 -*-
# Build with build.ps1 (or: python -m PyInstaller PortLens.spec).
# The exe name and Windows file version both come from the VERSION file.

import os
import sys

ROOT = os.path.abspath(SPECPATH)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import make_version_info  # noqa: E402

with open(os.path.join(ROOT, 'VERSION'), encoding='utf-8') as fh:
    VERSION = fh.read().strip()
EXE_NAME = f'PortLens-{VERSION}'

# Generated into build/ (ignored by Git). PyInstaller's --clean step runs before
# this spec executes, so the file is not removed again.
BUILD_DIR = os.path.join(ROOT, 'build')
os.makedirs(BUILD_DIR, exist_ok=True)
VERSION_FILE = os.path.join(BUILD_DIR, 'version_info.txt')
with open(VERSION_FILE, 'w', encoding='utf-8') as fh:
    fh.write(make_version_info.render(VERSION, EXE_NAME + '.exe'))

a = Analysis(
    [os.path.join(ROOT, 'portlens.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'assets', 'portlens.ico'), '.'),
        (os.path.join(ROOT, 'assets', 'portlens_logo.png'), '.'),
        (os.path.join(ROOT, 'VERSION'), '.'),
    ],
    hiddenimports=[],
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
    name=EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX-packed exes are flagged by antivirus far more often
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(ROOT, 'assets', 'portlens.ico')],
    version=VERSION_FILE,
)
