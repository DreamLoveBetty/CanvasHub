"""Prepare the pinned Krea 2 source adapter in the shared Canvas Python environment.

The upstream packages are kept as audited source trees and added to the worker's
PYTHONPATH. They are deliberately not installed as distributions because their
metadata caps MLX below the Canvas-wide mlx==0.32.2 profile.
"""
from __future__ import annotations

import argparse
import datetime
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

import requests

from .contracts import (BASE_REPO, BASE_REVISION, BUILDS, MFLUX_VERSION,
                        MFLUX_WHEEL_SHA256, REVISION, SAFETY_REPO, SAFETY_REVISION)
from .environment import (PROFILE, REQUIREMENTS, host_supported, model_paths, pins,
                          probe, profile_hash, source_paths, supported)


def emit(stage, message, **extra):
    print("KREA2_EVENT " + json.dumps({"stage": stage, "message": message, **extra}, ensure_ascii=False), flush=True)


def _token():
    try:
        from huggingface_hub import get_token
        return (get_token() or "").strip()
    except Exception:
        return str(os.environ.get("HF_TOKEN") or "").strip()


def prepare_source(root):
    root = Path(root)
    krea, mflux = source_paths(root)
    krea.parent.mkdir(parents=True, exist_ok=True)
    if not krea.exists():
        emit("source", "下载固定版本 Krea 2 MLX 源码")
        subprocess.run(["git", "init", str(krea)], check=True)
        subprocess.run(["git", "-C", str(krea), "remote", "add", "origin",
                        "https://github.com/avlp12/krea2_alis_mlx.git"], check=True)
    if not (krea / ".git").is_dir():
        raise RuntimeError("Krea 2 源码目录存在但不是 Git 仓库，已保留现场")
    try:
        remote = subprocess.check_output(
            ["git", "-C", str(krea), "remote", "get-url", "origin"], text=True,
            stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        try:
            subprocess.run(["git", "-C", str(krea), "rev-parse", "HEAD"], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            remote = "https://github.com/avlp12/krea2_alis_mlx.git"
            subprocess.run(["git", "-C", str(krea), "remote", "add", "origin", remote], check=True)
        else:
            raise RuntimeError("Krea 2 源码仓库缺少 origin，已保留现场") from None
    if remote.rstrip("/").removesuffix(".git") != "https://github.com/avlp12/krea2_alis_mlx":
        raise RuntimeError("Krea 2 源码仓库地址不符，已保留现场")
    try:
        head = subprocess.check_output(
            ["git", "-C", str(krea), "rev-parse", "HEAD"], text=True,
            stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        # A previous network interruption can leave a valid initialized repo
        # without a commit. Resume the immutable fetch rather than requiring a
        # user to remove internal component state by hand.
        subprocess.run(["git", "-C", str(krea), "fetch", "--depth", "1", "origin", REVISION], check=True)
        subprocess.run(["git", "-C", str(krea), "checkout", "--detach", REVISION], check=True)
        head = subprocess.check_output(["git", "-C", str(krea), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(krea), "status", "--porcelain"], text=True).strip()
    if head != REVISION or dirty:
        raise RuntimeError("Krea 2 组件源码版本不同或存在修改，已保留现场")

    if mflux.exists():
        try:
            if (mflux / ".mflux-version").read_text().strip() == MFLUX_VERSION:
                return
        except OSError:
            pass
        raise RuntimeError("mflux 组件源码版本不同，已保留现场")
    emit("source", f"准备 mflux {MFLUX_VERSION} 源码适配层")
    with tempfile.TemporaryDirectory(prefix="krea2-mflux-", dir=krea.parent) as temp_name:
        temp = Path(temp_name)
        subprocess.run([str(sys.executable), "-m", "pip", "download", "--no-deps", "--only-binary=:all:",
                        "--dest", str(temp), f"mflux=={MFLUX_VERSION}"], check=True)
        wheel, = temp.glob("mflux-*.whl")
        if hashlib.sha256(wheel.read_bytes()).hexdigest() != MFLUX_WHEEL_SHA256:
            raise RuntimeError("mflux wheel SHA-256 校验失败")
        stage = temp / "unpacked"
        with zipfile.ZipFile(wheel) as archive:
            stage_root = stage.resolve()
            for member in archive.infolist():
                target = (stage / member.filename).resolve()
                if target != stage_root and stage_root not in target.parents:
                    raise RuntimeError("mflux wheel 包含非法路径")
            archive.extractall(stage)
        (stage / ".mflux-version").write_text(MFLUX_VERSION + "\n", encoding="utf-8")
        stage.rename(mflux)


def install_dependencies(root, python, uv):
    info = probe(python)
    if not supported(info):
        raise RuntimeError("请选择原生 Apple Silicon Python 3.14 虚拟环境（默认使用画布主 .venv）")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    log_dir = Path(root) / "install-records" / stamp
    log_dir.mkdir(parents=True, exist_ok=False)
    before = subprocess.check_output([str(python), "-m", "pip", "freeze", "--all"], text=True)
    (log_dir / "before.txt").write_text(before, encoding="utf-8")
    versions = subprocess.check_output([str(python), "-c",
        'import importlib.metadata as m; print("\\n".join(sorted(d.metadata["Name"]+"=="+d.version for d in m.distributions())))'], text=True)
    constraints = log_dir / "constraints.txt"
    constraints.write_text(versions, encoding="utf-8")
    command = [uv, "pip", "install", "--no-config", "--python", str(python),
               "--constraint", str(constraints), "-r", str(REQUIREMENTS)]
    emit("environment", "检查共享 Python 依赖，不允许降级现有组件")
    with (log_dir / "dry-run.txt").open("w") as output:
        subprocess.run(command + ["--dry-run"], check=True, stdout=output)
    with (log_dir / "install.txt").open("w") as output:
        subprocess.run(command, check=True, stdout=output)
    with (log_dir / "pip-check.txt").open("w") as output:
        subprocess.run([uv, "pip", "check", "--python", str(python)], check=True, stdout=output)
    with (log_dir / "after.txt").open("w") as output:
        subprocess.run([str(python), "-m", "pip", "freeze", "--all"], check=True, stdout=output)
    return probe(python), log_dir


def _auth_headers():
    token = _token()
    return {"Authorization": f"Bearer {token}"} if token else {}


def download_file(repo, revision, filename, destination, *, expected_size=0, expected_sha256=""):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://huggingface.co/{repo}/resolve/{revision}/{filename}"
    auth = _auth_headers()
    total = int(expected_size or 0)
    try:
        head = requests.head(url, headers=auth, allow_redirects=True, timeout=30)
        if head.status_code in (401, 403):
            raise RuntimeError(f"Hugging Face 拒绝访问 {repo}；请先接受模型条款并登录")
        head.raise_for_status()
        total = total or int(head.headers.get("content-length") or 0)
    except RuntimeError:
        raise
    except Exception:
        if not destination.is_file():
            raise
    if destination.is_file() and (not total or destination.stat().st_size == total):
        if expected_sha256:
            emit("verify", f"校验 {filename}")
            digest = hashlib.sha256()
            with destination.open("rb") as stream:
                for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != expected_sha256:
                raise RuntimeError(f"{filename} SHA-256 校验失败，保留文件供检查")
        return destination
    part = destination.with_suffix(destination.suffix + ".part")
    position = part.stat().st_size if part.exists() else 0
    if total and position > total:
        raise RuntimeError(f"{filename} 的断点文件大于远端文件，保留现场供检查")
    headers = {**auth, **({"Range": f"bytes={position}-"} if position else {})}
    emit("download", f"下载 {filename}", file=filename, downloaded=position, total=total)
    with requests.get(url, headers=headers, stream=True, timeout=(30, 180), allow_redirects=True) as response:
        if response.status_code in (401, 403):
            raise RuntimeError(f"Hugging Face 拒绝访问 {repo}；请先接受模型条款并登录")
        response.raise_for_status()
        resume = bool(position and response.status_code == 206)
        if not resume:
            position = 0
        received = position
        next_report = received
        with part.open("ab" if resume else "wb") as stream:
            for chunk in response.iter_content(4 * 1024 * 1024):
                if not chunk:
                    continue
                stream.write(chunk)
                received += len(chunk)
                if received >= next_report:
                    emit("download", f"下载 {filename}", file=filename, downloaded=received, total=total)
                    next_report = received + 64 * 1024 * 1024
    if total and received != total:
        raise RuntimeError(f"{filename} 下载不完整：{received}/{total}")
    os.replace(part, destination)
    return download_file(repo, revision, filename, destination,
                         expected_size=expected_size, expected_sha256=expected_sha256)


def _repo_files(repo, revision, patterns):
    from huggingface_hub import HfApi
    info = HfApi().model_info(repo, revision=revision, token=_token() or None, files_metadata=True)
    result = []
    for sibling in info.siblings:
        name = sibling.rfilename
        if any(fnmatch.fnmatch(name, pattern) for pattern in patterns):
            lfs = getattr(sibling, "lfs", None)
            result.append((name, int(sibling.size or 0), str(getattr(lfs, "sha256", "") or "")))
    if not result:
        raise RuntimeError(f"{repo} 没有匹配的模型文件")
    return sorted(result)


def prepare_models(root, selected, *, include_safety=True):
    root = Path(root)
    paths = model_paths(root)
    records = {}
    # Resolve the gated base repository first.  This fails quickly when the
    # signed-in account has not accepted the license instead of downloading a
    # 10–14 GB public transformer that cannot yet be used.
    base_patterns = ["model_index.json", "vae/*.safetensors", "vae/*.json",
                     "text_encoder/*.safetensors", "text_encoder/*.json",
                     "tokenizer/*.json", "tokenizer/*.jinja", "tokenizer/*.txt", "tokenizer/*.model"]
    base_files = _repo_files(BASE_REPO, BASE_REVISION, base_patterns)
    for name, size, sha256 in base_files:
        download_file(BASE_REPO, BASE_REVISION, name, paths["base"] / name,
                      expected_size=size, expected_sha256=sha256)
    records["base"] = {"repo": BASE_REPO, "revision": BASE_REVISION,
                       "files": [{"name": name, "size": size, **({"sha256": sha256} if sha256 else {})}
                                 for name, size, sha256 in base_files]}
    if include_safety:
        safety_patterns = ["*.safetensors", "*.json"]
        safety_files = _repo_files(SAFETY_REPO, SAFETY_REVISION, safety_patterns)
        for name, size, sha256 in safety_files:
            download_file(SAFETY_REPO, SAFETY_REVISION, name, paths["safety"] / name,
                          expected_size=size, expected_sha256=sha256)
        records["safety"] = {"repo": SAFETY_REPO, "revision": SAFETY_REVISION,
                             "files": [{"name": name, "size": size, **({"sha256": sha256} if sha256 else {})}
                                       for name, size, sha256 in safety_files]}
    for precision in selected:
        build = BUILDS[precision]
        target = paths[precision]
        download_file(build["repo"], build["repo_revision"], build["filename"], target,
                      expected_size=build["size"], expected_sha256=build["sha256"])
        records[precision] = {"repo": build["repo"], "revision": build["repo_revision"],
                              "file": str(target.relative_to(root)), "size": target.stat().st_size,
                              "sha256": build["sha256"]}
    return records


def install(root, python, uv, selected, *, include_safety=True):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if not host_supported():
        raise RuntimeError("Krea 2 MLX 需要 Apple Silicon macOS")
    prepare_source(root)
    info, log_dir = install_dependencies(root, python, uv)
    existing = {}
    try:
        existing = json.loads((root / "installed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    models = dict(existing.get("models") or {})
    # Even `--models none` prepares the shared gated VAE/text encoder (and the
    # optional safety model).  Converted custom transformers reuse those shared
    # components without downloading another built-in transformer artifact.
    models.update(prepare_models(root, selected, include_safety=include_safety))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    receipt = {"revision": REVISION, "mflux_version": MFLUX_VERSION, "profile": PROFILE,
               "profile_sha256": profile_hash(), "python": str(python), "prefix": info["prefix"],
               "python_version": info["version"], "models": models, "installed_at": stamp,
               "last_install_record": str(log_dir.relative_to(root))}
    pending = root / "installed.json.tmp"
    pending.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(pending, root / "installed.json")
    emit("done", "Krea 2 共享环境与模型准备完成")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", choices=("none", "8bit", "mixed-4-8", "all"), default="8bit")
    parser.add_argument("--skip-safety", action="store_true",
                        help="不下载可选的 NSFW 安全分类模型")
    default_python = (Path(sys.executable) if sys.prefix != sys.base_prefix else
                      Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python")
    parser.add_argument("--python", type=Path, default=default_python)
    args = parser.parse_args()
    uv = shutil.which("uv")
    if not uv:
        parser.error("未找到 uv")
    from ..app_config import APP_DATA_DIR
    root = (APP_DATA_DIR / "components" / "krea2").resolve()
    selected = [] if args.models == "none" else list(BUILDS) if args.models == "all" else [args.models]
    import fcntl
    root.mkdir(parents=True, exist_ok=True)
    with (root / "install.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("另一个 Krea 2 安装器正在运行")
        try:
            install(root, args.python.expanduser().absolute(), uv, selected,
                    include_safety=not args.skip_safety)
        except Exception as exc:
            emit("failed", str(exc)[:1000])
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()
