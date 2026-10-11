"""Prepare Qwen sources/models in the existing interpreter, without pip edits."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.parse import quote

from ..app_config import APP_DATA_DIR
from ..local_image.downloads import download
from .contracts import (DEFAULT_MODEL_ID, MODEL_REPO, MODEL_REVISION, REVISION,
                        TURBO_REPO)
from .profiles import ADAPTERS, DEFAULT_PRESET, canonical_preset
from .environment import environment_ready, source_path, turbo_path
from .source_adapter import TARGETS, apply as apply_source_adapter, recognized
from .model_store import BaseModelStore, shared_model_file
from . import text_encoder

PREFIX = "QWEN21_EVENT "
FILES = json.loads(Path(__file__).with_name("model_files.json").read_text())


def emit(stage, message, **extra):
    print(PREFIX + json.dumps({"stage": stage, "message": message, **extra}, ensure_ascii=False), flush=True)


def prepare_source(component):
    source = source_path(component)
    source.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        subprocess.run(["git", "clone", "--filter=blob:none", "--no-checkout",
                        "https://github.com/mflux-community/mflux.git", str(source)], check=True)
        # A --no-checkout clone has deleted files in its worktree status, not
        # user edits. Materialize the pin before applying the dirty-tree gate.
        subprocess.run(["git", "-C", str(source), "fetch", "origin", REVISION], check=True)
        subprocess.run(["git", "-C", str(source), "checkout", "--detach", REVISION], check=True)
    if not (source / ".git").is_dir():
        raise RuntimeError("Qwen 源码目录不是 Git 仓库，保留现场")
    remote = subprocess.check_output(["git", "-C", str(source), "remote", "get-url", "origin"], text=True).strip()
    if remote.rstrip("/").removesuffix(".git") != "https://github.com/mflux-community/mflux":
        raise RuntimeError("Qwen 源码仓库地址不符，保留现场")
    head = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"], text=True).splitlines()
    if dirty and not (head == REVISION and set(dirty).issubset({f" M {x}" for x in TARGETS}) and recognized(source)):
        raise RuntimeError("Qwen 源码存在非预期修改，保留现场")
    if head != REVISION:
        subprocess.run(["git", "-C", str(source), "fetch", "origin", REVISION], check=True)
        subprocess.run(["git", "-C", str(source), "checkout", "--detach", REVISION], check=True)
    emit("source", "应用 Qwen 独立 Viggle / 参考图适配")
    return apply_source_adapter(source)


def _headers(endpoint):
    # Credentials stay server-side and are never sent to a third-party mirror.
    if endpoint.rstrip("/") != "https://huggingface.co":
        return {}
    try:
        from huggingface_hub import get_token
        token = get_token()
        return {"Authorization": f"Bearer {token}"} if token else {}
    except Exception:
        return {}


def prepare_model(data, endpoint, *, shared_only=False):
    store = BaseModelStore(Path(data) / "assets", Path(data))
    shared_only = shared_only or store.builtin_removed
    destination = Path(data) / "assets" / "base_models" / DEFAULT_MODEL_ID
    # A verified BF16 encoder replacement is kept; an invalid record raises here.
    replaced = text_encoder.read(destination) is not None
    files = [item for item in FILES if (not shared_only or shared_model_file(item["rfilename"]))
             and not (replaced and item["rfilename"].startswith("text_encoder/"))]
    destination.mkdir(parents=True, exist_ok=True)
    total = sum(item["size"] for item in files)
    remaining = total - sum(min((destination / x["rfilename"]).stat().st_size, x["size"])
                            for x in files if (destination / x["rfilename"]).is_file())
    import shutil
    if shutil.disk_usage(destination).free < max(0, remaining) + 2 * 1024**3:
        raise RuntimeError("Qwen 模型目录空间不足")
    progress_by_file, verified = {}, {}
    lock = threading.Lock()

    def fetch(item):
        filename = item["rfilename"]
        path = destination / filename
        expected_sha = (item.get("lfs") or {}).get("sha256", "")

        def progress(done, size):
            with lock:
                progress_by_file[filename] = done
                emit("download", "准备 Qwen 2.1 共享组件" if shared_only else "下载 Qwen 2.1 完整模型", file=filename,
                     downloaded=sum(progress_by_file.values()), total=total)
        url = f"{endpoint}/{MODEL_REPO}/resolve/{MODEL_REVISION}/{quote(filename, safe='/')}"
        download(url, path, size=item["size"], sha256_value=expected_sha,
                 blob_id=item.get("blobId", ""), progress=progress, headers=_headers(endpoint))
        stat = path.stat()
        with lock:
            progress_by_file[filename] = item["size"]
            verified[filename] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                                  "sha256": expected_sha, "blob_id": item.get("blobId", "")}
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(fetch, files))
    manifest = {"schema_version": 1, "id": DEFAULT_MODEL_ID,
                "name": "Qwen-Image-2.1-Heretic-mlx-8bit", "architecture": "qwen-image-2.1",
                "precision": "8bit", "builtin": True, "reference_capable": True,
                "repo": MODEL_REPO, "repo_revision": MODEL_REVISION,
                "created_at": int(time.time()), "verified_files": verified,
                "file_size": total, "validation": {"checksums": True}}
    # A shared-only repair never overwrites the complete Transformer receipt.
    if not shared_only:
        pending = destination / ".manifest.json.tmp"
        pending.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        pending.replace(destination / "manifest.json")
    manifest.update(shared_only=True, verified_files={name: proof for name, proof in verified.items()
                                                     if shared_model_file(name)})
    manifest["file_size"] = sum(proof["size"] for proof in manifest["verified_files"].values())
    pending = destination / ".shared-manifest.json.tmp"
    pending.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    pending.replace(destination / ".shared-manifest.json")
    return destination


def prepare_turbo(component, endpoint, preset=DEFAULT_PRESET):
    preset = canonical_preset(preset)
    adapter = ADAPTERS[preset]
    filename = adapter["filename"]
    return download(f"{endpoint}/{TURBO_REPO}/resolve/{adapter['revision']}/{quote(filename)}",
                    turbo_path(component, preset), size=adapter["size"], sha256_value=adapter["sha256"],
                    headers=_headers(endpoint), progress=lambda done, total: emit(
                        "turbo", "下载 " + adapter["label"], downloaded=done, total=total))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--component", type=Path, default=APP_DATA_DIR / "components" / "qwen21")
    parser.add_argument("--data", type=Path, default=APP_DATA_DIR / "data" / "qwen21")
    parser.add_argument("--sources-only", action="store_true")
    parser.add_argument("--shared-only", action="store_true")
    parser.add_argument("--turbo", action="store_true")
    parser.add_argument("--turbo-preset", choices=list(ADAPTERS), default=DEFAULT_PRESET)
    parser.add_argument("--endpoint", default=os.environ.get("HF_ENDPOINT", "https://huggingface.co"))
    args = parser.parse_args(argv)
    endpoint = args.endpoint.rstrip("/")
    if endpoint not in {"https://huggingface.co", "https://hf-mirror.com"}:
        raise ValueError("Qwen 固定版本下载仅支持 Hugging Face 或 hf-mirror.com")
    ready, reasons = environment_ready(Path(sys.executable))
    if not ready:
        raise RuntimeError("；".join(reasons))
    emit("environment", "共享依赖检查通过，不修改主环境")
    patch_hash = prepare_source(args.component)
    if not args.sources_only:
        prepare_model(args.data, endpoint, shared_only=args.shared_only)
        if args.turbo:
            prepare_turbo(args.component, endpoint, args.turbo_preset)
    receipt = {"revision": REVISION, "patch_sha256": patch_hash,
               "python": str(Path(sys.executable).absolute()), "prepared_at": int(time.time()),
               "profile": "shared-cpython314-mlx0322-qwen21-v1"}
    path = args.component / "installed.json"
    pending = path.with_suffix(".json.tmp")
    pending.write_text(json.dumps(receipt, indent=2) + "\n")
    pending.replace(path)
    emit("done", "Qwen 2.1 准备完成")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        emit("failed", str(exc)[:1600])
        raise SystemExit(1) from None
