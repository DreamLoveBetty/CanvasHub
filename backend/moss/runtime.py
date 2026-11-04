"""MOSS adapter over the neutral worker supervisor. The HTTP process never imports MLX."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import threading
import time

from ..local_image.runtime import JsonLineRuntime, LocalImageCancelled, LocalImageError
from . import environment
from .contracts import ENGINE, MAX_TOKENS, WORKER_PREFIX

PROBE = Path(__file__).with_name("tokenizer_probe.py")
PROBE_TIMEOUT = 60
STATUS_TTL = 30


class MossError(LocalImageError):
    pass


class MossCancelled(LocalImageCancelled, MossError):
    pass


def worker_spec(job, model, loras, prompt, *, state_root):
    """Server-side worker input. `loras` holds (path, public) from LoRAStore.resolve, in job order."""
    scales = {item["asset_id"]: item["scale"] for item in job["loras"]}
    return {"prompt": prompt, "width": job["width"], "height": job["height"], "seed": job["seed"],
            "preset": job["preset"], "sampler": job["sampler"], "managed_adapters": job["managed_adapters"],
            "model": {"id": model.model_id, "view": str(model.view_path), "student": str(model.student_path),
                      "destripe": str(model.destripe_path), "fingerprint": model.fingerprint},
            "loras": [{"asset_id": public["asset_id"], "name": public.get("name", ""), "path": str(path),
                       "scale": scales[public["asset_id"]]} for path, public in loras],
            "lora_cache": str(Path(state_root) / "cache" / "lora"),
            "prompt_cache": str(Path(state_root) / "cache" / "prompt-embeds")}


class Runtime(JsonLineRuntime):
    def __init__(self, component, *, model_store=None, worker=None, timeout=3600, idle_seconds=600, before_load=None):
        super().__init__(component, worker=worker or Path(__file__).with_name("worker.py"), label="MOSS",
                         prefix=WORKER_PREFIX, error=MossError, cancelled_error=MossCancelled,
                         before_load=before_load, timeout=timeout, idle_seconds=idle_seconds)
        self.model_store = model_store
        self._status_lock = threading.Lock()
        self._status_cache = (0.0, None)

    @property
    def python(self):
        value = environment.read_receipt(self.root).get("python")
        return Path(value) if isinstance(value, str) and Path(value).is_absolute() else None

    def child_environment(self):
        project = Path(__file__).resolve().parents[2]
        cache = self.root / "cache"
        return {**os.environ, "PYTHONPATH": str(project), "HF_HOME": str(cache / "huggingface"),
                "MOSS_MLX_CACHE": str(cache), "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "TOKENIZERS_PARALLELISM": "false", "PYTHONUNBUFFERED": "1"}

    def invalidate_status(self):
        with self._status_lock:
            self._status_cache = (0.0, None)

    def status(self):
        with self._status_lock:
            checked, cached = self._status_cache
            if cached is None or time.monotonic() - checked > STATUS_TTL:
                cached = environment.status(self.root)
                self._status_cache = (time.monotonic(), cached)
        with self._lock:
            warm = bool(self._process and self._process.poll() is None)
        return {**cached, "engine": ENGINE, "warm": warm, "offline_inference": True}

    def _tokenizer_path(self):
        if not environment.read_receipt(self.root) or self.python is None or not self.python.is_file():
            raise ValueError("MOSS 环境尚未准备")
        if self.model_store is None:
            raise ValueError("MOSS 模型尚未绑定")
        return self.model_store.resolve().view_path / "tokenizer"

    def inspect_prompt(self, prompt, negative_prompt="", max_sequence_length=MAX_TOKENS):
        """Exact token budget without loading a model or taking the GPU lease. Unchecked is never a pass."""
        result = {"checked": False, "valid": None, "prompt_tokens": None, "negative_tokens": None,
                  "max_tokens": max_sequence_length, "reason": None}
        try:
            tokenizer = self._tokenizer_path()
        except ValueError as error:
            return {**result, "reason": str(error)}
        try:
            output = subprocess.run([str(self.python), "-I", str(PROBE)], text=True, capture_output=True, check=True,
                                    input=json.dumps({"tokenizer": str(tokenizer),
                                                      "texts": [prompt, negative_prompt]}, ensure_ascii=False),
                                    env=self.child_environment(), timeout=PROBE_TIMEOUT)
            positive, negative = json.loads(output.stdout.strip().splitlines()[-1])["counts"]
        except (OSError, ValueError, IndexError, KeyError, TypeError, subprocess.SubprocessError):
            return {**result, "reason": "token 检查失败"}
        valid = positive <= max_sequence_length and negative <= max_sequence_length
        return {**result, "checked": True, "valid": valid, "prompt_tokens": positive, "negative_tokens": negative,
                "reason": None if valid else f"{'提示词' if positive > max_sequence_length else '负面提示词'}超过 {max_sequence_length} token 上限"}
