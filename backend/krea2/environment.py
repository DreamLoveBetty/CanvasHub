"""Shared-interpreter and installed-component checks without importing MLX."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

from .contracts import BUILDS, MFLUX_VERSION, REVISION


PROFILE = "cpython314-mlx0322-krea2-v1"
REQUIREMENTS = Path(__file__).with_name("requirements-py314.txt")


def pins():
    return dict(line.split("==", 1) for line in REQUIREMENTS.read_text().splitlines()
                if line and not line.startswith("#"))


def profile_hash():
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def read_receipt(root):
    try:
        result = json.loads((Path(root) / "installed.json").read_text(encoding="utf-8"))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def shared_python(receipt=None):
    if getattr(sys, "frozen", False):
        value = (receipt or {}).get("python")
        return Path(value) if isinstance(value, str) and Path(value).is_absolute() else None
    return Path(sys.executable).absolute()


def source_paths(root):
    source = Path(root) / "source"
    return source / "krea2", source / "mflux"


def source_ready(root):
    krea, mflux = source_paths(root)
    if not (krea / "krea2" / "pipeline.py").is_file() or not (mflux / "mflux" / "__init__.py").is_file():
        return False
    try:
        head = subprocess.check_output(["git", "-C", str(krea), "rev-parse", "HEAD"], text=True, timeout=5).strip()
        version = (mflux / ".mflux-version").read_text().strip()
        return head == REVISION and version == MFLUX_VERSION
    except (OSError, subprocess.SubprocessError):
        return False


def probe(python):
    expected = {**pins(), "mlx": "0.32.2", "numpy": "2.3.3", "transformers": "5.10.4",
                "huggingface-hub": "1.31.0", "pillow": "12.3.0"}
    code = '''import importlib.metadata as m,json,platform,sys
expected=json.loads(sys.argv[1]); missing=[]
for name, version in expected.items():
    try: actual=m.version(name)
    except m.PackageNotFoundError: actual=None
    if actual != version: missing.append(dict(name=name, expected=version, actual=actual))
print(json.dumps(dict(version=list(sys.version_info[:3]),prefix=sys.prefix,
    virtualenv=sys.prefix != sys.base_prefix,system=platform.system(),machine=platform.machine(),missing=missing)))
'''
    result = subprocess.run([str(python), "-c", code, json.dumps(expected)], capture_output=True,
                            text=True, check=True, timeout=15)
    return json.loads(result.stdout)


def supported(info):
    return (info.get("version", [])[:2] == [3, 14] and info.get("virtualenv")
            and info.get("system") == "Darwin" and info.get("machine") == "arm64")


def environment_ready(python):
    if python is None or not python.is_file():
        return False, ["未找到画布共享 Python 环境"]
    try:
        info = probe(python)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False, ["无法检查画布共享 Python 环境"]
    reasons = []
    if not supported(info):
        reasons.append("Krea 2 需要 Apple Silicon macOS 的 Python 3.14 虚拟环境")
    if info.get("missing"):
        reasons.append("共享环境依赖版本未就绪")
    return not reasons, reasons


def model_paths(root):
    root = Path(root)
    cache = root / "cache" / "krea2_alis_mlx"
    result = {}
    for precision, build in BUILDS.items():
        result[precision] = cache / build["repo"].replace("/", "__") / build["filename"]
    result["base"] = cache / "krea__Krea-2-Turbo"
    result["safety"] = cache / "Falconsai__nsfw_image_detection"
    return result


def build_ready(root, precision):
    path = model_paths(root)[precision]
    build = BUILDS[precision]
    try:
        return path.is_file() and path.stat().st_size == build["size"]
    except OSError:
        return False


def base_ready(root):
    base = model_paths(root)["base"]
    return ((base / "model_index.json").is_file()
            and any((base / "vae").glob("*.safetensors"))
            and any((base / "text_encoder").glob("*.safetensors"))
            and (base / "tokenizer" / "tokenizer_config.json").is_file())


def safety_ready(root):
    path = model_paths(root)["safety"]
    return path.is_dir() and any(path.glob("*.safetensors")) and any(path.glob("*.json"))


def host_supported():
    return platform.system() == "Darwin" and platform.machine() == "arm64"
