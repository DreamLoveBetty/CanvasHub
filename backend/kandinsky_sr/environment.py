"""Explicit preparation and readiness status for the isolated Kandinsky ImageSR 2.0 environment."""
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
from typing import Any, Dict, List, Optional

from ..app_config import APP_DATA_DIR
from ..local_image.downloads import DIRECT, download
from .contracts import ENGINE, MODEL_KEY, MODEL_LABEL, PREPARE_PREFIX, PYTHON_VERSION

REQUIREMENTS = Path(__file__).with_name("requirements.lock")
ASSETS_LOCK = Path(__file__).with_name("assets.lock.json")
SHARED_RECEIPTS = ("qwen21", "krea2", "moss")
GITHUB_RAW_URL = "https://raw.githubusercontent.com/{repo}/{revision}/{file}"
HF_URL = "https://huggingface.co/{repo}/resolve/{revision}/{file}"
_TOOL_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", str(Path.home() / ".local" / "bin"))


def component_root() -> Path:
    return APP_DATA_DIR / "components" / "kandinsky-sr"


def venv_python(root: Optional[Path] = None) -> Path:
    return Path(root or component_root()) / "venv" / "bin" / "python"


def src_dir(root: Optional[Path] = None) -> Path:
    return Path(root or component_root()) / "src"


def python_package_root(root: Optional[Path] = None) -> Path:
    return src_dir(root) / "src"


def default_model_dir(root: Optional[Path] = None) -> Path:
    return Path(root or component_root()) / "assets" / MODEL_KEY


def emit(stage: str, message: str, **extra: Any) -> None:
    payload = {"stage": stage, "message": message, **extra}
    print(PREPARE_PREFIX + json.dumps(payload, ensure_ascii=False), flush=True)


def load_assets() -> Dict[str, Any]:
    return json.loads(ASSETS_LOCK.read_text(encoding="utf-8"))


def pinned_packages(path: Path = REQUIREMENTS) -> Dict[str, str]:
    """{name: version} from the hash lock, with continuation lines skipped."""
    return dict(re.findall(r"^([A-Za-z0-9._-]+)==([^\s\\]+)", Path(path).read_text(encoding="utf-8"), re.M))


