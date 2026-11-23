"""One-shot MLX WeMM-Video inference worker running inside the isolated Python 3.12 venv."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.local_image.parent_watch import start_parent_watch
from backend.video_understand.contracts import EVENT_PREFIX
from backend.video_understand.prompts import build_prompt


def emit(event: str, **payload: Any) -> None:
    print(EVENT_PREFIX + json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _collect_eos_ids(model: Any, processor: Any) -> set[int]:
    eos_ids: set[int] = set()
    tok_eos = getattr(processor.tokenizer, "eos_token_id", None)
    if tok_eos is not None:
        eos_ids.add(int(tok_eos))
    cfg_eos = getattr(model.config, "eos_token_id", None)
    if isinstance(cfg_eos, int):
        eos_ids.add(cfg_eos)
    elif isinstance(cfg_eos, list):
        eos_ids.update(int(x) for x in cfg_eos)
    im_end = processor.tokenizer.convert_tokens_to_ids("<|im_end|>")
    if isinstance(im_end, int) and im_end >= 0:
        eos_ids.add(im_end)
    return eos_ids


def _run_inference(request: Dict[str, Any], result_dir: Path) -> None:
    import mlx.core as mx
    from mlx_wemm_video.generate import _sample_next_token, load_wemm_model
    from mlx_wemm_video.media import _probe_video_ffprobe, detect_video_shots

    video_path = str(request["video_path"])
    model_dir = str(request["model_dir"])
    mode = str(request["mode"])
    use_audio = bool(request.get("use_audio", True))
    thinking = bool(request.get("thinking", False))
    shot_anchors = bool(request.get("shot_anchors", False))
    fps = float(request.get("fps", 1.0))
    max_frames = int(request.get("max_frames", 64))
    total_pixels = int(request.get("total_pixels", 2097152))
    max_tokens = int(request.get("max_tokens", 2048))
    min_shot_sec = float(request.get("min_shot_sec", 1.2))
    temperature = float(request.get("temperature", 0.0))
    custom_prompt = str(request.get("prompt") or "")
    model_variant = str(request.get("model_variant") or "")

    shots: List[Tuple[float, float]] = []
    if shot_anchors:
        emit("progress", stage="shots", ratio=0.05, message="正在检测视频切镜锚点")
        shots, duration = detect_video_shots(video_path, min_shot_sec=min_shot_sec)
        emit("progress", stage="shots", ratio=0.12, message=f"已检测 {len(shots)} 个镜头（{duration:.1f}s）", shots=len(shots))
    else:
        emit("progress", stage="shots", ratio=0.05, message="读取视频基础信息")
        _, _, _, _, duration = _probe_video_ffprobe(video_path)

    prompt = build_prompt(
        mode,
        duration=duration,
        shots=shots if shot_anchors else None,
        custom_prompt=custom_prompt,
        use_audio=use_audio,
    )

    emit("progress", stage="load", ratio=0.14, message="正在加载 WeMM-Video MLX 模型")
    t_load = time.monotonic()
    model, processor = load_wemm_model(model_dir)
    load_sec = time.monotonic() - t_load

    emit("progress", stage="encode", ratio=0.20, message="正在编码视频画面与音轨")
    t_enc = time.monotonic()
    media_kind = "video_audio" if use_audio else "video"
    messages = [{
        "role": "user",
        "content": [
            {
                "type": media_kind,
                "video": video_path,
                "fps": fps,
                "min_frames": 4,
                "max_frames": max_frames,
                "total_pixels": total_pixels,
            },
            {"type": "text", "text": prompt},
        ],
    }]
    inputs = processor.prepare_messages(
        messages,
        add_generation_prompt=True,
        enable_thinking=thinking,
        use_audio_in_video=use_audio,
        fps=fps,
        max_frames=max_frames,
        total_pixels=total_pixels,
    )
    input_ids = inputs["input_ids"]
    prompt_tokens = int(input_ids.shape[1])

    emb_out = model.get_input_embeddings(
        input_ids=input_ids,
        pixel_values=inputs.get("pixel_values"),
        pixel_values_videos=inputs.get("pixel_values_videos"),
        image_grid_thw=inputs.get("image_grid_thw"),
        video_grid_thw=inputs.get("video_grid_thw"),
        audio_feature=inputs.get("audio_feature"),
        attention_mask=inputs.get("attention_mask"),
    )
    inputs_embeds = emb_out.inputs_embeds
    position_ids = emb_out.position_ids
    mx.eval(inputs_embeds, position_ids)
    encode_sec = time.monotonic() - t_enc

    emit(
        "progress",
        stage="prefill",
        ratio=0.25,
        message=f"正在 Prefill（{prompt_tokens} tokens）",
        prompt_tokens=prompt_tokens,
    )
    cache = model.language_model.make_cache()
    prefill_step_size = 2048
    total_len = int(inputs_embeds.shape[1])
    t_prefill = time.monotonic()
    pos = 0
    logits = None
    while pos < total_len:
        end = min(total_len, pos + prefill_step_size)
        out = model.language_model(
            input_ids[:, pos:end],
            inputs_embeds=inputs_embeds[:, pos:end, :],
            cache=cache,
            position_ids=position_ids[:, :, pos:end] if position_ids is not None else None,
        )
        logits = out.logits[:, -1, :]
        mx.eval(logits, [c.state for c in cache])
        pos = end
        ratio = 0.25 + 0.20 * (pos / max(1, total_len))
        emit(
            "progress",
            stage="prefill",
            ratio=round(ratio, 3),
            message=f"Prefill {pos}/{total_len} tokens",
            prompt_tokens=prompt_tokens,
        )
    prefill_sec = time.monotonic() - t_prefill

    eos_ids = _collect_eos_ids(model, processor)
    next_tok = _sample_next_token(logits, temperature=temperature, top_p=0.95)
    mx.eval(next_tok)

    generated_ids: List[int] = []
    finish_reason = "length"
    t_gen = time.monotonic()
    last_emit = t_gen

    emit("progress", stage="generate", ratio=0.46, message="正在生成文本分析", prompt_tokens=prompt_tokens)
    for step in range(max_tokens):
        tok_id = int(next_tok.item())
        if tok_id in eos_ids:
            finish_reason = "stop"
            break
        generated_ids.append(tok_id)
        now = time.monotonic()
        if step == 0 or (step + 1) % 16 == 0 or (now - last_emit) >= 0.8:
            last_emit = now
            tps = len(generated_ids) / max(1e-6, now - t_gen)
            preview = processor.tokenizer.decode(generated_ids, skip_special_tokens=True)[-160:]
            ratio = 0.46 + 0.50 * min(1.0, len(generated_ids) / max(1, max_tokens))
            emit(
                "progress",
                stage="generate",
                ratio=round(ratio, 3),
                message=f"生成中 · {len(generated_ids)} tok · {tps:.1f} tok/s",
                prompt_tokens=prompt_tokens,
                generated_tokens=len(generated_ids),
                decode_tps=round(tps, 2),
                preview_tail=preview,
            )
        out = model.language_model(next_tok[:, None], cache=cache)
        next_tok = _sample_next_token(out.logits[:, -1, :], temperature=temperature, top_p=0.95)
        mx.eval(next_tok)

    decode_sec = time.monotonic() - t_gen
    decode_tps = len(generated_ids) / max(1e-6, decode_sec)
    final_text = processor.tokenizer.decode(generated_ids, skip_special_tokens=True).strip()

    emit("progress", stage="save", ratio=0.97, message="正在保存分析结果")
    shots_payload = [{"index": i + 1, "start": round(s, 3), "end": round(e, 3)} for i, (s, e) in enumerate(shots)]
    stats = {
        "prompt_tokens": prompt_tokens,
        "generated_tokens": len(generated_ids),
        "finish_reason": finish_reason,
        "load_sec": round(load_sec, 3),
        "encode_sec": round(encode_sec, 3),
        "prefill_sec": round(prefill_sec, 3),
        "decode_sec": round(decode_sec, 3),
        "decode_tps": round(decode_tps, 2),
    }
    result_payload = {
        "text": final_text,
        "finish_reason": finish_reason,
        "mode": mode,
        "model_variant": model_variant,
        "duration_sec": round(float(duration), 3),
        "shots": shots_payload,
        "stats": stats,
    }
    _atomic_write_text(result_dir / "output.md", final_text + "\n")
    _atomic_write_text(result_dir / "shots.json", json.dumps(shots_payload, ensure_ascii=False, indent=2) + "\n")
    _atomic_write_text(result_dir / "result.json", json.dumps(result_payload, ensure_ascii=False, indent=2) + "\n")
    emit("done", stage="done", ratio=1.0, message="分析完成", **stats)


def main(argv: Optional[List[str]] = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        raise SystemExit("usage: worker.py <request.json> <result_dir>")
    start_parent_watch()
    request_path = Path(args[0])
    result_dir = Path(args[1])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    _run_inference(request, result_dir)


if __name__ == "__main__":
    main()
