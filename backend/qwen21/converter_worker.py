"""Offline Qwen-specific quantizer, run only in a leased child process."""
from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
import shutil
import traceback

from ..local_image.comfy_fp8 import inspect_comfy_scaled_fp8, load_comfy_scaled_fp8, read_safetensors_header
from ..local_image.downloads import sha256
from ..local_image.safetensors import save_safetensors_atomic, validate_bf16_safetensors
from .contracts import EXPORT_FORMATS
from .weight_schema import expected_shapes, match_header, mlx_name

PREFIX = "QWEN21_CONVERT_EVENT "


def emit(event, **extra):
    print(PREFIX + json.dumps({"event": event, **extra}, ensure_ascii=False), flush=True)


def convert(source, output, config_path, name, precision="8bit"):
    if precision not in EXPORT_FORMATS:
        raise ValueError("未知 Qwen 输出精度")
    import mlx.core as mx
    import mlx.nn as nn
    from mlx.utils import tree_flatten, tree_map
    from mflux.models.qwen21.model.qwen21_transformer.qwen21_transformer import Qwen21Transformer
    from mflux.models.qwen21.reference.weights.qwen_image21_weight_definition import QwenImage21WeightDefinition

    source, output = Path(source).resolve(), Path(output).resolve()
    header = read_safetensors_header(source)
    fp8 = inspect_comfy_scaled_fp8(header)
    prefix = match_header(header.tensors, allow_auxiliary=bool(fp8))
    emit("progress", progress=5, stage="校验源模型 SHA-256")
    source_sha = sha256(source)
    model = Qwen21Transformer()
    expected_mlx = dict(tree_flatten(model.parameters()))
    expected_raw = {key: expected_mlx[mlx_name(key)] for key in expected_shapes()}
    emit("progress", progress=18, stage="逐张量读取完整 Qwen 2.1 Transformer")
    if fp8:
        loaded = load_comfy_scaled_fp8(source, expected_raw, mx, header=header,
                                      progress=lambda done, total, key: emit(
                                          "progress", progress=18 + 22 * done / total,
                                          stage=f"scaled-FP8 → BF16 · {int(done * 100 / total)}%"))
        mapped = [(mlx_name(key), value) for key, value in loaded["weights"]]
        del loaded
        source_format = fp8["source_format"]
    else:
        source_weights = mx.load(str(source))
        mapped = [(mlx_name(key), source_weights[prefix + key]) for key in expected_shapes()]
        del source_weights
        source_format = "float"
    model.load_weights(mapped, strict=True)
    del mapped, expected_raw, expected_mlx
    gc.collect()
    model.update(tree_map(lambda value: value.astype(mx.bfloat16), model.parameters()))
    mx.eval(model.parameters())
    predicate = QwenImage21WeightDefinition.quantization_predicate
    if precision == "8bit":
        emit("progress", progress=43, stage="Qwen 专用 MLX 8-bit · group_size=64")
        nn.quantize(model, bits=8, group_size=64, class_predicate=predicate)
    else:
        emit("progress", progress=43, stage="保留 BF16 Transformer · 不进行低位量化")
    mx.eval(model.parameters())
    count = sum(hasattr(module, "bits") for _, module in model.named_modules())
    expected_count = EXPORT_FORMATS[precision]["quantized_linear_count"]
    if count != expected_count:
        raise RuntimeError(f"Qwen 结构不符：{count} != {expected_count}")
    directory = output / "transformer"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "0.safetensors"
    emit("progress", progress=70, stage="原子写入 MLX Transformer")
    weights = dict(tree_flatten(model.parameters()))
    metadata = {
        "quantization_level": "None" if precision == "bf16" else "8",
        "mflux_version": "0.20.0+canvas-qwen21", "precision": precision,
        "architecture": "qwen-image-2.1", "model_name": str(name),
        **({"group_size": "64"} if precision == "8bit" else {}),
        "source_sha256": source_sha, "source_format": source_format}
    save_safetensors_atomic(mx, destination, weights, metadata=metadata)
    index = {"metadata": {key: metadata[key] for key in ("quantization_level", "mflux_version")},
             "weight_map": {key: destination.name for key in weights}}
    (directory / "model.safetensors.index.json").write_text(json.dumps(index, indent=2) + "\n")
    shutil.copyfile(config_path, directory / "config.json")
    del weights, model
    gc.collect()
    mx.clear_cache()
    emit("progress", progress=82, stage="严格重载全部 Transformer 参数")
    verify = Qwen21Transformer()
    if precision == "8bit":
        nn.quantize(verify, bits=8, group_size=64, class_predicate=predicate)
    verify.load_weights(str(destination), strict=True)
    mx.eval(verify.parameters())
    output_count = len(tree_flatten(verify.parameters()))
    if precision == "bf16":
        validate_bf16_safetensors(destination, 297,
                                 metadata={"precision": "bf16", "quantization_level": "None"})
    del verify
    gc.collect()
    mx.clear_cache()
    emit("progress", progress=94, stage="校验转换产物 SHA-256")
    return {"source_sha256": source_sha, "output_sha256": sha256(destination),
            "source_format": source_format, "source_prefix": prefix,
            "source_tensor_count": 297, "source_quantized_tensor_count": (fp8 or {}).get("quantized_tensor_count", 0),
            "output_tensor_count": output_count, "quantized_linear_count": count,
            "precision": precision, "strict_load": True, "strict_reload": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--precision", choices=tuple(EXPORT_FORMATS), default="8bit")
    args = parser.parse_args()
    try:
        result = convert(args.source, args.output, args.config, args.name, args.precision)
        emit("result", **result)
    except Exception as exc:
        traceback.print_exc()
        emit("error", message=str(exc)[:1600])
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
