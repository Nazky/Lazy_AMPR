# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ["worker_ampr_pack_profile.py"],
    pathex=["external/ampr_emu/tools"],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ampr_pack_profile", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="ampr_pack_profile")
