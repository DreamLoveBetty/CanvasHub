# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules


PROJECT_ROOT = Path(SPECPATH).resolve().parents[1]
ENTRYPOINT = PROJECT_ROOT / "packaging" / "pyinstaller" / "runtime_entry.py"
CODEX_SCRIPT_DIR = PROJECT_ROOT / "backend" / "codex_image_runtime" / "scripts"

hiddenimports = sorted(set(
    collect_submodules("backend")
    + collect_submodules("sidecars.chatgpt_pool")
    + collect_submodules("uvicorn")
    + collect_submodules("fastapi")
    + collect_submodules("starlette")
    + collect_submodules("PIL")
    + [
        "curl_cffi.requests",
        "chat",
        "codex_api",
        "edit_image",
        "fitz",
        "generate_image",
    ]
))

datas = collect_data_files("certifi") + collect_data_files("curl_cffi")
binaries = collect_dynamic_libs("curl_cffi")

a = Analysis(
    [str(ENTRYPOINT)],
    pathex=[str(PROJECT_ROOT), str(CODEX_SCRIPT_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "numpy",
        "spandrel",
        "torch",
        "torchvision",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="canvashub-runtime",
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
    name="canvashub-runtime",
)
