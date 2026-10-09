"""Read-only shared-interpreter and Qwen-specific source checks, without MLX."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

from .contracts import REVISION
from .profiles import ADAPTERS, DEFAULT_PRESET, canonical_preset
from .source_adapter import TARGETS, ready as adapter_ready

REQUIRED = {"mlx": "0.32.2", "numpy": "2.3.3", "transformers": "5.10.4",
            "huggingface-hub": "1.31.0", "pillow": "12.3.0", "safetensors": "0.7.0",
            "torch": "2.14.0", "mlx-lm": "0.31.3"}


def read_receipt(root):
    try:
        value = json.loads((Path(root) / "installed.json").read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def shared_python(receipt=None):
    if not getattr(sys, "frozen", False):
        return Path(sys.executable).absolute()
    value = (receipt or {}).get("python")
    return Path(value) if isinstance(value, str) and Path(value).is_absolute() else None


def environment_ready(python):
    if python is None or not python.is_file():
        return False, ["未找到画布共享 Python 环境"]
    code = '''import importlib.metadata as m,json,sys,platform
expected=json.loads(sys.argv[1]); missing=[]
for name,wanted in expected.items():
    try: actual=m.version(name)
    except m.PackageNotFoundError: actual=None
    if actual != wanted: missing.append(name)
print(json.dumps(dict(missing=missing, supported=platform.system()=="Darwin" and
 platform.machine()=="arm64" and sys.version_info[:2]==(3,14) and sys.prefix!=sys.base_prefix)))
'''
    try:
        value = json.loads(subprocess.check_output([str(python), "-c", code, json.dumps(REQUIRED)],
                                                  text=True, timeout=20))
        reasons = []
        if not value.get("supported"):
            reasons.append("Qwen 2.1 需要 Apple Silicon macOS 的共享 Python 3.14 环境")
        if value.get("missing"):
            reasons.append("共享依赖版本不匹配：" + ", ".join(value["missing"]))
        return not reasons, reasons
    except (OSError, ValueError, subprocess.SubprocessError):
        return False, ["无法检查共享 Python 环境"]


def source_path(root):
    return Path(root) / "source" / "mflux"


def source_ready(root):
    source = source_path(root)
    if not adapter_ready(source):
        return False
    try:
        head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                       text=True, timeout=5).strip()
        dirty = subprocess.check_output(["git", "-C", str(source), "diff", "--name-only", "HEAD"],
                                        text=True, timeout=5).splitlines()
        return head == REVISION and dirty == sorted(TARGETS)
    except (OSError, subprocess.SubprocessError):
        return False


def turbo_path(root, preset=DEFAULT_PRESET):
    return Path(root) / "adapters" / ADAPTERS[canonical_preset(preset)]["filename"]


def turbo_ready(root, preset=DEFAULT_PRESET):
    preset = canonical_preset(preset)
    if preset not in ADAPTERS:
        return False
    path = turbo_path(root, preset)
    try:
        return path.is_file() and not path.is_symlink() and path.stat().st_size == ADAPTERS[preset]["size"]
    except OSError:
        return False
