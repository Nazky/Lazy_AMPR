# -*- mode: python ; coding: utf-8 -*-
import sys

is_windows = sys.platform == "win32"

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("resources/fakelib/libSceAmpr.sprx", "resources/fakelib"),
        ("toml_profiles", "toml_profiles"),
        ("external/ampr_emu/LICENSE", "licenses"),
        ("external/ampr_emu/third_party/lz4/LICENSE", "licenses/lz4"),
    ],
    hiddenimports=["FATtools.Volume"],
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
    [],
    exclude_binaries=True,
    name="Lazy_AMPR",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    uac_admin=is_windows,
    disable_windowed_traceback=False,
    version="version_info.txt" if is_windows else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Lazy_AMPR",
)
