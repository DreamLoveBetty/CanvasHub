"""Persistent MLX worker for Krea 2.

This is the only CanvasHub process that imports Krea/MLX.  The HTTP process
speaks a small JSON-lines protocol over stdin/stdout and keeps owning task,
archive and authentication state.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
import sys
import time
import traceback


PREFIX = "KREA2_EVENT "


class Cancelled(RuntimeError):
    pass


def emit(event, **payload):
    print(PREFIX + json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def _denoise_elapsed(generate_started, generate_finished, step_marks):
    """Estimate the complete denoise window from post-step callbacks."""
    if not step_marks:
        return 0.0
    elapsed = max(0.0, generate_finished - generate_started)
    if len(step_marks) == 1:
        return min(elapsed, max(0.0, step_marks[0] - generate_started))
    intervals = sorted(
        max(0.0, current - previous)
        for previous, current in zip(step_marks, step_marks[1:])
    )
    typical_step = intervals[len(intervals) // 2]
    measured = max(0.0, step_marks[-1] - step_marks[0]) + typical_step
    return min(elapsed, measured)


def _generation_timing(total, model_load, denoise, save):
    total = max(0.0, float(total))
    model_load = min(total, max(0.0, float(model_load)))
    denoise = min(max(0.0, total - model_load), max(0.0, float(denoise)))
    save = min(max(0.0, total - model_load - denoise), max(0.0, float(save)))
    inference = max(0.0, total - model_load - denoise - save)
    rounded = {
        "schema_version": 1,
        "local_inference": True,
        "total_seconds": round(total, 3),
        "model_load_seconds": round(model_load, 3),
        "denoise_seconds": round(denoise, 3),
        "save_seconds": round(save, 3),
    }
    rounded["inference_seconds"] = round(max(
        0.0,
        rounded["total_seconds"]
        - rounded["model_load_seconds"]
        - rounded["denoise_seconds"]
        - rounded["save_seconds"],
    ), 3)
    return rounded


def configure(component):
    component = Path(component).resolve()
    source = component / "source"
    for path in (source / "krea2", source / "mflux"):
        sys.path.insert(0, str(path))
    cache = component / "cache" / "krea2_alis_mlx"
    os.environ.update({
        "HF_HOME": str(component / "cache" / "huggingface"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "PYTHONUNBUFFERED": "1",
        "MLX_ENABLE_TF32": "0",
        "AGX_RELAX_CDM_CTXSTORE_TIMEOUT": "1",
    })
    from krea2 import pipeline
    pipeline._CACHE = str(cache)
    return component, pipeline


class Engine:
    def __init__(self, component, pipeline_module):
        self.component = component
        self.pipeline_module = pipeline_module
        self.pipeline = None
        self.precision = ""
        self.model_id = ""
        self.model_name = ""
        self.model_signature = ""
        self.safety_classifier = None

    @property
    def cache(self):
        return self.component / "cache" / "krea2_alis_mlx"

    def _paths(self, precision):
        names = {
            "8bit": ("avlp12__Krea-2-Turbo-Alis-MLX-8bit", "transformer_8bit.safetensors"),
            "mixed-4-8": ("avlp12__Krea-2-Turbo-Alis-MLX-mixed-4-8", "transformer_mixed_4_8.safetensors"),
        }
        if precision not in names:
            raise ValueError("未知 Krea 2 模型构建")
        folder, filename = names[precision]
        return self.cache / folder / filename, self.cache / "krea__Krea-2-Turbo"

    def unload(self):
        if self.pipeline is not None:
            try:
                self.pipeline.set_loras([])
            except Exception:
                pass
        self.pipeline = None
        self.precision = ""
        self.model_id = ""
        self.model_name = ""
        self.model_signature = ""
        gc.collect()
        try:
            import mlx.core as mx
            mx.clear_cache()
        except Exception:
            pass

    def load(self, selection, cancelled):
        if isinstance(selection, dict):
            precision = str(selection.get("precision") or "")
            model_id = str(selection.get("id") or "")
            model_name = str(selection.get("name") or model_id or "Krea 2")
            transformer = Path(str(selection.get("path") or "")).expanduser().resolve()
            base = self.cache / "krea__Krea-2-Turbo"
        else:
            precision = str(selection or "8bit")
            transformer, base = self._paths(precision)
            model_id, model_name = precision, f"Krea 2 {precision}"
        if precision not in {"8bit", "mixed-4-8", "bf16"}:
            raise ValueError("未知 Krea 2 模型输出精度")
        try:
            signature = f"{model_id}:{precision}:{transformer}:{transformer.stat().st_size}:{transformer.stat().st_mtime_ns}"
        except OSError:
            signature = ""
        if self.pipeline is not None and self.model_signature == signature:
            return self.pipeline
        if cancelled():
            raise Cancelled("任务已取消")
        self.unload()
        if not transformer.is_file() or not (base / "model_index.json").is_file():
            raise RuntimeError("Krea 2 模型文件不完整，请先在节点中准备模型")
        emit("progress", ratio=0.02, stage=f"载入 {model_name}")
        self.pipeline = self.pipeline_module.Krea2Pipeline(
            transformer_path=str(transformer), precision=precision, base_dir=str(base))
        self.precision = precision
        self.model_id = model_id
        self.model_name = model_name
        self.model_signature = signature
        if cancelled():
            self.unload()
            raise Cancelled("任务已取消")
        emit("progress", ratio=0.12, stage="模型载入完成")
        return self.pipeline

    def safety(self):
        if self.safety_classifier is None:
            safety_path = self.cache / "Falconsai__nsfw_image_detection"
            if not safety_path.is_dir():
                raise RuntimeError("安全分类模型未安装；Krea 2 拒绝在无过滤状态下生成")
            from krea2.nsfw_mlx import load_classifier
            self.safety_classifier = load_classifier(str(safety_path))
            if self.safety_classifier is None:
                raise RuntimeError("安全分类模型载入失败；Krea 2 拒绝在无过滤状态下生成")
        return self.safety_classifier

    def run(self, request):
        total_started = time.perf_counter()
        job_id = str(request.get("job_id") or "")
        job_dir = Path(str(request.get("job_dir") or "")).resolve()
        cancel_file = Path(str(request.get("cancel_file") or "")).resolve()
        if not job_id or not job_dir.is_dir() or not cancel_file.is_relative_to(job_dir):
            raise ValueError("Krea 2 worker 请求目录无效")
        cancelled = cancel_file.exists
        spec = request.get("spec")
        if not isinstance(spec, dict):
            raise ValueError("Krea 2 worker 参数无效")
        load_started = time.perf_counter()
        pipe = self.load(spec.get("model") or str(spec.get("precision") or "8bit"), cancelled)
        model_load_seconds = time.perf_counter() - load_started
        loras = []
        edit_adapter = spec.get("edit_adapter")
        if edit_adapter:
            path = Path(str(edit_adapter.get("path") or "")).resolve()
            if not path.is_file() or path.suffix.lower() != ".safetensors":
                raise ValueError("编辑 LoRA 文件不存在或格式无效")
            loras.append((str(path), float(edit_adapter.get("scale", 1))))
        for item in spec.get("loras") or []:
            path = Path(str(item.get("path") or "")).resolve()
            if not path.is_file() or path.suffix.lower() != ".safetensors":
                raise ValueError("LoRA 文件不存在或格式无效")
            loras.append((str(path), float(item.get("scale", 1))))
        if cancelled():
            raise Cancelled("任务已取消")
        emit("progress", ratio=0.14, stage="应用 LoRA" if loras else "准备生成")
        pipe.set_loras(loras)
        safety_enabled = spec.get("safety_enabled") is True
        classifier = self.safety() if safety_enabled else None
        if safety_enabled:
            from krea2.nsfw_mlx import nsfw_score
            from krea2.safety import _redact

        output = job_dir / "generated"
        output.mkdir(parents=True, exist_ok=True)
        count = int(spec["image_count"])
        steps = int(spec["steps"])
        mode = str(spec.get("mode") or "standard")
        init_image = spec.get("init_image") or None
        if init_image:
            init_path = Path(str(init_image)).resolve()
            if not init_path.is_file() or not init_path.is_relative_to(job_dir):
                raise ValueError("重绘输入图不存在")
            init_image = str(init_path)
        edit_image = spec.get("edit_image") or None
        if mode == "edit":
            edit_path = Path(str(edit_image or "")).resolve()
            if not edit_path.is_file() or not edit_path.is_relative_to(job_dir):
                raise ValueError("指令编辑源图不存在")
            if not edit_adapter:
                raise ValueError("指令编辑 LoRA 未配置")
            edit_image = str(edit_path)
        elif edit_image or edit_adapter:
            raise ValueError("编辑源图和编辑 LoRA 只能用于指令编辑模式")
        paths, flagged = [], 0
        denoise_seconds = 0.0
        save_seconds = 0.0
        for index in range(count):
            if cancelled():
                raise Cancelled("任务已取消")

            step_marks = []

            def on_step(step, total, *, image_index=index):
                if cancelled():
                    raise Cancelled("任务已取消")
                step_marks.append(time.perf_counter())
                # Img2img runs only the strength-selected tail of the schedule,
                # so the callback's total may be smaller than the requested
                # step count.  Report progress against what is actually run.
                effective_total = max(1, int(total))
                completed_images = image_index + min(effective_total, max(0, int(step))) / effective_total
                ratio = 0.16 + (completed_images / max(1, count)) * 0.72
                emit("progress", ratio=ratio,
                     stage=f"生成第 {image_index + 1}/{count} 张 · {step}/{total} 步")

            generate_started = time.perf_counter()
            if mode == "edit":
                # Worker-local module: the HTTP process never imports MLX and
                # normal generation keeps using the pinned upstream pipeline.
                from edit_mlx import generate_edit

                def on_phase(ratio, stage):
                    if cancelled():
                        raise Cancelled("任务已取消")
                    emit("progress", ratio=0.14 + max(0.0, min(1.0, float(ratio))) * 0.02,
                         stage=str(stage))

                images = generate_edit(
                    pipe, spec["prompt"], source_image=edit_image,
                    text_encoder_path=self.cache / "krea__Krea-2-Turbo" / "text_encoder"
                                      / "model.safetensors",
                    width=int(spec["width"]), height=int(spec["height"]),
                    steps=steps, seed=int(spec["seed"]) + index,
                    reference_strength=float(spec.get("reference_strength", 4.0)),
                    grounding_px=int(spec.get("grounding_px", 768)),
                    fit_mode=str(spec.get("fit_mode") or "fit"),
                    step_callback=on_step, phase_callback=on_phase,
                )
            else:
                images = pipe.generate(
                    spec["prompt"], width=int(spec["width"]), height=int(spec["height"]),
                    steps=steps, seed=int(spec["seed"]) + index, num_images=1,
                    init_image=init_image, strength=float(spec["strength"]),
                    step_callback=on_step,
                )
            generate_finished = time.perf_counter()
            denoise_seconds += _denoise_elapsed(generate_started, generate_finished, step_marks)
            if cancelled():
                raise Cancelled("任务已取消")
            image = images[0]
            score = None
            was_flagged = False
            if safety_enabled:
                emit("progress", ratio=0.89 + (index / max(1, count)) * 0.05,
                     stage=f"安全检查第 {index + 1}/{count} 张")
                score = float(nsfw_score(classifier, image))
                was_flagged = score >= 0.85
                if was_flagged:
                    image = _redact(image)
                    flagged += 1
            else:
                emit("progress", ratio=0.89 + (index / max(1, count)) * 0.05,
                     stage=f"保存第 {index + 1}/{count} 张")
            path = output / f"result_{index + 1}.png"
            save_started = time.perf_counter()
            image.save(path, format="PNG")
            save_seconds += time.perf_counter() - save_started
            paths.append(str(path))
            emit("artifact", index=index, path=str(path), safety_score=score,
                 safety_flagged=was_flagged)
        timing = _generation_timing(
            time.perf_counter() - total_started,
            model_load_seconds,
            denoise_seconds,
            save_seconds,
        )
        return {"paths": paths, "flagged": flagged, "precision": self.precision,
                "base_model_id": self.model_id or str(spec.get("base_model_id") or ""),
                "base_model_name": self.model_name or str(spec.get("base_model_name") or ""),
                "seed": int(spec["seed"]), "mode": mode,
                "safety_enabled": safety_enabled,
                "safety_threshold": 0.85 if safety_enabled else None,
                "generation_timing": timing}


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from backend.local_image.parent_watch import start_parent_watch
    start_parent_watch()
    parser = argparse.ArgumentParser()
    parser.add_argument("component", type=Path)
    args = parser.parse_args()
    component, pipeline = configure(args.component)
    engine = Engine(component, pipeline)
    emit("ready", pid=os.getpid())
    for raw in sys.stdin:
        request = {}
        try:
            request = json.loads(raw)
            if request.get("command") == "shutdown":
                break
            if request.get("command") != "generate":
                raise ValueError("未知 worker 指令")
            result = engine.run(request)
            emit("result", job_id=request.get("job_id"), **result)
        except Cancelled as exc:
            emit("cancelled", job_id=(request or {}).get("job_id"), message=str(exc))
        except Exception as exc:
            emit("error", job_id=(request or {}).get("job_id"), message=str(exc)[:2000],
                 exception=type(exc).__name__, traceback=traceback.format_exc(limit=12)[-12000:])
    engine.unload()


if __name__ == "__main__":
    main()
