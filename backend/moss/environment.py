"""Explicit preparation and status of the isolated MOSS environment; never runs implicitly."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

from ..app_config import APP_DATA_DIR
from ..local_image.downloads import download
from .assets import load_lock
from .contracts import DEFAULT_MODEL_ID
from .model_store import STUDENT_LOCATIONS, ModelStore

PREFIX = "MOSS_EVENT "
REQUIREMENTS = Path(__file__).with_name("requirements.lock")
SHARED_RECEIPTS = ("qwen21", "krea2")
HF_URL = "https://huggingface.co/{repo}/resolve/{revision}/{file}"


def component_root():
    return APP_DATA_DIR / "components" / "moss"


def state_root():
    return APP_DATA_DIR / "data" / "moss"


def assets_dir(root=None):
    return Path(root or component_root()) / "assets"


def venv_python(root=None):
    return Path(root or component_root()) / "venv" / "bin" / "python"


def emit(stage, message, **extra):
    print(PREFIX + json.dumps({"stage": stage, "message": message, **extra}, ensure_ascii=False), flush=True)


def pinned_packages(path=REQUIREMENTS):
    """{name: version} from the hash lock, with continuation lines skipped."""
    return dict(re.findall(r"^([A-Za-z0-9._-]+)==([^\s\\]+)", Path(path).read_text(encoding="utf-8"), re.M))


def read_receipt(root=None):
    try:
        value = json.loads((Path(root or component_root()) / "installed.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def supported_platform():
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def base_python(components=None):
    """Interpreter for `uv venv`: this one when not frozen, otherwise a shared Python recorded by a receipt."""
    if not getattr(sys, "frozen", False):
        return Path(sys.executable).absolute()
    for name in SHARED_RECEIPTS:
        value = read_receipt(Path(components or APP_DATA_DIR / "components") / name).get("python")
        if isinstance(value, str) and Path(value).is_absolute() and Path(value).is_file():
            return Path(value)
    return None


def probe_packages(python, expected):
    """Names whose installed version differs from the lock, read inside the isolated interpreter."""
    code = ("import importlib.metadata as m,json,sys\n"
            "def v(n):\n try: return m.version(n)\n except m.PackageNotFoundError: return None\n"
            "print(json.dumps([n for n,w in json.loads(sys.argv[1]).items() if v(n)!=w]))")
    return json.loads(subprocess.check_output([str(python), "-I", "-c", code, json.dumps(expected)],
                                              text=True, timeout=30))


def status(root=None, *, probe=probe_packages):
    """Readiness and reasons for the UI, without paths, tokens or model imports."""
    root = Path(root or component_root())
    reasons = []
    if not supported_platform():
        reasons.append("MOSS 仅支持 Apple Silicon macOS")
    receipt = read_receipt(root)
    python = venv_python(root)
    if not receipt:
        reasons.append("MOSS 环境尚未准备")
    elif not python.is_file():
        reasons.append("MOSS 隔离环境丢失")
    else:
        try:
            mismatched = probe(python, pinned_packages())
        except (OSError, ValueError, subprocess.SubprocessError):
            reasons.append("无法读取 MOSS 隔离环境")
        else:
            if mismatched:
                reasons.append(f"MOSS 依赖版本不符：{mismatched[0]}")
    return {"ready": not reasons, "reasons": reasons, "prepared_at": receipt.get("prepared_at"),
            "versions": receipt.get("versions", {})}


def _create_venv(root, uv, python, run):
    # A venv records its own prefix, so it is built in place; the receipt is gone until this one is complete.
    (Path(root) / "installed.json").unlink(missing_ok=True)
    target = Path(root) / "venv"
    shutil.rmtree(target, ignore_errors=True)
    run([uv, "venv", "--no-config", "--python", str(python), str(target)], check=True)
    run([uv, "pip", "install", "--no-config", "--python", str(target / "bin" / "python"),
         "--require-hashes", "-r", str(REQUIREMENTS)], check=True)
    return target / "bin" / "python"


def _download_assets(root, source, fetch):
    lock, target = load_lock(), assets_dir(root)
    for name, item in lock["configs"]["files"].items():
        emit("assets", f"下载配置 {name}")
        entry = {"repo": lock["configs"]["repo"], "revision": lock["configs"]["revision"], "file": name}
        fetch(HF_URL.format(**entry), target / "configs" / name, size=item["size"], sha256_value=item["sha256"])
    student_present = source and any((Path(source) / name).is_file() for name in STUDENT_LOCATIONS)
    for key, item in lock["managed"].items():
        if key == "student" and student_present:
            continue
        emit("assets", f"下载受管适配器 {key}")
        fetch(HF_URL.format(**item), target / Path(item["file"]).name, size=item["size"], sha256_value=item["sha256"])


def prepare(*, root=None, source=None, uv=None, python=None, run=subprocess.run, fetch=download):
    """User-triggered: build the venv, fetch pinned small assets, then write the receipt last."""
    root = Path(root or component_root())
    if not supported_platform():
        raise RuntimeError("MOSS 仅支持 Apple Silicon macOS")
    uv = uv or shutil.which("uv")
    if not uv:
        raise RuntimeError("未找到 uv，无法准备 MOSS 环境")
    python = python or base_python()
    if python is None or not Path(python).is_file():
        raise RuntimeError("未找到共享 Python，无法准备 MOSS 环境")
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".install.lock").open("w") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        emit("environment", "创建隔离环境")
        created = _create_venv(root, uv, python, run)
        _download_assets(root, source, fetch)
        receipt = {"schema_version": 1, "python": str(created), "base_python": str(python),
                   "prepared_at": int(time.time()), "versions": pinned_packages()}
        pending = root / "installed.json.tmp"
        pending.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(pending, root / "installed.json")
    emit("complete", "MOSS 环境已就绪")
    return status(root)


def bind(source, *, root=None, state=None):
    return ModelStore(state or state_root(), assets_dir(root)).bind(source, DEFAULT_MODEL_ID)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare the isolated MOSS environment")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("prepare").add_argument("--source")
    commands.add_parser("bind").add_argument("source")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(source=args.source)
        elif args.command == "bind":
            emit("bind", "校验 MOSS 权重，约需数分钟")
            result = bind(args.source)
        else:
            result = status()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        emit("failed", str(error)[:400])
        raise SystemExit(1) from error
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
