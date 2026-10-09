# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules


PROJECT_ROOT = Path(SPECPATH).resolve().parents[1]
ENTRYPOINT = PROJECT_ROOT / "packaging" / "pyinstaller" / "runtime_entry.py"
CODEX_SCRIPT_DIR = PROJECT_ROOT / "backend" / "codex_image_runtime" / "scripts"

hiddenimports = sorted(set(
    collect_submodules("backend")
    + collect_submodules("sidecars.chatgpt_pool")
    + collect_submodules("sidecars.google_pool")
    + ["sidecars.account_service"]
    + collect_submodules("uvicorn")
    + collect_submodules("fastapi")
    + collect_submodules("starlette")
    + collect_submodules("PIL")
    + collect_submodules("websocket")
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
# The optional MLX environment executes this file, not the frozen server binary.
datas += [(str(PROJECT_ROOT / "backend" / "audio" / "worker.py"), "backend/audio")]
datas += [(str(PROJECT_ROOT / "backend" / "audio" / "requirements-py314.txt"), "backend/audio")]
datas += [(str(PROJECT_ROOT / "backend" / "audio" / "vendor" / name), "backend/audio/vendor")
          for name in ("LICENSE.mlx-Yue", "NOTICE.md")]
# Krea 2 also executes in the shared, non-frozen Python environment.  Keep its
# process entrypoint and dependency profile beside the frozen backend modules.
datas += [(str(PROJECT_ROOT / "backend" / "krea2" / "worker.py"), "backend/krea2")]
datas += [(str(PROJECT_ROOT / "backend" / "krea2" / "edit_mlx.py"), "backend/krea2")]
datas += [(str(PROJECT_ROOT / "backend" / "krea2" / "edit_profile.py"), "backend/krea2")]
datas += [(str(PROJECT_ROOT / "backend" / "krea2" / "vendor" / name), "backend/krea2/vendor")
          for name in ("LICENSE.comfyui-krea2edit", "LICENSE.kinomlx", "NOTICE.md")]
datas += [(str(PROJECT_ROOT / "backend" / "krea2" / "converter_worker.py"), "backend/krea2")]
datas += [(str(PROJECT_ROOT / "backend" / "krea2" / "comfy_fp8.py"), "backend/krea2")]
datas += [(str(PROJECT_ROOT / "backend" / "krea2" / "requirements-py314.txt"), "backend/krea2")]
# Non-frozen shared-Python children must also see their relative helper imports.
# These are application source/config/licensing files, never runtime weights.
datas += collect_data_files("backend", include_py_files=True, includes=[
    "__init__.py", "app_config.py", "runtime_resources.py", "services/__init__.py",
    "services/generation_timing.py", "local_image/*.py", "krea2/*.py", "qwen21/*.py",
    "qwen21/*.json", "qwen21/vendor/*",
])
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
