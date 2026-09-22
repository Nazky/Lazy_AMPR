# -*- mode: python ; coding: utf-8 -*-
import os
import sys

sys.path.insert(0, SPECPATH)
from version import VERSION

is_windows = sys.platform == "win32"
is_darwin = sys.platform == "darwin"

# macOS signing. Empty/unset means ad-hoc ("-"). build_macos.sh reads the same
# variables so the PyInstaller signature and the post-build re-sign agree.
codesign_identity = os.environ.get("LAZY_AMPR_CODESIGN_IDENTITY") or None
entitlements_file = os.environ.get("LAZY_AMPR_ENTITLEMENTS") or None

# Optional application icon. No logo exists yet (see README TODO); dropping
# resources/icon.icns into the repo enables it without touching this file.
icon_file = os.path.join(SPECPATH, "resources", "icon.icns")
if not os.path.isfile(icon_file):
    icon_file = None

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
    # PyInstaller only applies UPX on Windows; keep it off explicitly on macOS
    # because packed Mach-O binaries cannot be code signed.
    upx=not is_darwin,
    console=False,
    uac_admin=is_windows,
    disable_windowed_traceback=False,
    version="version_info.txt" if is_windows else None,
    codesign_identity=codesign_identity,
    entitlements_file=entitlements_file,
    icon=icon_file,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=not is_darwin,
    upx_exclude=[],
    name="Lazy_AMPR",
)

if is_darwin:
    # CFBundleShortVersionString/CFBundleVersion must be dotted numerics; drop
    # any "-rcN" suffix that version.py allows.
    plist_version = VERSION.split("-")[0]
    app = BUNDLE(
        coll,
        name="Lazy_AMPR.app",
        icon=icon_file,
        bundle_identifier="com.nazky.lazyampr",
        version=plist_version,
        info_plist={
            "CFBundleDisplayName": "Lazy AMPR",
            "CFBundleShortVersionString": plist_version,
            "CFBundleVersion": plist_version,
            # PySide6 6.10 wheels are tagged macosx_13_0.
            "LSMinimumSystemVersion": "13.0",
            "NSHighResolutionCapable": True,
            "NSPrincipalClass": "NSApplication",
            "NSRequiresAquaSystemAppearance": False,
            "LSApplicationCategoryType": "public.app-category.utilities",
            "NSHumanReadableCopyright": "MIT License",
        },
    )
