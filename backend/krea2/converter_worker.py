"""Offline MLX checkpoint quantizer launched only by ConversionService."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback

try:
    from .comfy_fp8 import (KNOWN_PREFIXES, inspect_comfy_scaled_fp8,
                            load_comfy_scaled_fp8, read_safetensors_header)
except ImportError:  # Direct execution by ConversionService.
    from comfy_fp8 import (KNOWN_PREFIXES, inspect_comfy_scaled_fp8,
                           load_comfy_scaled_fp8, read_safetensors_header)


PREFIX = "KREA2_CONVERT_EVENT "
OUTPUT_FILENAME = "transformer.safetensors"


def emit(event, **payload):
    print(PREFIX + json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def configure(component):
    component = Path(component).resolve()
    source = component / "source"
    for path in (source / "krea2", source / "mflux"):
        sys.path.insert(0, str(path))
    os.environ.update({
        "HF_HOME": str(component / "cache" / "huggingface"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "PYTHONUNBUFFERED": "1",
        "MLX_ENABLE_TF32": "0",
        "AGX_RELAX_CDM_CTXSTORE_TIMEOUT": "1",
    })


def digest(path, start, end, label):
    value = hashlib.sha256()
    total = path.stat().st_size
    done = 0
    reported = -1
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(16 * 1024 * 1024), b""):
            value.update(chunk)
            done += len(chunk)
            percent = int(done * 100 / max(1, total))
            bucket = percent // 2
            if bucket != reported:
                reported = bucket
                emit("progress", progress=start + (end - start) * percent / 100,
                     stage=f"{label} · {percent}%")
    return value.hexdigest()


from backend.krea2.contracts import EXPORT_FORMATS
from backend.local_image.safetensors import (pending_safetensors_path, save_safetensors_atomic,
                                            validate_bf16_safetensors)


def select_weights(weights, expected):
    best = None
    for prefix in KNOWN_PREFIXES:
        mapped = []
        missing = []
        mismatched = []
        for key, expected_array in expected.items():
            source_key = prefix + key
            source_array = weights.get(source_key)
            if source_array is None:
                missing.append(key)
                continue
            if tuple(source_array.shape) != tuple(expected_array.shape):
                mismatched.append((key, tuple(source_array.shape), tuple(expected_array.shape)))
                continue
            mapped.append((key, source_array))
        # A shape mismatch is still evidence that the wrapper prefix is the
        # correct namespace. Prefer coverage first, then exact shape matches.
        score = (len(mapped) + len(mismatched)) * 10 - len(missing) - len(mismatched)
        candidate = (score, prefix, mapped, missing, mismatched)
        if best is None or candidate[0] > best[0]:
            best = candidate
        if not missing and not mismatched:
            return prefix, mapped
    _, prefix, mapped, missing, mismatched = best
    details = []
    if missing:
        details.append(f"缺少 {len(missing)} 个张量，例如 {', '.join(missing[:3])}")
    if mismatched:
        name, actual, wanted = mismatched[0]
        details.append(f"{len(mismatched)} 个 shape 不一致，例如 {name}: {actual} != {wanted}")
    raise ValueError("源模型与 Krea 2 Turbo Transformer 不兼容（"
                     + (prefix or "无前缀") + "）：" + "；".join(details))


def convert(component, source, output, precision, name):
    configure(component)
    import mlx.core as mx
    from mlx import nn
    from mlx.utils import tree_flatten, tree_map
    from krea2.quant_recipes import mixed_4_8, quantize_bulk
    from krea2.transformer import Krea2Config, SingleStreamDiT

    source = Path(source).resolve(strict=True)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    destination = output / OUTPUT_FILENAME
    pending = pending_safetensors_path(destination)
    pending.unlink(missing_ok=True)
    if precision not in EXPORT_FORMATS:
        raise ValueError("未知输出精度")
    export = EXPORT_FORMATS[precision]

    emit("progress", progress=3, stage="读取源模型")
    source_sha256 = digest(source, 4, 16, "校验源模型哈希")
    emit("progress", progress=17, stage="创建 Krea 2 Transformer 结构")
    model = SingleStreamDiT(Krea2Config())
    expected = dict(tree_flatten(model.parameters()))
    header = read_safetensors_header(source)
    comfy_fp8 = inspect_comfy_scaled_fp8(header)
    source_format = "float"
    source_quantized_tensor_count = 0
    if comfy_fp8:
        emit("progress", progress=20, stage="验证 ComfyUI scaled-FP8 结构")
        last_bucket = -1

        def decoded(done, total, key):
            nonlocal last_bucket
            percent = int(done * 100 / max(1, total))
            bucket = percent // 2
            if bucket != last_bucket:
                last_bucket = bucket
                emit("progress", progress=22 + 17 * percent / 100,
                     stage=f"逐张量解码 scaled-FP8 · {percent}%")

        loaded = load_comfy_scaled_fp8(source, expected, mx, header=header, progress=decoded)
        mapped = loaded["weights"]
        source_prefix = loaded["source_prefix"]
        source_tensor_count = loaded["source_tensor_count"]
        source_format = loaded["source_format"]
        source_quantized_tensor_count = loaded["source_quantized_tensor_count"]
        del loaded
        emit("progress", progress=40, stage="严格装载解码后的 BF16 权重")
    else:
        weights = mx.load(str(source))
        if any(key.endswith(".scales") or key.endswith(".biases") for key in weights):
            raise ValueError("源文件已经是 MLX 量化模型，请选择原始浮点或 ComfyUI scaled-FP8 权重")
        emit("progress", progress=22, stage="严格检查张量名称与 shape")
        source_prefix, mapped = select_weights(weights, expected)
        source_tensor_count = len(mapped)
    model.load_weights(mapped, strict=True)
    # Do not keep a second reference to every source tensor (or to the model's
    # initial parameter tree) while BF16 casting and quantization allocate their
    # outputs.  Full Krea 2 checkpoints are large enough for those otherwise
    # harmless dictionaries to create avoidable unified-memory pressure.
    del expected, mapped
    if not comfy_fp8:
        del weights
    gc.collect()
    emit("progress", progress=41 if comfy_fp8 else 30, stage="将兼容权重统一为 BF16")
    model.update(tree_map(lambda value: value.astype(mx.bfloat16), model.parameters()))
    mx.eval(model.parameters())

    if precision == "8bit":
        emit("progress", progress=43, stage="执行 8-bit · group size 64 量化")
        nn.quantize(model, group_size=64, bits=8, class_predicate=quantize_bulk)
    elif precision == "mixed-4-8":
        emit("progress", progress=43, stage="执行 Mixed 4/8-bit · group size 64 量化")
        nn.quantize(model, group_size=64, bits=4, class_predicate=mixed_4_8)
    else:
        emit("progress", progress=43, stage="保留 BF16 Transformer · 不进行低位量化")
    mx.eval(model.parameters())
    emit("progress", progress=70, stage="写入 MLX safetensors")
    flattened = dict(tree_flatten(model.parameters()))
    save_safetensors_atomic(mx, destination, flattened, metadata={
        "architecture": "krea2-single-stream-dit-v1",
        "precision": precision,
        "recipe": export["recipe"],
        **({"group_size": "64"} if precision != "bf16" else {}),
        "source_sha256": source_sha256,
        "source_format": source_format,
        "source_quantized_tensor_count": str(source_quantized_tensor_count),
        "model_name": str(name),
    })

    del flattened, model
    gc.collect()
    mx.clear_cache()
    emit("progress", progress=82, stage="严格重载 Transformer")
    verify = SingleStreamDiT(Krea2Config())
    if precision == "8bit":
        nn.quantize(verify, group_size=64, bits=8, class_predicate=quantize_bulk)
    elif precision == "mixed-4-8":
        nn.quantize(verify, group_size=64, bits=4, class_predicate=mixed_4_8)
    verify.load_weights(str(destination), strict=True)
    mx.eval(verify.parameters())
    output_tensor_count = len(tree_flatten(verify.parameters()))
    quantized_linear_count = sum(
        1 for _, module in verify.named_modules() if hasattr(module, "bits"))
    expected_count = export["quantized_linear_count"]
    if quantized_linear_count != expected_count:
        raise RuntimeError(
            f"结构验证失败：期望 {expected_count} 个量化 Linear，实际 {quantized_linear_count} 个")
    if precision == "bf16":
        if output_tensor_count != source_tensor_count:
            raise RuntimeError("BF16 Transformer 张量数量发生变化")
        validate_bf16_safetensors(destination, source_tensor_count, metadata={"precision": "bf16"})
    del verify
    gc.collect()
    mx.clear_cache()

    emit("progress", progress=91, stage="校验输出模型哈希")
    output_sha256 = digest(destination, 91, 98, "校验输出模型哈希")
    emit("result", progress=98, stage="模型转换与严格重载完成",
         source_sha256=source_sha256, output_sha256=output_sha256,
         source_prefix=source_prefix, source_tensor_count=source_tensor_count,
         source_format=source_format,
         source_quantized_tensor_count=source_quantized_tensor_count,
         output_tensor_count=output_tensor_count,
         quantized_linear_count=quantized_linear_count,
         file_size=destination.stat().st_size, precision=precision)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--component", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--precision", choices=tuple(EXPORT_FORMATS), required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        convert(args.component, args.source, args.output, args.precision, args.name)
    except BaseException as exc:
        pending = pending_safetensors_path(Path(args.output) / OUTPUT_FILENAME)
        pending.unlink(missing_ok=True)
        traceback.print_exc()
        emit("error", message=str(exc)[:2000] or type(exc).__name__)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
