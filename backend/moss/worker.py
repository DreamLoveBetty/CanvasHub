"""Persistent MOSS worker in the isolated venv. Sampling stays upstream; heavy imports happen only in MlxBackend."""
from __future__ import annotations

import gc
import json
import os
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.moss import lora_adapter, prompt_cache
from backend.moss.contracts import ENGINE, WORKER_PREFIX
from backend.moss.native_adapter import BRIDGE_VERSION, make_pipeline
from backend.moss.tokenizer_probe import count_tokens

# (group, adapter dtype), in the order every validated render applied them.
MANAGED = {"destripe": "bfloat16", "student": "float32"}
ORDINARY_GROUP = "ordinary"
ORDINARY_DTYPE = "float16"


def emit(event, **extra):
    print(WORKER_PREFIX + json.dumps({"event": event, **extra}, ensure_ascii=False), flush=True)


class Cancelled(Exception):
    pass


def sampler_request(spec):
    """Keyword arguments of upstream's Request; the sampler itself is never reimplemented here."""
    sampler = spec["sampler"]
    common = {"prompt": spec["prompt"], "negative_prompt": sampler["negative_prompt"], "width": spec["width"],
              "height": spec["height"], "seed": spec["seed"], "uncond_skip_layers": sampler["uncond_skip_layers"],
              "max_sequence_length": sampler["max_sequence_length"]}
    if sampler["name"] == "author_hybrid_turbo":
        return {**common, "steps": sampler["training_steps"], "guidance": float(sampler["teacher_cfg"]),
                "shift": float(sampler["training_shift"]), "turbo": True}
    return {**common, "steps": sampler["steps"], "guidance": float(sampler["cfg"]), "shift": float(sampler["shift"]),
            "turbo": False}


def prepare_loras(spec):
    """Normalize ordinary LoRAs first; one failure fails the job instead of silently dropping that LoRA."""
    prepared = []
    for item in spec["loras"]:
        try:
            path = lora_adapter.prepare(item["path"], item["asset_id"], spec["lora_cache"])
        except (OSError, ValueError) as error:
            raise RuntimeError(f"准备LoRA失败（{item.get('name') or item['asset_id'][:12]}）：{error}") from error
        prepared.append((str(path), float(item["scale"])))
    return prepared


def adapter_stack(spec, prepared):
    """(path, strength, dtype name, group). Ordinary LoRAs share a group the student switch never touches."""
    scales = {item["id"]: float(item["scale"]) for item in spec["managed_adapters"]}
    stack = [(spec["model"][name], scales[name], dtype, name) for name, dtype in MANAGED.items() if name in scales]
    return stack + [(path, scale, ORDINARY_DTYPE, ORDINARY_GROUP) for path, scale in prepared]


def effective_parameters(spec, tokens):
    """What actually ran, for the job record. Carries no local path."""
    return {"engine": ENGINE, "model_id": spec["model"]["id"], "model_fingerprint": spec["model"]["fingerprint"],
            "bridge": BRIDGE_VERSION, "preset": spec["preset"], "sampler": spec["sampler"],
            "width": spec["width"], "height": spec["height"], "seed": spec["seed"],
            "managed_adapters": spec["managed_adapters"], "prompt_tokens": tokens[0], "negative_tokens": tokens[1],
            "loras": [{"asset_id": item["asset_id"], "scale": item["scale"],
                       "converter": lora_adapter.CONVERTER_VERSION} for item in spec["loras"]]}


