"""Persistent Qwen MLX worker. Heavy imports occur here, never in the server."""
from __future__ import annotations

import gc
import json
import os
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.qwen21.contracts import REVISION
from backend.qwen21.environment import source_path, turbo_path
from backend.qwen21.runtime import PREFIX


def emit(event, **extra):
    print(PREFIX + json.dumps({"event": event, **extra}, ensure_ascii=False), flush=True)


class Cancelled(Exception):
    pass


class Worker:
    def __init__(self, component):
        self.component = Path(component).resolve()
        sys.path.insert(0, str(source_path(component) / "src"))
        self.pipeline, self.signature = None, None

    def generate(self, request):
        import mlx.core as mx
        from mflux.callbacks.callback_registry import CallbackRegistry
        from backend.qwen21.mlx_adapter import load_pipeline, prepare_loras
        from backend.qwen21.vae_runtime import model_view, vae_signature

        started = time.monotonic()
        directory = Path(request["job_dir"]).resolve()
        cancel = Path(request["cancel_file"])
        spec = request["spec"]
        model = spec["model"]
        preset = spec["preset"]
        turbo = preset != "standard"
        loras = list(spec.get("loras") or [])
        if turbo:
            loras.insert(0, {"path": str(turbo_path(self.component, preset)), "scale": 1.0})
        files = [(str(x["path"]), Path(x["path"]).stat().st_mtime_ns, float(x["scale"])) for x in loras]
        vae = spec.get("vae")
        signature = (str(model["path"]), bool(turbo), tuple(files), vae_signature(vae))
        emit("progress", ratio=.02, stage="载入 " + model["name"])
        if cancel.exists():
            raise Cancelled()
        load_started = time.monotonic()
        if signature != self.signature:
            self.pipeline, self.signature = None, None
            gc.collect()
            mx.clear_cache()
            mx.set_cache_limit(1024**3)
            adapted_loras = prepare_loras(loras, self.component / "cache" / "loras")
            with model_view(model["path"], vae, self.component / "cache" / "vae-views") as path:
                self.pipeline = load_pipeline(path, adapted_loras, turbo)
            self.signature = signature
        load_seconds = time.monotonic() - load_started
        emit("progress", ratio=.12, stage="模型载入完成")
        if cancel.exists():
            raise Cancelled()
        paths, seeds = [], []
        denoise_seconds, inference_seconds, save_seconds = 0.0, 0.0, 0.0
        count = spec["image_count"]
        for index in range(count):
            if cancel.exists():
                raise Cancelled()
            seed = (int(spec["seed"]) + index) % 2**32
            self.pipeline.prompt_cache.clear()
            self.pipeline.callbacks = CallbackRegistry()
            loop_times = {"start": None, "seconds": 0.0}

            class Progress:
                def call_before_loop(_self, **kwargs):
                    if cancel.exists():
                        raise Cancelled()
                    mx.eval(kwargs["latents"])
                    loop_times["start"] = time.monotonic()

                def call_in_loop(_self, t, **kwargs):
                    if cancel.exists():
                        raise Cancelled()
                    ratio = .15 + .76 * (index + (t + 1) / spec["steps"]) / count
                    emit("progress", ratio=ratio, stage=f"降噪 {index + 1}/{count} · {t + 1}/{spec['steps']}")

                def call_after_loop(_self, **kwargs):
                    mx.eval(kwargs["latents"])
                    loop_times["seconds"] = time.monotonic() - loop_times["start"]

            self.pipeline.callbacks.register(Progress())
            inference_started = time.monotonic()
            result = self.pipeline.generate_image(
                seed=seed, prompt=spec["prompt"], num_inference_steps=spec["steps"],
                width=spec["width"], height=spec["height"], guidance=spec["guidance"],
                negative_prompt=spec.get("negative_prompt") if spec["guidance"] > 1 else None,
                image_paths=spec.get("references") or [], output_resolution=1024,
                reference_resolution=spec.get("reference_resolution", 1024),
                scheduler="canvas_viggle" if turbo else "linear", independent_edit_noise=True)
            elapsed = time.monotonic() - inference_started
            denoise_seconds += loop_times["seconds"]
            inference_seconds += max(0, elapsed - loop_times["seconds"])
            if cancel.exists():
                raise Cancelled()
            save_started = time.monotonic()
            destination = directory / f"output_{index + 1}.png"
            pending = destination.with_suffix(".png.part")
            # Save pixels directly: upstream metadata may contain absolute model
            # and LoRA paths. Public provenance is written by the domain service.
            result.image.convert("RGBA").save(pending, format="PNG")
            os.replace(pending, destination)
            save_seconds += time.monotonic() - save_started
            paths.append(str(destination))
            seeds.append(seed)
            del result
            mx.clear_cache()
        return {"paths": paths, "seed": spec["seed"], "seeds": seeds,
                "base_model_id": model["id"], "base_model_name": model["name"],
                "precision": model["precision"], "preset": preset, "revision": REVISION,
                "vae_id": (vae or {}).get("id", "builtin"),
                "generation_timing": {"schema_version": 1, "local_inference": True,
                                      "model_load_seconds": round(load_seconds, 3),
                                      "inference_seconds": round(inference_seconds, 3),
                                      "denoise_seconds": round(denoise_seconds, 3),
                                      "save_seconds": round(save_seconds, 3),
                                      "total_seconds": round(time.monotonic() - started, 3)}}


def main():
    from backend.local_image.parent_watch import start_parent_watch
    start_parent_watch()
    worker = Worker(sys.argv[1])
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if request.get("command") == "shutdown":
                break
            if request.get("command") != "generate":
                continue
            job_id = str(request.get("job_id") or "")
            try:
                emit("result", job_id=job_id, **worker.generate(request))
            except Cancelled:
                emit("cancelled", job_id=job_id, message="任务已取消")
            except Exception as exc:
                worker.pipeline, worker.signature = None, None
                gc.collect()
                traceback.print_exc()
                emit("error", job_id=job_id, message=str(exc)[:1600])
        except (ValueError, KeyError) as exc:
            emit("error", job_id="", message=str(exc)[:400])


if __name__ == "__main__":
    main()
