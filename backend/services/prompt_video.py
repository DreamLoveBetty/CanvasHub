"""Video-reference normalization and batched key-frame understanding.

The browser owns decoding because every supported canvas video is already
playable there.  This service owns the server-side contract: validate the
12--24 sampled frames, analyze them in bounded multimodal batches, cache the
content summary, and return text that existing prompt providers can consume.

No raw video, canvas state, HTTP handler, or provider credential is owned here.
The caller injects the existing prompt-model adapter so Codex -> account-pool
fallback semantics stay unchanged.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from typing import Any, Callable


MIN_FRAMES_PER_VIDEO = 12
MIN_RECOMMENDED_FRAMES = MIN_FRAMES_PER_VIDEO
MAX_FRAMES_PER_VIDEO = 24
MAX_VIDEO_REFERENCES = 2
FRAME_BATCH_SIZE = 8
MAX_FRAME_DATA_URL_CHARS = 2_500_000
SUMMARY_CACHE_ITEMS = 16


VIDEO_FRAME_SYSTEM = """你是视频关键帧分析器。输入图像来自同一段视频，并按时间先后排列。
只依据画面证据描述：主体、动作变化、场景变化、镜头景别与运动线索、节奏、光线、色彩、材质、视觉风格和可见文字。
必须区分“单帧可见事实”和“由相邻帧变化推断的运动”；无法确认的内容明确写未知。
不要虚构未提供的音频、对白、片外事件或精确摄影参数。输出简洁中文结构化文本，不要 Markdown 表格。"""


_SUMMARY_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_SUMMARY_CACHE_LOCK = threading.Lock()


def _text(value: Any, limit: int = 4_000) -> str:
    clean = str(value or "").strip()
    return clean if len(clean) <= limit else clean[:limit]


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed >= 0 else fallback


def normalize_video_references(videos: list[Any] | None) -> list[dict[str, Any]]:
    """Validate client-sampled video frames without retaining the raw video."""
    if videos is None:
        return []
    if not isinstance(videos, list):
        raise ValueError("引用视频必须是列表")
    if len(videos) > MAX_VIDEO_REFERENCES:
        raise ValueError(f"最多支持 {MAX_VIDEO_REFERENCES} 个视频引用")

    normalized: list[dict[str, Any]] = []
    for video_index, raw_video in enumerate(videos):
        if not isinstance(raw_video, dict):
            raise ValueError("视频引用格式错误")
        raw_frames = raw_video.get("frames")
        if not isinstance(raw_frames, list) or not raw_frames:
            raise ValueError("视频引用缺少已抽取的关键帧")
        if len(raw_frames) < MIN_FRAMES_PER_VIDEO:
            raise ValueError(f"每个视频至少需要 {MIN_FRAMES_PER_VIDEO} 帧")
        if len(raw_frames) > MAX_FRAMES_PER_VIDEO:
            raise ValueError(f"每个视频最多支持 {MAX_FRAMES_PER_VIDEO} 帧")

        frames: list[dict[str, Any]] = []
        for frame_index, raw_frame in enumerate(raw_frames):
            if isinstance(raw_frame, str):
                data_url = raw_frame.strip()
                timestamp = float(frame_index)
            elif isinstance(raw_frame, dict):
                data_url = _text(
                    raw_frame.get("data_url")
                    or raw_frame.get("dataUrl")
                    or raw_frame.get("image_data")
                    or raw_frame.get("imageData"),
                    MAX_FRAME_DATA_URL_CHARS + 1,
                )
                timestamp = _number(
                    raw_frame.get("timestamp_seconds")
                    if raw_frame.get("timestamp_seconds") is not None
                    else raw_frame.get("timestampSeconds"),
                    float(frame_index),
                )
            else:
                raise ValueError("视频关键帧格式错误")
            if not data_url.startswith("data:image/"):
                raise ValueError("视频关键帧必须是图像 data URL")
            if len(data_url) > MAX_FRAME_DATA_URL_CHARS:
                raise ValueError("视频关键帧数据过大，请降低抽帧分辨率")
            frames.append({
                "index": frame_index + 1,
                "timestamp_seconds": round(timestamp, 3),
                "data_url": data_url,
            })

        video_id = _text(raw_video.get("id") or f"video{video_index + 1}", 80) or f"video{video_index + 1}"
        normalized.append({
            "id": video_id,
            "label": _text(raw_video.get("label") or raw_video.get("name") or video_id, 240),
            "source_node_id": _text(raw_video.get("source_node_id") or raw_video.get("sourceNodeId"), 160),
            "mime_type": _text(raw_video.get("mime_type") or raw_video.get("mimeType") or "video/mp4", 120),
            "duration_seconds": round(_number(raw_video.get("duration_seconds") or raw_video.get("durationSeconds")), 3),
            "width": int(_number(raw_video.get("width") or raw_video.get("media_width") or raw_video.get("mediaWidth"))),
            "height": int(_number(raw_video.get("height") or raw_video.get("media_height") or raw_video.get("mediaHeight"))),
            "fps": round(_number(raw_video.get("fps")), 3),
            "frames": frames,
            "recommended_frame_minimum_met": len(frames) >= MIN_RECOMMENDED_FRAMES,
        })
    return normalized


def _summary_cache_key(video: dict[str, Any], options: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps({
        "id": video.get("id"),
        "duration_seconds": video.get("duration_seconds"),
        "width": video.get("width"),
        "height": video.get("height"),
        "provider": options.get("provider"),
        "model": options.get("model"),
        "reasoning_effort": options.get("reasoning_effort") or options.get("reasoningEffort"),
    }, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    for frame in video.get("frames") or []:
        digest.update(str(frame.get("timestamp_seconds") or 0).encode("ascii", errors="ignore"))
        digest.update(str(frame.get("data_url") or "").encode("utf-8"))
    return digest.hexdigest()


def _cache_get(key: str) -> dict[str, Any] | None:
    with _SUMMARY_CACHE_LOCK:
        value = _SUMMARY_CACHE.pop(key, None)
        if value is None:
            return None
        _SUMMARY_CACHE[key] = value
        return dict(value)


def _cache_put(key: str, value: dict[str, Any]) -> None:
    with _SUMMARY_CACHE_LOCK:
        _SUMMARY_CACHE.pop(key, None)
        _SUMMARY_CACHE[key] = dict(value)
        while len(_SUMMARY_CACHE) > SUMMARY_CACHE_ITEMS:
            _SUMMARY_CACHE.popitem(last=False)


def _batch_prompt(video: dict[str, Any], batch: list[dict[str, Any]], batch_index: int, batch_count: int) -> str:
    metadata = {
        "video_id": video.get("id"),
        "label": video.get("label"),
        "duration_seconds": video.get("duration_seconds"),
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": video.get("fps"),
        "batch": f"{batch_index}/{batch_count}",
    }
    timestamps = "、".join(
        f"图{index + 1}={float(frame.get('timestamp_seconds') or 0):.2f}s"
        for index, frame in enumerate(batch)
    )
    return "\n".join([
        "分析这一批按时间顺序排列的视频关键帧。",
        f"视频元数据：{json.dumps(metadata, ensure_ascii=False)}",
        f"图片与时间对应：{timestamps}",
        "输出以下项目：画面事实；主体与动作变化；场景变化；镜头/构图变化；节奏线索；光色与视觉风格；可见文字；不确定项。",
    ])


def summarize_video_references(
    videos: list[Any] | None,
    *,
    call_model: Callable[..., dict[str, Any]],
    options: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Analyze 1--2 videos in batches of eight frames through an injected model."""
    normalized = normalize_video_references(videos)
    model_options = dict(options or {})
    model_options["reasoning_effort"] = model_options.get("reasoning_effort") or model_options.get("reasoningEffort") or "low"
    summaries: list[dict[str, Any]] = []
    for video in normalized:
        key = _summary_cache_key(video, model_options)
        cached = _cache_get(key)
        if cached is not None:
            summaries.append(cached)
            continue

        frames = video["frames"]
        batches = [frames[index:index + FRAME_BATCH_SIZE] for index in range(0, len(frames), FRAME_BATCH_SIZE)]
        batch_summaries: list[dict[str, Any]] = []
        providers: list[str] = []
        models: list[str] = []
        warnings: list[str] = []
        for batch_index, batch in enumerate(batches, start=1):
            result = call_model(
                _batch_prompt(video, batch, batch_index, len(batches)),
                VIDEO_FRAME_SYSTEM,
                model_options,
                images=[frame["data_url"] for frame in batch],
                error_label="视频关键帧分析",
            )
            text = _text(result.get("text") or result.get("reply"), 12_000)
            if not text:
                raise RuntimeError("视频关键帧分析没有返回内容")
            batch_summaries.append({
                "batch_index": batch_index,
                "start_seconds": batch[0]["timestamp_seconds"],
                "end_seconds": batch[-1]["timestamp_seconds"],
                "frame_count": len(batch),
                "summary": text,
            })
            if result.get("provider"):
                providers.append(str(result["provider"]))
            if result.get("model"):
                models.append(str(result["model"]))
            if result.get("warning"):
                warnings.append(str(result["warning"]))

        summary = {
            "id": video["id"],
            "label": video["label"],
            "source_node_id": video["source_node_id"],
            "duration_seconds": video["duration_seconds"],
            "width": video["width"],
            "height": video["height"],
            "fps": video["fps"],
            "frame_count": len(frames),
            "batch_count": len(batches),
            "recommended_frame_minimum_met": video["recommended_frame_minimum_met"],
            "batch_summaries": batch_summaries,
            "summary": "\n\n".join(
                f"{item['start_seconds']:.2f}s–{item['end_seconds']:.2f}s：{item['summary']}"
                for item in batch_summaries
            ),
            "providers": list(dict.fromkeys(providers)),
            "models": list(dict.fromkeys(models)),
            "warnings": list(dict.fromkeys(warnings)),
        }
        _cache_put(key, summary)
        summaries.append(summary)
    return summaries


def video_summaries_prompt_context(summaries: list[dict[str, Any]]) -> str:
    """Serialize summaries for a final assistant/planner call without frame data."""
    sections: list[str] = []
    for video in summaries:
        meta = [
            f"引用编号 {video.get('id')}",
            str(video.get("label") or "视频"),
            f"{video.get('frame_count') or 0} 帧",
        ]
        if video.get("duration_seconds"):
            meta.append(f"{video['duration_seconds']:g} 秒")
        if video.get("width") and video.get("height"):
            meta.append(f"{video['width']}×{video['height']}")
        sections.append(f"【{' · '.join(meta)}】\n{video.get('summary') or ''}")
    return "\n\n".join(sections).strip()