def run_job(request, backend):
    started = time.monotonic()
    directory, spec = Path(request["job_dir"]).resolve(), request["spec"]
    cancel = Path(request["cancel_file"])

    def checkpoint():
        if cancel.exists():
            raise Cancelled()

    checkpoint()
    if spec["loras"]:
        emit("progress", ratio=0.02, stage="准备LoRA")
    prepared = prepare_loras(spec)
    checkpoint()
    max_tokens = spec["sampler"]["max_sequence_length"]
    negative_text = spec["sampler"]["negative_prompt"]
    tokenizer = backend.tokenizer(spec["model"]["view"])
    expected = [count_tokens(tokenizer, text) for text in (spec["prompt"], negative_text)]
    if max(expected) > max_tokens:
        raise ValueError(f"提示词超过 {max_tokens} token 上限")
    emit("progress", ratio=0.05, stage="编码提示词")
    # The binding fingerprint covers encoder, tokenizer, template, bridge and configs, so any change is a new cache.
    cache_root = Path(spec["prompt_cache"])
    pipe = backend.pipeline(spec["model"]["view"], cache_root / spec["model"]["fingerprint"][:16],
                            adapter_stack(spec, prepared))
    entries = prompt_cache.touch(pipe.cache, [spec["prompt"], negative_text], max_tokens)
    positive, negative = backend.encode(pipe, [spec["prompt"], negative_text], max_tokens)
    if [positive.shape[1], negative.shape[1]] != expected:
        raise RuntimeError("提示词编码长度与 token 预检不一致，任务已中止")
    checkpoint()

    def on_step(index, total):
        checkpoint()
        emit("progress", ratio=round(0.15 + 0.75 * (index + 1) / total, 4), stage=f"采样 {index + 1}/{total}")

    emit("progress", ratio=0.15, stage="载入模型")
    denoise_started = time.monotonic()
    latents = pipe.denoise(backend.request(sampler_request(spec)), positive, negative, on_step=on_step)
    denoise_seconds = time.monotonic() - denoise_started
    checkpoint()
    emit("progress", ratio=0.92, stage="解码图像")
    image = pipe.decode(latents)
    output = directory / "output.png"
    backend.save_png(image, output)
    prompt_cache.evict(cache_root, keep=entries)
    return {"paths": [str(output)], "seed": spec["seed"], "effective": effective_parameters(spec, expected),
            "generation_timing": {"schema_version": 1, "local_inference": True,
                                  "denoise_seconds": round(denoise_seconds, 3),
                                  "total_seconds": round(time.monotonic() - started, 3)}}


class MlxBackend:
    """Everything that touches MLX; created on the first job, so an idle worker start stays light."""

    def __init__(self):
        import mlx.core as mx
        from moss_image_mlx.pipeline import Request
        from PIL import Image
        from transformers import AutoTokenizer

        if not mx.metal.is_available():
            raise RuntimeError("MOSS 需要 Metal GPU")
        mx.set_default_device(mx.gpu)
        self.mx, self.request_type, self.image, self.tokenizer_type = mx, Request, Image, AutoTokenizer
        self.tokenizers = {}

    def tokenizer(self, view):
        path = str(Path(view) / "tokenizer")
        if path not in self.tokenizers:
            self.tokenizers = {path: self.tokenizer_type.from_pretrained(path, local_files_only=True)}
        return self.tokenizers[path]

    def pipeline(self, view, cache_dir, stack):
        loras = [(path, strength, getattr(self.mx, dtype), group) for path, strength, dtype, group in stack]
        return make_pipeline(view, cache_dir, loras)

    def encode(self, pipe, prompts, max_tokens):
        embeddings = pipe.encode(prompts, max_tokens)
        self.mx.eval(*embeddings)
        return embeddings

    def request(self, kwargs):
        return self.request_type(**kwargs)

    def save_png(self, image, path):
        pending = path.with_name(path.name + ".pending")
        self.image.fromarray(image).save(pending, format="PNG")
        os.replace(pending, path)

    def release(self):
        gc.collect()
        self.mx.clear_cache()


def serve(lines, make_backend=MlxBackend):
    backend = None
    for line in lines:
        try:
            request = json.loads(line)
        except ValueError:
            continue
        if request.get("command") == "shutdown":
            return
        if request.get("command") != "generate":
            continue
        job_id = str(request.get("job_id") or "")
        try:
            backend = backend or make_backend()
            emit("result", job_id=job_id, **run_job(request, backend))
        except Cancelled:
            emit("cancelled", job_id=job_id, message="任务已取消")
        except Exception as error:
            traceback.print_exc()
            emit("error", job_id=job_id, message=str(error)[:1600])
        finally:
            if backend:
                backend.release()


def main():
    from backend.local_image.parent_watch import start_parent_watch

    start_parent_watch()
    serve(sys.stdin)


if __name__ == "__main__":
    main()
