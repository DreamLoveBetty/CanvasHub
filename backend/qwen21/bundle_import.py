"""Import the pinned Qwen-Image-2.1-Turbo MLX bundle from a local download.

Operator action, run while no Qwen job is active (it refuses otherwise):

  python -m backend.qwen21.bundle_import --source <downloaded repo directory>
  python -m backend.qwen21.bundle_import --restore-text-encoder

Every used file is proven against the pinned revision before anything is
published. The distilled Transformer becomes its own Base (sampling=turbo-8);
its BF16 Heretic encoder replaces the shared 8-bit one in place (backup kept).
The bundle VAE/processor equal the shared ones and are not duplicated. Files
are APFS clones where possible, so the source download is never modified.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from ..app_config import APP_DATA_DIR
from ..local_image.downloads import sha256, verify
from . import text_encoder
from .contracts import TASK_TYPE, TERMINAL
from .model_store import BaseModelStore
from .profiles import TURBO_PRESET, TURBO_SIGMAS

BUNDLE = {"repo": "vanch007/Qwen-Image-2.1-Turbo-Heretic-mlx-bf16",
          "revision": "1ac68b7ede726b22ea3ace1fa6f03062450e4649"}
FILES = json.loads(Path(__file__).with_name("turbo_bundle_files.json").read_text())
MODEL_ID = "qwen-image-2.1-turbo-heretic-bf16"
MODEL_NAME = "Qwen-Image-2.1-Turbo-Heretic"
ENCODER = {"id": "heretic-bf16", "label": "Heretic · BF16", **BUNDLE}
# Restored language-model head: the pinned loader rejects it, images never use it.
GENERATION_HEAD = "generation_head.safetensors"
GENERATION_HEAD_KEYS = {"lm_head.weight", "language_model.norm.weight"}


def emit(message):
    print(message, flush=True)


def checksums(prefix):
    return {item["rfilename"]: item["lfs"]["sha256"] for item in FILES
            if item["rfilename"].startswith(prefix) and item.get("lfs")}


def verify_source(source):
    source = Path(source).expanduser().resolve()
    for item in FILES:
        emit("校验 " + item["rfilename"])
        if not verify(source / item["rfilename"], size=item["size"],
                      sha256_value=(item.get("lfs") or {}).get("sha256", ""), blob_id=item["blobId"]):
            raise RuntimeError(f"{item['rfilename']} 与固定版本 {BUNDLE['revision'][:12]} 不一致")
    sigmas = json.loads((source / "model_index.json").read_text()).get("sample_sigmas")
    if tuple(sigmas or ()) != TURBO_SIGMAS:
        raise RuntimeError("Turbo 采样节点与固定版本不一致")
    return source


def clone(source, destination):
    """APFS copy-on-write clone; ordinary copy on other filesystems."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if subprocess.run(["cp", "-c", str(source), str(destination)], capture_output=True).returncode:
        shutil.copyfile(source, destination)
    if destination.stat().st_size != source.stat().st_size:
        raise RuntimeError(f"{destination.name} 复制不完整")


def text_index(source):
    value = json.loads((source / "text_encoder/model.safetensors.index.json").read_text())
    weight_map = value["weight_map"]
    dropped = {key for key, shard in weight_map.items() if shard == GENERATION_HEAD}
    if dropped != GENERATION_HEAD_KEYS:
        raise RuntimeError("文本编码器索引结构与固定版本不符")
    value["weight_map"] = {key: shard for key, shard in weight_map.items() if shard != GENERATION_HEAD}
    return value


def import_transformer(store, source):
    store.paths()
    stage = store.staging / f"{MODEL_ID}-{uuid.uuid4().hex[:8]}"
    try:
        for item in FILES:
            name = item["rfilename"]
            if name.startswith("transformer/"):
                emit("复制 " + name)
                clone(source / name, stage / name)
        return store.publish_native(stage, model_id=MODEL_ID, name=MODEL_NAME, sampling=TURBO_PRESET,
                                    bundle=dict(BUNDLE), checksums=checksums("transformer/"))
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def import_text_encoder(store, source):
    shared = store.shared
    current = text_encoder.read(shared)
    if current is not None:
        if current.get("revision") != BUNDLE["revision"]:
            raise RuntimeError("已安装其他替换版文本编码器，请先还原")
        return text_encoder.public(shared)
    if not store.shared_ready():
        raise RuntimeError("共享组件校验未通过，保留现场")
    staging = shared / text_encoder.STAGING
    if staging.exists():
        shutil.rmtree(staging)
    names = [item["rfilename"] for item in FILES if item["rfilename"].startswith("text_encoder/")
             and not item["rfilename"].endswith("model.safetensors.index.json")]
    try:
        for name in names:
            emit("复制 " + name)
            clone(source / name, staging / Path(name).name)
        index = text_index(source)
        (staging / "model.safetensors.index.json").write_text(json.dumps(index, indent=2) + "\n")
        sums = {**checksums("text_encoder/"),
                text_encoder.INDEX: sha256(staging / "model.safetensors.index.json")}
        result = text_encoder.activate(shared, staging, identity=dict(ENCODER), checksums=sums)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    if not store.shared_ready():
        raise RuntimeError("替换后共享组件校验失败，请执行 --restore-text-encoder")
    return result


def active_tasks():
    from ..database import get_all_tasks
    return [task["task_id"] for task in get_all_tasks(limit=5000)
            if task.get("type") == TASK_TYPE and task.get("status") not in TERMINAL]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=APP_DATA_DIR / "data" / "qwen21")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--keep-text-encoder", action="store_true",
                        help="只导入 Turbo Transformer，不替换共享文本编码器")
    parser.add_argument("--restore-text-encoder", action="store_true")
    args = parser.parse_args(argv)
    if bool(args.source) == args.restore_text_encoder:
        parser.error("请指定 --source 或 --restore-text-encoder 其中之一")
    if active_tasks():
        raise RuntimeError("仍有 Qwen 任务在排队或运行，请完成后再操作")
    store = BaseModelStore(args.data / "assets", args.data)
    if args.restore_text_encoder:
        emit("已还原：" + json.dumps(text_encoder.restore(store.shared), ensure_ascii=False))
        return
    source = verify_source(args.source)
    model = import_transformer(store, source)
    emit("Base 已注册：" + json.dumps(model, ensure_ascii=False))
    if not args.keep_text_encoder:
        emit("文本编码器：" + json.dumps(import_text_encoder(store, source), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        emit("失败：" + str(exc)[:1600])
        raise SystemExit(1) from None
