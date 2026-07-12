# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules


PROJECT_ROOT = Path(SPECPATH).resolve().parents[1]
ENTRYPOINT = PROJECT_ROOT / "packaging" / "upscale" / "upscale_worker_entry.py"

hiddenimports = sorted(set(
    collect_submodules("torch")
    + collect_submodules("torchvision")
    + collect_submodules("spandrel")
    + collect_submodules("PIL")
    + ["numpy"]
))

datas = collect_data_files("torch") + collect_data_files("torchvision") + collect_data_files("spandrel")
binaries = collect_dynamic_libs("torch") + collect_dynamic_libs("torchvision")

a = Analysis(
    [str(ENTRYPOINT)],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["fastapi", "uvicorn", "curl_cffi"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="upscale-worker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="upscale-worker",
)
