"""Explicit preparation and status of the isolated ASR environment; never runs implicitly.

`prepare` (run as `python -m backend.asr.environment prepare` by the settings center) builds
components/asr/venv from the hash lock with uv (Python 3.12, `--no-deps`: the lock pins every
runtime import, so qwen-asr's demo dependencies stay out), downloads the pinned model files into
components/asr/assets/<model>/ and writes installed.json last. Model files come from ModelScope
(direct, at a pinned revision) and fall back to Hugging Face (through the configured proxy); both
serve the same bytes, checked by size and sha256 before a file is kept.
"""
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
from ..local_image.downloads import DIRECT, download
from .contracts import PYTHON_VERSION

PREFIX = "ASR_PREPARE "
REQUIREMENTS = Path(__file__).with_name("requirements.lock")
ASSETS_LOCK = Path(__file__).with_name("assets.lock.json")
SHARED_RECEIPTS = ("qwen21", "krea2", "moss")
MODELSCOPE_URL = "https://www.modelscope.cn/models/{repo}/resolve/{revision}/{file}"
HF_URL = "https://huggingface.co/{repo}/resolve/{revision}/{file}"


def component_root():
    return APP_DATA_DIR / "components" / "asr"


def assets_dir(root=None):
    return Path(root or component_root()) / "assets"


def model_dir(key, root=None):
    return assets_dir(root) / key


def venv_python(root=None):
    return Path(root or component_root()) / "venv" / "bin" / "python"


def emit(stage, message, **extra):
    print(PREFIX + json.dumps({"stage": stage, "message": message, **extra}, ensure_ascii=False), flush=True)


def load_assets():
    return json.loads(ASSETS_LOCK.read_text(encoding="utf-8"))


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


def launcher_python(components=None):
    """Interpreter that runs `prepare` (it imports backend.*): this one when not frozen, otherwise a
    shared Python recorded by another component's receipt."""
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


def missing_assets(root=None):
    """Model files that are absent or of the wrong size (hashes were checked when downloaded)."""
    missing = []
    for key, model in load_assets()["models"].items():
        for name, item in model["files"].items():
            path = model_dir(key, root) / name
            if not path.is_file() or path.stat().st_size != item["size"]:
                missing.append(f"{key}/{name}")
    return missing


def download_bytes():
    return sum(item["size"] for model in load_assets()["models"].values() for item in model["files"].values())


def status(root=None, *, probe=probe_packages):
    """Readiness and reasons for the UI, without paths or model imports."""
    root = Path(root or component_root())
    reasons = []
    if not supported_platform():
        reasons.append("语音识别仅支持 Apple Silicon macOS")
    receipt = read_receipt(root)
    python = venv_python(root)
    if not receipt:
        reasons.append("语音识别环境尚未准备")
    elif not python.is_file():
        reasons.append("语音识别隔离环境丢失")
    else:
        try:
            mismatched = probe(python, pinned_packages())
        except (OSError, ValueError, subprocess.SubprocessError):
            reasons.append("无法读取语音识别隔离环境")
        else:
            if mismatched:
                reasons.append(f"语音识别依赖版本不符：{mismatched[0]}")
        missing = missing_assets(root)
        if missing:
            reasons.append(f"语音识别模型文件缺失：{missing[0]}")
    return {"ready": not reasons, "reasons": reasons, "prepared_at": receipt.get("prepared_at"),
            "download_bytes": download_bytes()}


def _create_venv(root, uv, run):
    # A venv records its own prefix, so it is built in place; the receipt is gone until this one is complete.
    (Path(root) / "installed.json").unlink(missing_ok=True)
    target = Path(root) / "venv"
    shutil.rmtree(target, ignore_errors=True)
    run([uv, "venv", "--no-config", "--python", PYTHON_VERSION, str(target)], check=True)
    run([uv, "pip", "install", "--no-config", "--python", str(target / "bin" / "python"),
         "--require-hashes", "--no-deps", "-r", str(REQUIREMENTS)], check=True)
    return target / "bin" / "python"


def _download_assets(root, fetch):
    """Every pinned file, ModelScope first, Hugging Face second; a partial file resumes across sources."""
    total, done = download_bytes(), 0
    for key, model in load_assets()["models"].items():
        for name, item in model["files"].items():
            target = model_dir(key, root) / name
            emit("assets", f"下载 {model['repo']} · {name}", downloaded=done, total=total, file=name)

            def report(position, _size, base=done):
                emit("assets", f"下载 {model['repo']} · {name}", downloaded=base + position, total=total, file=name)

            sources = [(MODELSCOPE_URL.format(repo=model["repo"], revision=item["modelscope_revision"], file=name), DIRECT),
                       (HF_URL.format(repo=model["repo"], revision=model["huggingface_revision"], file=name), None)]
            for index, (url, proxies) in enumerate(sources):
                try:
                    fetch(url, target, size=item["size"], sha256_value=item["sha256"], progress=report, proxies=proxies)
                    break
                except Exception as error:  # the last source's error is the one the user sees
                    if index + 1 == len(sources):
                        raise RuntimeError(f"{name} 下载失败：{str(error)[:200]}") from error
                    emit("assets", f"ModelScope 下载失败，改用 Hugging Face：{name}", downloaded=done, total=total, file=name)
            done += item["size"]


def prepare(*, root=None, uv=None, run=subprocess.run, fetch=download):
    """User-triggered: build the venv, fetch the pinned models, then write the receipt last."""
    root = Path(root or component_root())
    if not supported_platform():
        raise RuntimeError("语音识别仅支持 Apple Silicon macOS")
    uv = uv or shutil.which("uv")
    if not uv:
        raise RuntimeError("未找到 uv，无法准备语音识别环境")
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".install.lock").open("w") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        emit("environment", f"创建隔离环境（Python {PYTHON_VERSION}）")
        created = _create_venv(root, uv, run)
        _download_assets(root, fetch)
        receipt = {"schema_version": 1, "python": str(created), "prepared_at": int(time.time()),
                   "versions": pinned_packages()}
        pending = root / "installed.json.tmp"
        pending.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(pending, root / "installed.json")
    emit("complete", "语音识别环境已就绪")
    return status(root)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare the isolated ASR environment")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("prepare")
    args = parser.parse_args(argv)
    try:
        result = prepare() if args.command == "prepare" else status()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        emit("failed", str(error)[:400])
        raise SystemExit(1) from error
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