def read_receipt(root: Optional[Path] = None) -> Dict[str, Any]:
    try:
        value = json.loads((Path(root or component_root()) / "installed.json").read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def supported_platform() -> bool:
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Darwin":
        return machine == "arm64"
    return system in ("Linux", "Windows") and machine in ("x86_64", "amd64", "arm64", "aarch64")


def locate_tool(name: str) -> Optional[str]:
    candidates = [shutil.which(name)] + [str(Path(directory) / name) for directory in _TOOL_DIRS]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def launcher_python(components: Optional[Path] = None) -> Optional[Path]:
    """Interpreter that runs `prepare` (must import backend.*)."""
    if not getattr(sys, "frozen", False):
        return Path(sys.executable).absolute()
    base = Path(components or APP_DATA_DIR / "components")
    for name in SHARED_RECEIPTS:
        value = read_receipt(base / name).get("python")
        if isinstance(value, str) and Path(value).is_absolute() and Path(value).is_file():
            return Path(value)
    return None


def probe_packages(python: Path, expected: Dict[str, str]) -> List[str]:
    """Names whose installed version differs from the lock, read inside the isolated interpreter."""
    code = (
        "import importlib.metadata as m,json,sys\n"
        "def v(n):\n try: return m.version(n)\n except m.PackageNotFoundError: return None\n"
        "print(json.dumps([n for n,w in json.loads(sys.argv[1]).items() if v(n)!=w]))"
    )
    output = subprocess.check_output([str(python), "-I", "-c", code, json.dumps(expected)], text=True, timeout=30)
    return json.loads(output)


def _require_regular_file(directory: Path, rel_path: str) -> Path:
    candidate = (directory / rel_path).resolve()
    if not candidate.is_relative_to(directory) or not candidate.is_file() or candidate.is_symlink():
        raise ValueError(f"模型目录缺少必要文件: {rel_path}")
    return candidate


def validate_local_model_dir(path: Path) -> Path:
    """Validate a local Kandinsky ImageSR 2.0 Diffusers directory."""
    directory = Path(path).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError("指定的模型目录不存在")

    model_index = _require_regular_file(directory, "model_index.json")
    transformer_cfg_path = _require_regular_file(directory, "transformer/config.json")
    _require_regular_file(directory, "vae/config.json")
    _require_regular_file(directory, "vae/diffusion_pytorch_model.safetensors")

    try:
        index_meta = json.loads(model_index.read_text(encoding="utf-8"))
        transformer_cfg = json.loads(transformer_cfg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("模型配置文件无法读取") from exc

    if index_meta.get("_class_name") != "KandinskyImageSRPipeline":
        raise ValueError("模型索引不是 KandinskyImageSRPipeline")
    if transformer_cfg.get("_class_name") != "KandinskyImageSRBakedTransformer3DModel":
        raise ValueError("Transformer 配置不是 KandinskyImageSRBakedTransformer3DModel")

    shards_index = directory / "transformer" / "diffusion_pytorch_model.safetensors.index.json"
    single_weights = directory / "transformer" / "diffusion_pytorch_model.safetensors"
    if shards_index.is_file() and not shards_index.is_symlink():
        try:
            weight_map = json.loads(shards_index.read_text(encoding="utf-8")).get("weight_map") or {}
        except (OSError, ValueError) as exc:
            raise ValueError("Transformer 分片索引损坏") from exc
        shards = sorted(set(str(v) for v in weight_map.values()))
        if not shards:
            raise ValueError("Transformer 分片索引不包含分片记录")
        for shard in shards:
            _require_regular_file(directory, f"transformer/{shard}")
    elif not (single_weights.is_file() and not single_weights.is_symlink()):
        raise ValueError("Transformer 缺少 safetensors 权重文件")

    return directory


def resolve_model_dir(root: Optional[Path] = None) -> Path:
    receipt = read_receipt(root)
    bound = receipt.get("model_dir")
    if isinstance(bound, str) and bound.strip():
        return Path(bound)
    return default_model_dir(root)


def missing_source(root: Optional[Path] = None) -> List[str]:
    base = src_dir(root)
    missing: List[str] = []
    for rel, item in load_assets()["source"]["files"].items():
        target = base / rel
        if not target.is_file() or target.is_symlink() or target.stat().st_size != int(item["size"]):
            missing.append(rel)
    return missing


def missing_model_assets(root: Optional[Path] = None) -> List[str]:
    base = default_model_dir(root)
    missing: List[str] = []
    for rel, item in load_assets()["model"]["files"].items():
        target = base / rel
        if not target.is_file() or target.is_symlink() or target.stat().st_size != int(item["size"]):
            missing.append(rel)
    return missing


def download_bytes() -> int:
    assets = load_assets()
    src_total = sum(int(item["size"]) for item in assets["source"]["files"].values())
    model_total = sum(int(item["size"]) for item in assets["model"]["files"].values())
    return src_total + model_total


def status(root: Optional[Path] = None, *, probe=None) -> Dict[str, Any]:
    """Readiness and reasons for the UI, without exposing host filesystem paths."""
    probe = probe or probe_packages
    root = Path(root or component_root())
    reasons: List[str] = []
    if not supported_platform():
        reasons.append("当前系统架构不支持 Kandinsky SR 本地运行")
    receipt = read_receipt(root)
    python = venv_python(root)
    if not receipt:
        reasons.append("Kandinsky SR 环境尚未准备")
    elif not python.is_file():
        reasons.append("Kandinsky SR 隔离环境丢失")
    else:
        try:
            mismatched = probe(python, pinned_packages())
        except (OSError, ValueError, subprocess.SubprocessError):
            reasons.append("无法读取 Kandinsky SR 隔离环境")
        else:
            if mismatched:
                reasons.append(f"Kandinsky SR 依赖版本不符：{mismatched[0]}")
        miss_src = missing_source(root)
        if miss_src:
            reasons.append(f"Kandinsky SR 运行代码缺失：{miss_src[0]}")
        bound_model = receipt.get("model_dir")
        if isinstance(bound_model, str) and bound_model.strip():
            try:
                validate_local_model_dir(Path(bound_model))
            except ValueError as exc:
                reasons.append(f"已绑定本地模型无效：{exc}")
        else:
            miss_model = missing_model_assets(root)
            if miss_model:
                reasons.append(f"Kandinsky SR 模型文件缺失：{miss_model[0]}")

    return {
        "ready": not reasons,
        "reasons": reasons,
        "prepared_at": receipt.get("prepared_at"),
        "download_bytes": download_bytes(),
        "model_variant": receipt.get("model_variant") or MODEL_LABEL,
        "engine": ENGINE,
    }


def _create_venv(root: Path, uv: str, run) -> Path:
    (Path(root) / "installed.json").unlink(missing_ok=True)
    target = Path(root) / "venv"
    shutil.rmtree(target, ignore_errors=True)
    run([uv, "venv", "--no-config", "--python", PYTHON_VERSION, str(target)], check=True)
    run(
        [
            uv,
            "pip",
            "install",
            "--no-config",
            "--python",
            str(target / "bin" / "python"),
            "--require-hashes",
            "--no-deps",
            "-r",
            str(REQUIREMENTS),
        ],
        check=True,
    )
    return target / "bin" / "python"


def _fetch_file(fetch, urls, target: Path, item: Dict[str, Any], progress) -> None:
    kwargs: Dict[str, Any] = {"size": int(item["size"]), "progress": progress}
    if item.get("sha256"):
        kwargs["sha256_value"] = item["sha256"]
    elif item.get("blob_id"):
        kwargs["blob_id"] = item["blob_id"]
    for index, (url, proxies) in enumerate(urls):
        try:
            fetch(url, target, proxies=proxies, **kwargs)
            return
        except Exception as error:
            if index + 1 == len(urls):
                raise RuntimeError(f"{target.name} 下载失败：{str(error)[:200]}") from error


def _download_assets(root: Path, fetch, *, include_model: bool) -> None:
    assets = load_assets()
    source_meta = assets["source"]
    model_meta = assets["model"]
    total = sum(int(item["size"]) for item in source_meta["files"].values())
    if include_model:
        total += sum(int(item["size"]) for item in model_meta["files"].values())
    done = 0

    source_base = src_dir(root)
    for rel, item in source_meta["files"].items():
        target = source_base / rel
        emit("assets", f"下载运行代码 · {rel}", downloaded=done, total=total, file=rel)

        def report_src(position: int, _size: int, base: int = done, label: str = rel) -> None:
            emit("assets", f"下载运行代码 · {label}", downloaded=base + position, total=total, file=label)

        url = GITHUB_RAW_URL.format(repo=source_meta["repo"], revision=source_meta["revision"], file=rel)
        _fetch_file(fetch, [(url, None), (url, DIRECT)], target, item, report_src)
        done += int(item["size"])

    if not include_model:
        return

    model_base = default_model_dir(root)
    for rel, item in model_meta["files"].items():
        target = model_base / rel
        emit("assets", f"下载 {model_meta['repo']} · {rel}", downloaded=done, total=total, file=rel)

        def report_model(position: int, _size: int, base: int = done, label: str = rel) -> None:
            emit("assets", f"下载 {model_meta['repo']} · {label}", downloaded=base + position, total=total, file=label)

        url = HF_URL.format(repo=model_meta["repo"], revision=model_meta["revision"], file=rel)
        _fetch_file(fetch, [(url, None), (url, DIRECT)], target, item, report_model)
        done += int(item["size"])


def prepare(
    *,
    root: Optional[Path] = None,
    model_dir: Optional[str | Path] = None,
    skip_model: bool = False,
    uv: Optional[str] = None,
    run=subprocess.run,
    fetch=download,
    tool_locator=None,
) -> Dict[str, Any]:
    """User-triggered: build isolated venv, fetch pinned source + weights (or bind local dir), then write receipt."""
    tool_locator = tool_locator or locate_tool
    root = Path(root or component_root())
    if not supported_platform():
        raise RuntimeError("当前系统架构不支持 Kandinsky SR 本地运行")
    uv_bin = uv or tool_locator("uv")
    if not uv_bin:
        raise RuntimeError("未找到 uv，无法准备 Kandinsky SR 环境")

    if skip_model and model_dir is not None and str(model_dir).strip():
        raise ValueError("--skip-model 与 --model-dir 不能同时使用")

    bound_dir: Optional[Path] = None
    model_variant = MODEL_LABEL
    if model_dir is not None and str(model_dir).strip():
        bound_dir = validate_local_model_dir(Path(model_dir))
        model_variant = f"{MODEL_LABEL} (本地绑定)"

    root.mkdir(parents=True, exist_ok=True)
    with (root / ".install.lock").open("w", encoding="utf-8") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        emit("environment", f"创建隔离环境（Python {PYTHON_VERSION}）")
        created = _create_venv(root, uv_bin, run)
        _download_assets(root, fetch, include_model=(bound_dir is None and not skip_model))
        if skip_model:
            default_model_dir(root).mkdir(parents=True, exist_ok=True)
        receipt: Dict[str, Any] = {
            "schema_version": 1,
            "python": str(created),
            "prepared_at": int(time.time()),
            "versions": pinned_packages(),
            "model_variant": model_variant,
        }
        if bound_dir is not None:
            receipt["model_dir"] = str(bound_dir)
        pending = root / "installed.json.tmp"
        pending.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(pending, root / "installed.json")
    emit("complete", "Kandinsky SR 运行环境已就绪（请将模型权重放入默认目录）" if skip_model else "Kandinsky SR 环境已就绪")
    return status(root)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare the isolated Kandinsky ImageSR 2.0 environment")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    prep = commands.add_parser("prepare")
    prep.add_argument("--model-dir", default=None, help="Bind an existing local Kandinsky-ImageSR-2.0 directory")
    prep.add_argument("--skip-model", action="store_true", help="Prepare isolated venv and source without downloading model weights")
    args = parser.parse_args(argv)
    try:
        result = (
            prepare(model_dir=getattr(args, "model_dir", None), skip_model=bool(getattr(args, "skip_model", False)))
            if args.command == "prepare"
            else status()
        )
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        emit("failed", str(error)[:400])
        raise SystemExit(1) from error
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
