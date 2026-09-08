#!/usr/bin/env python3
"""Supervised Agent orchestration for the desktop prompt workbench.

The backend owns planning, approval state, prompt refinement, audit events and
generation monitoring.  Browser-owned canvas mutations are exposed as a small
allow-listed action protocol and must be acknowledged by the desktop client.
This keeps the runtime useful without giving it arbitrary file or settings
access, and lets existing generation/provider code remain the source of truth.
"""

from __future__ import annotations

import copy
import re
import threading
import time
import uuid
from typing import Any, Callable

from . import agent_store
from .database import get_task, update_task_status
from .prompt_skill_client import polish_prompt


AGENT_SCHEMA_VERSION = 2
MAX_PLAN_STEPS = 8
MAX_GENERATION_ROUNDS = 2
ACTION_TIMEOUT_SECONDS = 300
TERMINAL_RUN_STATUSES = {"succeeded", "failed", "canceled", "rolled_back"}
TERMINAL_TASK_STATUSES = {
    "succeeded",
    "success",
    "succeeded_no_telegram",
    "failed",
    "telegram_failed",
    "canceled",
}
CLIENT_ACTION_KINDS = {
    "analyze_images",
    "compile_h3_prompt",
    "update_text_node",
    "apply_prompt_to_input",
    "connect_nodes",
    "submit_generation",
    "submit_video_generation",
    "rollback_canvas",
}


class AgentRuntimeError(RuntimeError):
    pass


class AgentRunNotFound(AgentRuntimeError):
    pass


class AgentRunConflict(AgentRuntimeError):
    pass


class AgentRunCanceled(AgentRuntimeError):
    pass


class AgentRunRollback(AgentRuntimeError):
    pass


def _text(value: Any, limit: int = 30_000) -> str:
    clean = str(value or "").strip()
    return clean if len(clean) <= limit else f"{clean[:limit]}\n...[truncated]"


def _bool(value: Any, fallback: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return fallback
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled", "开启"}


def _int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))


def _workflow_state(context: dict[str, Any]) -> dict[str, Any]:
    workflow = context.get("workflow") if isinstance(context.get("workflow"), dict) else {}
    if isinstance(workflow.get("state"), dict):
        return workflow["state"]
    state = context.get("state") if isinstance(context.get("state"), dict) else {}
    return state or context


def _canvas_state(context: dict[str, Any]) -> dict[str, Any]:
    explicit = context.get("canvas") if isinstance(context.get("canvas"), dict) else {}
    if explicit:
        return explicit
    state = _workflow_state(context)
    return state.get("canvas") if isinstance(state.get("canvas"), dict) else {}


def _node_text(node: dict[str, Any] | None) -> str:
    if not isinstance(node, dict):
        return ""
    direct = _text(node.get("text"))
    if direct:
        return direct
    document = node.get("promptDocument") or node.get("prompt_document")
    if not isinstance(document, dict):
        return ""
    parts: list[str] = []
    for segment in document.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        value = segment.get("text") if segment.get("type") == "text" else (
            segment.get("content_snapshot") or segment.get("contentSnapshot")
        )
        clean = _text(value)
        if clean:
            parts.append(clean)
    return "\n\n".join(parts).strip()


def summarize_context(context: dict[str, Any]) -> dict[str, Any]:
    """Extract only the planning facts needed by the runtime."""
    context = context if isinstance(context, dict) else {}
    state = _workflow_state(context)
    canvas = _canvas_state(context)
    nodes = canvas.get("nodes") if isinstance(canvas.get("nodes"), dict) else {}
    edges = canvas.get("edges") if isinstance(canvas.get("edges"), list) else []
    target = context.get("target") if isinstance(context.get("target"), dict) else {}
    selected_ids = canvas.get("selectedNodeIds") or canvas.get("selected_node_ids") or []
    if not isinstance(selected_ids, list):
        selected_ids = []
    selected_id = _text(
        target.get("node_id")
        or target.get("nodeId")
        or canvas.get("selectedNodeId")
        or canvas.get("selected_node_id")
        or (selected_ids[0] if selected_ids else ""),
        160,
    )
    selected_node = nodes.get(selected_id) if selected_id else None
    if not isinstance(selected_node, dict):
        selected_node = None
    selected_text_id = selected_id if selected_node and selected_node.get("type") == "text" else ""

    input_nodes = [node for node in nodes.values() if isinstance(node, dict) and node.get("type") == "input"]
    requested_result_id = _text(context.get("result_node_id") or context.get("resultNodeId"), 160)
    requested_result = nodes.get(requested_result_id) if requested_result_id else None
    if not isinstance(requested_result, dict):
        requested_result = None
    video_node = requested_result if requested_result and requested_result.get("type") == "video_inference" else None
    if not video_node and requested_result and requested_result.get("type") == "video":
        upstream_video_id = next((
            _text(edge.get("from"), 160)
            for edge in edges
            if isinstance(edge, dict)
            and _text(edge.get("to"), 160) == requested_result_id
            and isinstance(nodes.get(_text(edge.get("from"), 160)), dict)
            and nodes[_text(edge.get("from"), 160)].get("type") == "video_inference"
        ), "")
        video_node = nodes.get(upstream_video_id)
    if not video_node and selected_node and selected_node.get("type") == "video_inference":
        video_node = selected_node
    if not video_node and selected_node and selected_node.get("type") == "video":
        upstream_video_id = next((
            _text(edge.get("from"), 160)
            for edge in edges
            if isinstance(edge, dict)
            and _text(edge.get("to"), 160) == selected_id
            and isinstance(nodes.get(_text(edge.get("from"), 160)), dict)
            and nodes[_text(edge.get("from"), 160)].get("type") == "video_inference"
        ), "")
        video_node = nodes.get(upstream_video_id)
    if not video_node and selected_id:
        connected_video_id = next((
            _text(edge.get("to"), 160)
            for edge in edges
            if isinstance(edge, dict)
            and _text(edge.get("from"), 160) == selected_id
            and isinstance(nodes.get(_text(edge.get("to"), 160)), dict)
            and nodes[_text(edge.get("to"), 160)].get("type") == "video_inference"
        ), "")
        video_node = nodes.get(connected_video_id)
    if not isinstance(video_node, dict):
        video_node = None
    video_node_id = _text((video_node or {}).get("id"), 160)
    task_domain = "video" if video_node else "image"

    requested_input_has_context = any(
        isinstance(edge, dict)
        and _text(edge.get("to"), 160) == requested_result_id
        and isinstance(nodes.get(_text(edge.get("from"), 160)), dict)
        and nodes[_text(edge.get("from"), 160)].get("type") in {"text", "image"}
        for edge in edges
    )
    input_node = (
        requested_result
        if requested_result
        and requested_result.get("type") == "input"
        and (
            requested_result_id != "input"
            or selected_id == requested_result_id
            or requested_input_has_context
        )
        else None
    )
    if not input_node and requested_result and requested_result.get("type") in {"output", "file_output"}:
        upstream_id = next((
            _text(edge.get("from"), 160)
            for edge in edges
            if isinstance(edge, dict)
            and _text(edge.get("to"), 160) == requested_result_id
            and isinstance(nodes.get(_text(edge.get("from"), 160)), dict)
            and nodes[_text(edge.get("from"), 160)].get("type") == "input"
        ), "")
        input_node = nodes.get(upstream_id)
    if not input_node and selected_node and selected_node.get("type") == "input":
        input_node = selected_node
    if not input_node and selected_id:
        connected_input_id = next((
            _text(edge.get("to"), 160)
            for edge in edges
            if isinstance(edge, dict)
            and _text(edge.get("from"), 160) == selected_id
            and isinstance(nodes.get(_text(edge.get("to"), 160)), dict)
            and nodes[_text(edge.get("to"), 160)].get("type") == "input"
        ), "")
        input_node = nodes.get(connected_input_id)
    if not input_node:
        connected_input_ids = {
            _text(edge.get("to"), 160)
            for edge in edges
            if isinstance(edge, dict)
            and isinstance(nodes.get(_text(edge.get("from"), 160)), dict)
            and nodes[_text(edge.get("from"), 160)].get("type") in {"text", "image"}
        }
        input_node = next((node for node in input_nodes if node.get("id") in connected_input_ids and node.get("id") != "input"), None)
    if not input_node:
        input_node = next((node for node in input_nodes if node.get("id") != "input"), None)
    if not input_node:
        input_node = next((node for node in input_nodes if node.get("id") == "input"), input_nodes[0] if input_nodes else None)
    input_node_id = _text((input_node or {}).get("id"), 160)
    resolved_result_id = requested_result_id
    if not requested_result or (
        requested_result.get("type") == "input"
        and _text(requested_result.get("id"), 160) != input_node_id
    ):
        resolved_result_id = input_node_id
    prompt_target_id = video_node_id or input_node_id
    connected_text_ids = [
        _text(edge.get("from"), 160)
        for edge in edges
        if isinstance(edge, dict)
        and _text(edge.get("to"), 160) == prompt_target_id
        and isinstance(nodes.get(_text(edge.get("from"), 160)), dict)
        and nodes[_text(edge.get("from"), 160)].get("type") == "text"
    ]
    current_prompt = _text(
        context.get("current_prompt")
        or context.get("prompt")
        or target.get("text")
        or _node_text(selected_node)
        or (_node_text(nodes.get(connected_text_ids[0])) if connected_text_ids else "")
        or state.get("prompt")
    )
    provider = _text(context.get("provider") or state.get("provider") or "gpt", 40).lower() or "gpt"
    params = context.get("params") if isinstance(context.get("params"), dict) else state.get("params")
    if not isinstance(params, dict):
        params = {}
    output = context.get("output") if isinstance(context.get("output"), dict) else state.get("output")
    if not isinstance(output, dict):
        output = {}
    canvas_image_nodes = [
        node for node in nodes.values()
        if isinstance(node, dict) and node.get("type") == "image" and (
            node.get("imageUrl") or node.get("image_url") or node.get("imageData") or node.get("image_data")
        )
    ]
    reference_items = context.get("referenced_images") if isinstance(context.get("referenced_images"), list) else []
    raw_reference_ids = (
        context.get("referenced_image_node_ids")
        if isinstance(context.get("referenced_image_node_ids"), list)
        else []
    )
    reference_meta: dict[str, dict[str, str]] = {}
    reference_ids: list[str] = []
    for item in reference_items[:8]:
        if not isinstance(item, dict):
            continue
        node_id = _text(item.get("source_node_id") or item.get("sourceNodeId") or item.get("node_id"), 160)
        if not node_id:
            continue
        reference_meta[node_id] = {
            "id": _text(item.get("id") or f"image{len(reference_meta) + 1}", 80),
            "label": _text(item.get("label") or item.get("name") or node_id, 240),
            "source_node_id": node_id,
        }
        reference_ids.append(node_id)
    for value in raw_reference_ids[:8]:
        node_id = _text(value, 160)
        if node_id:
            reference_ids.append(node_id)
    reference_ids = list(dict.fromkeys(reference_ids))[:8]
    video_first_frame_id = ""
    if video_node_id:
        video_first_frame_id = next((
            _text(edge.get("from"), 160)
            for edge in edges
            if isinstance(edge, dict)
            and _text(edge.get("to"), 160) == video_node_id
            and isinstance(nodes.get(_text(edge.get("from"), 160)), dict)
            and nodes[_text(edge.get("from"), 160)].get("type") in {"image", "layout", "pose"}
            and _text(edge.get("inputRole") or edge.get("input_role") or "first_frame", 80) == "first_frame"
        ), "")
        if video_first_frame_id and not reference_ids:
            reference_ids.append(video_first_frame_id)
    referenced_image_nodes = [
        node for node in canvas_image_nodes
        if _text(node.get("id"), 160) in reference_ids
    ]
    image_nodes = referenced_image_nodes if reference_ids else canvas_image_nodes
    resolved_reference_ids = [_text(node.get("id"), 160) for node in referenced_image_nodes]
    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "canvas_image_node_count": len(canvas_image_nodes),
        "image_node_count": len(image_nodes),
        "image_node_ids": [_text(node.get("id"), 160) for node in image_nodes[:8]],
        "referenced_image_count": len(referenced_image_nodes),
        "referenced_image_node_ids": resolved_reference_ids,
        "reference_ratio": _nearest_reference_ratio(referenced_image_nodes[0]) if referenced_image_nodes else "",
        "referenced_images": [
            reference_meta.get(node_id) or {
                "id": f"image{index + 1}",
                "label": node_id,
                "source_node_id": node_id,
            }
            for index, node_id in enumerate(resolved_reference_ids)
        ],
        "selected_node_id": selected_id,
        "selected_text_node_id": selected_text_id,
        "connected_text_node_id": connected_text_ids[0] if connected_text_ids else "",
        "task_domain": task_domain,
        "model_family": "minimax_h3" if task_domain == "video" else "",
        "generation_node_id": video_node_id or input_node_id or "input",
        "video_node_id": video_node_id,
        "first_frame_node_id": video_first_frame_id or (reference_ids[0] if task_domain == "video" and reference_ids else ""),
        "first_frame_connected": bool(video_first_frame_id),
        "video_mode": _text((video_node or {}).get("mode") or params.get("mode") or "image_to_video", 80),
        "input_node_id": video_node_id or input_node_id or "input",
        "result_node_id": video_node_id or resolved_result_id or input_node_id or "input",
        "current_prompt": current_prompt,
        "provider": (
            "minimax_h3"
            if task_domain == "video"
            else (provider if provider in {"gpt", "google", "comfy", "upscale"} else "gpt")
        ),
        "params": copy.deepcopy(params),
        "archive_enabled": _bool(
            output.get("archive_enabled", output.get("archiveEnabled")),
            True,
        ),
        "telegram_enabled": _bool(
            output.get("telegram_enabled", output.get("telegramEnabled")),
            True,
        ),
    }


_GENERATION_TERMS = re.compile(
    r"(?:生成|出图|做图|渲染|跑图|执行生图|开始制作|generate|render|create\s+(?:an?\s+)?image)",
    re.I,
)
_NO_GENERATION_TERMS = re.compile(r"(?:只(?:要|需).{0,8}(?:提示词|计划|分析)|不要出图|不生成|先别生成|仅优化|only\s+(?:plan|prompt))", re.I)
_IMAGE_ANALYSIS_TERMS = re.compile(r"(?:分析.{0,4}(?:图片|参考图)|看图|读图|图片分析|参考图分析|analy[sz]e\s+(?:the\s+)?image)", re.I)


def _wants_generation(goal: str, options: dict[str, Any]) -> bool:
    if _NO_GENERATION_TERMS.search(goal):
        return False
    if "auto_generate" in options:
        return _bool(options.get("auto_generate"), False)
    return bool(_GENERATION_TERMS.search(goal))


_SUPPORTED_RATIOS = {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "9:21", "21:9"}
_COUNT_WORDS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8}


def _nearest_reference_ratio(node: dict[str, Any] | None) -> str:
    if not isinstance(node, dict):
        return ""
    raw_ratio = node.get("aspectRatio") or node.get("aspect_ratio")
    try:
        aspect = float(raw_ratio or 0)
    except (TypeError, ValueError):
        aspect = 0
    if aspect <= 0:
        try:
            width = float(node.get("width") or 0)
            height = float(node.get("height") or 0)
            aspect = width / height if width > 0 and height > 0 else 0
        except (TypeError, ValueError, ZeroDivisionError):
            aspect = 0
    if aspect <= 0:
        return ""
    ratios = {
        "1:1": 1,
        "2:3": 2 / 3,
        "3:2": 3 / 2,
        "3:4": 3 / 4,
        "4:3": 4 / 3,
        "4:5": 4 / 5,
        "5:4": 5 / 4,
        "9:16": 9 / 16,
        "16:9": 16 / 9,
        "9:21": 9 / 21,
        "21:9": 21 / 9,
    }
    return min(ratios, key=lambda key: abs(ratios[key] - aspect))


def _base_generation_decision(summary: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    params = summary.get("params") if isinstance(summary.get("params"), dict) else {}
    options = options if isinstance(options, dict) else {}
    provider = _text(summary.get("provider") or "gpt", 40).lower()
    if provider not in {"gpt", "google"}:
        provider = "gpt"
    ratio = _text(summary.get("reference_ratio") or params.get("ratio") or "1:1", 24).replace("：", ":")
    if ratio not in _SUPPORTED_RATIOS:
        ratio = "1:1"
    resolution = _text(params.get("resolution") or "2k", 24).lower()
    if resolution not in {"1k", "2k", "4k"}:
        resolution = "2k"
    quality = _text(params.get("quality") or "auto", 24).lower()
    if quality not in {"auto", "low", "medium", "high"}:
        quality = "auto"
    image_count = _int(
        options.get("image_count", params.get("imageCount", params.get("image_count", 1))),
        1,
        1,
        8,
    )
    if provider == "google":
        image_count = 1
    return {
        "provider": provider,
        "image_count": image_count,
        "ratio": ratio,
        "resolution": resolution,
        "quality": quality,
        "archive_enabled": bool(summary.get("archive_enabled", True)),
        "telegram_enabled": bool(summary.get("telegram_enabled", True)),
    }


def _decision_summary(decision: dict[str, Any]) -> str:
    provider = "Google" if decision.get("provider") == "google" else "GPT"
    quality_labels = {"auto": "自动质量", "low": "低质量", "medium": "中等质量", "high": "高质量"}
    parts = [
        provider,
        _text(decision.get("ratio") or "1:1", 24),
        _text(decision.get("resolution") or "2k", 24).upper(),
    ]
    if provider == "GPT":
        parts.append(quality_labels.get(_text(decision.get("quality"), 24).lower(), "自动质量"))
    parts.extend([
        f"{_int(decision.get('image_count'), 1, 1, 8)} 张",
        "自动归档" if decision.get("archive_enabled") else "不归档",
        "发送 Telegram" if decision.get("telegram_enabled") else "不发送 Telegram",
    ])
    return " · ".join(parts)


def _decision_attention(decision: dict[str, Any]) -> list[str]:
    attention: list[str] = []
    if _text(decision.get("resolution"), 24).lower() == "4k":
        attention.append("4K 高分辨率")
    image_count = _int(decision.get("image_count"), 1, 1, 8)
    if image_count > 1:
        attention.append(f"{image_count} 张批量生成")
    if decision.get("telegram_enabled"):
        attention.append("发送 Telegram")
    return attention


def infer_generation_decision(
    instruction: str,
    summary: dict[str, Any],
    *,
    base: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Resolve explicit task language over conservative canvas defaults."""
    text = _text(instruction, 2_000)
    lowered = text.lower()
    decision = _base_generation_decision(summary, options)
    if isinstance(base, dict):
        for key in (
            "provider",
            "image_count",
            "ratio",
            "resolution",
            "quality",
            "archive_enabled",
            "telegram_enabled",
        ):
            if key in base:
                decision[key] = copy.deepcopy(base[key])

    recognized: list[str] = []
    basis: list[str] = []
    notes: list[str] = []

    provider_matches: list[tuple[int, str, str]] = []
    for pattern, value, label in (
        (r"(?:google|gemini|谷歌)", "google", "Google"),
        (r"(?:gpt|openai|codex)", "gpt", "GPT"),
    ):
        provider_matches.extend((match.start(), value, label) for match in re.finditer(pattern, lowered, re.I))
    provider_explicit = bool(provider_matches)
    if provider_matches:
        _, provider, provider_label = max(provider_matches, key=lambda item: item[0])
        decision["provider"] = provider
        recognized.append("provider")
        basis.append(provider_label)

    ratio = ""
    ratio_label = ""
    ratio_terms = (
        (r"(?:超宽|电影宽幅|影院宽幅|ultrawide)", "21:9", "超宽画幅"),
        (r"(?:横版|横图|横向|landscape)", "16:9", "横版"),
        (r"(?:竖版|竖图|竖向|portrait)", "9:16", "竖版"),
        (r"(?:方图|方形|正方形|square)", "1:1", "方形"),
    )
    for pattern, value, label in ratio_terms:
        if re.search(pattern, lowered, re.I):
            ratio, ratio_label = value, label
    ratio_matches = list(re.finditer(
        r"(?<!\d)(1|2|3|4|5|9|16|21)\s*[:：比x×]\s*(1|2|3|4|5|9|16|21)(?!\d)",
        text,
        re.I,
    ))
    if ratio_matches:
        match = ratio_matches[-1]
        candidate = f"{match.group(1)}:{match.group(2)}"
        if candidate in _SUPPORTED_RATIOS:
            ratio, ratio_label = candidate, candidate
    if ratio:
        decision["ratio"] = ratio
        recognized.append("ratio")
        basis.append(ratio_label)

    resolution_matches = list(re.finditer(r"(?<!\d)([124])\s*k(?![a-z0-9])", lowered, re.I))
    if resolution_matches:
        resolution = f"{resolution_matches[-1].group(1)}k"
        decision["resolution"] = resolution
        recognized.append("resolution")
        basis.append(resolution.upper())

    quality = ""
    quality_label = ""
    if re.search(r"(?:最高质量|高质量|质量.{0,2}(?:高|最好)|精细模式)", text, re.I):
        quality, quality_label = "high", "高质量"
    elif re.search(r"(?:中等质量|标准质量|质量.{0,2}中)", text, re.I):
        quality, quality_label = "medium", "中等质量"
    elif re.search(r"(?:低质量|质量.{0,2}低|草图质量|快速预览)", text, re.I):
        quality, quality_label = "low", "低质量"
    elif re.search(r"(?:自动质量|质量自动)", text, re.I):
        quality, quality_label = "auto", "自动质量"
    if quality:
        decision["quality"] = quality
        recognized.append("quality")
        basis.append(quality_label)

    count_matches = list(re.finditer(
        r"([1-8一二两三四五六七八])\s*(?:张|幅|版(?:图)?|个(?:版本|方案|结果))",
        text,
        re.I,
    ))
    requested_count = 0
    if count_matches:
        raw_count = count_matches[-1].group(1)
        requested_count = int(raw_count) if raw_count.isdigit() else _COUNT_WORDS.get(raw_count, 1)
        decision["image_count"] = _int(requested_count, 1, 1, 8)
        recognized.append("image_count")
        basis.append(f"{decision['image_count']} 张")

    archive_negative = re.search(r"(?:不|不要|关闭|取消).{0,4}(?:自动)?归档|不归档", text, re.I)
    archive_positive = re.search(r"(?:开启|打开|自动|需要|保留).{0,4}归档|归档.{0,3}(?:开启|打开)", text, re.I)
    if archive_negative:
        decision["archive_enabled"] = False
        recognized.append("archive_enabled")
        basis.append("不归档")
    elif archive_positive:
        decision["archive_enabled"] = True
        recognized.append("archive_enabled")
        basis.append("自动归档")

    telegram_name = r"(?:telegram|tg|电报)"
    telegram_negative = re.search(
        rf"(?:不|不要|关闭|取消|停止)(?:再)?\s*(?:发送|发到|发|同步|推送)?\s*(?:到)?\s*{telegram_name}|"
        rf"{telegram_name}\s*(?:关闭|取消|不发|不要发送?)",
        text,
        re.I,
    )
    telegram_positive = re.search(
        rf"(?:发送|发到|发|同步|推送|开启|打开)\s*(?:到)?\s*{telegram_name}|"
        rf"{telegram_name}\s*(?:发送|同步|开启|打开)",
        text,
        re.I,
    )
    if telegram_negative:
        decision["telegram_enabled"] = False
        recognized.append("telegram_enabled")
        basis.append("不发送 Telegram")
    elif telegram_positive:
        decision["telegram_enabled"] = True
        recognized.append("telegram_enabled")
        basis.append("发送 Telegram")

    if decision.get("provider") == "google" and _int(decision.get("image_count"), 1, 1, 8) > 1:
        if provider_explicit:
            decision["image_count"] = 1
            notes.append("Google 模式单次固定生成 1 张")
        else:
            decision["provider"] = "gpt"
            basis.append("GPT 批量生成")

    decision["image_count"] = _int(decision.get("image_count"), 1, 1, 8)
    if decision.get("provider") == "google":
        decision["image_count"] = 1
    decision["decision_basis"] = [
        f"已采用：{'、'.join(dict.fromkeys(basis))}"
        if basis
        else (
            f"沿用参考图画幅 {decision.get('ratio')}，其余采用当前节点设置"
            if summary.get("reference_ratio")
            else "沿用当前模型节点设置"
        )
    ]
    decision["decision_notes"] = notes
    decision["decision_attention"] = _decision_attention(decision)
    decision["requires_attention"] = bool(decision["decision_attention"])
    decision["decision_summary"] = _decision_summary(decision)
    return decision, list(dict.fromkeys(recognized))


def _generation_step_description(decision: dict[str, Any]) -> str:
    provider = "Google" if decision.get("provider") == "google" else "GPT"
    return (
        f"使用 {provider}，按 {decision.get('ratio') or '1:1'}、"
        f"{_text(decision.get('resolution') or '2k', 24).upper()} 生成 "
        f"{_int(decision.get('image_count'), 1, 1, 8)} 张；"
        f"归档{'开启' if decision.get('archive_enabled') else '关闭'}，"
        f"Telegram {'开启' if decision.get('telegram_enabled') else '关闭'}。"
    )


def _video_generation_decision(summary: dict[str, Any]) -> dict[str, Any]:
    params = summary.get("params") if isinstance(summary.get("params"), dict) else {}

    def value(*keys: str, fallback: Any = None) -> Any:
        for key in keys:
            if params.get(key) not in {None, ""}:
                return params.get(key)
        return fallback

    try:
        duration_seconds = float(value("duration_seconds", "durationSeconds", fallback=15))
    except (TypeError, ValueError):
        duration_seconds = 15.0
    duration_seconds = max(4.0, min(15.0, duration_seconds))
    try:
        pixel_budget_mp = float(value("pixel_budget_mp", "pixelBudgetMp", fallback=0.8))
    except (TypeError, ValueError):
        pixel_budget_mp = 0.8
    aspect_ratio = _text(value("aspect_ratio", "aspectRatio", fallback="3:4"), 24).replace("：", ":")
    if aspect_ratio not in {"16:9", "9:16", "3:4", "4:3", "2:3", "3:2", "1:1", "21:9", "9:21"}:
        aspect_ratio = "3:4"
    acceleration_mode = _text(
        value("acceleration_mode", "accelerationMode", fallback="first_block_cache"),
        40,
    ).lower()
    if acceleration_mode not in {"off", "first_block_cache", "sol_attn", "combined"}:
        acceleration_mode = "first_block_cache"
    source_mode = _text(summary.get("video_mode") or value("mode", fallback="image_to_video"), 80).lower()
    h3_mode = "I2VA" if source_mode == "image_to_video" else "Ref2VA"
    width = _int(value("width", fallback=0), 0, 0, 8192)
    height = _int(value("height", fallback=0), 0, 0, 8192)
    decision = {
        "task_domain": "video",
        "provider": "minimax_h3",
        "mode": source_mode,
        "h3_mode": h3_mode,
        "duration_seconds": duration_seconds,
        "aspect_ratio": aspect_ratio,
        "pixel_budget_mp": round(max(0.1, min(8.0, pixel_budget_mp)), 3),
        "width": width,
        "height": height,
        "acceleration_mode": acceleration_mode,
        "archive_enabled": True,
        "telegram_enabled": bool(summary.get("telegram_enabled", False)),
        "decision_basis": ["读取 MiniMax H3 视频节点设置"],
        "decision_notes": [],
        "decision_attention": [],
        "requires_attention": False,
    }
    duration_label = f"{duration_seconds:g}"
    size_label = f" · {width}x{height}" if width and height else ""
    decision["decision_summary"] = (
        f"MiniMax H3 · {h3_mode} · {duration_label} 秒 · {aspect_ratio} · "
        f"{decision['pixel_budget_mp']:g} MP{size_label}"
    )
    return decision


def _video_generation_step_description(decision: dict[str, Any]) -> str:
    return (
        f"使用 MiniMax H3 {decision.get('h3_mode') or 'I2VA'}，按 "
        f"{decision.get('aspect_ratio') or '3:4'}、{float(decision.get('duration_seconds') or 15):g} 秒、"
        f"{float(decision.get('pixel_budget_mp') or 0.8):g} MP 提交；"
        "其余推理参数沿用视频节点设置。"
    )


def _step(step_id: str, kind: str, title: str, description: str, *, tool: str, approval: bool = False) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "kind": kind,
        "tool": tool,
        "title": title,
        "description": description,
        "status": "pending",
        "requires_approval": bool(approval),
    }


def build_plan(goal: str, context: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a conservative, bounded first-pass plan."""
    goal = _text(goal, 2_000)
    if not goal:
        raise ValueError("请输入希望 Agent 完成的任务")
    options = options if isinstance(options, dict) else {}
    summary = summarize_context(context)
    wants_generation = _wants_generation(goal, options)
    is_video = summary.get("task_domain") == "video"
    decision = _video_generation_decision(summary) if is_video else infer_generation_decision(goal, summary, options=options)[0]
    wants_analysis = bool(
        summary["image_node_count"]
        and (
            summary["referenced_image_count"]
            or _IMAGE_ANALYSIS_TERMS.search(goal)
        )
    )
    scope = _text(options.get("scope") or "selection", 32).lower()
    if scope not in {"selection", "canvas"}:
        scope = "selection"

    if is_video:
        if not summary.get("first_frame_node_id"):
            raise ValueError("H3 I2VA Agent 需要视频节点已连接首帧，或在目标中用 @ 引用一张画布图片")
        steps: list[dict[str, Any]] = [
            _step(
                "inspect_canvas",
                "inspect_canvas",
                "读取 H3 视频上下文",
                f"检查 MiniMax H3 节点、首帧连接和 {decision.get('duration_seconds'):g} 秒输出设置。",
                tool="read_canvas",
            )
        ]
        if not summary.get("first_frame_connected"):
            steps.append(_step(
                "connect_first_frame",
                "connect_nodes",
                "连接 H3 首帧",
                "把 @ 引用的图片连接为 MiniMax H3 视频节点首帧。",
                tool="connect_nodes",
            ))
        if summary.get("first_frame_node_id"):
            steps.append(_step(
                "analyze_images",
                "analyze_images",
                "分析 H3 首帧",
                "分析已连接的首帧，提取人物、场景、构图和可连续运动的视觉锚点。",
                tool="analyze_image",
            ))
        if not _bool(options.get("skip_prompt_rewrite"), False):
            steps.append(_step(
                "compile_h3_prompt",
                "compile_h3_prompt",
                "编译 H3 I2VA 提示词",
                "按照 MiniMax H3 官方 I2VA 结构生成时间线、声景和配乐字段，并完成格式校验。",
                tool="compile_h3_prompt",
            ))
        steps.append(_step(
            "apply_prompt",
            "apply_prompt_to_input",
            "写入 H3 提示词",
            "更新视频节点已连接的文本节点；没有文本节点时自动创建并连接。",
            tool="create_or_update_text_node",
        ))
        if wants_generation:
            steps.extend([
                _step(
                    "submit_video_generation",
                    "submit_video_generation",
                    "提交视频生成",
                    _video_generation_step_description(decision),
                    tool="submit_video_generation",
                    approval=True,
                ),
                _step(
                    "monitor_generation",
                    "monitor_generation",
                    "跟踪视频结果",
                    "持续读取现有 H3 任务状态，直到视频完成归档或任务失败。",
                    tool="get_generation_status",
                ),
            ])
        steps = steps[:MAX_PLAN_STEPS]
        return {
            "schema_version": AGENT_SCHEMA_VERSION,
            "plan_id": f"plan_{uuid.uuid4().hex[:12]}",
            "summary": "将按 MiniMax H3 官方 I2VA 规范整理提示词、更新画布" + ("并提交视频。" if wants_generation else "。"),
            "goal": goal,
            "scope": scope,
            "task_domain": "video",
            "artifact_type": "video",
            "steps": steps,
            "approval_required": True,
            "generation_requested": wants_generation,
            "execution_policy": {
                "supervised": True,
                "max_steps": MAX_PLAN_STEPS,
                "max_generation_rounds": MAX_GENERATION_ROUNDS,
                "destructive_tools_enabled": False,
                "settings_write_enabled": False,
                "direct_telegram_enabled": False,
            },
            "confirmation": decision,
        }

    steps: list[dict[str, Any]] = [
        _step(
            "inspect_canvas",
            "inspect_canvas",
            "读取画布上下文",
            (
                f"检查 {summary['node_count']} 个节点、{summary['edge_count']} 条连接和当前输出设置"
                + (f"，确认 {summary['referenced_image_count']} 个 @ 图片引用。" if summary["referenced_image_count"] else "。")
            ),
            tool="read_canvas",
        )
    ]
    if wants_analysis:
        steps.append(_step(
            "analyze_images",
            "analyze_images",
            "分析参考图",
            (
                f"分析 @ 引用的 {summary['referenced_image_count']} 个图片节点，提取可执行的视觉方向。"
                if summary["referenced_image_count"]
                else f"读取当前画布中的 {summary['image_node_count']} 个图片节点，提取可执行的视觉方向。"
            ),
            tool="analyze_image",
        ))
    if not _bool(options.get("skip_prompt_rewrite"), False):
        steps.append(_step(
            "rewrite_prompt",
            "rewrite_prompt",
            "整理执行提示词",
            "结合当前文本、用户目标和参考图分析，生成可投喂的正式提示词。",
            tool="generate_prompt_version",
        ))

    if wants_generation:
        steps.append(_step(
            "apply_prompt",
            "apply_prompt_to_input",
            "写入模型提示词",
            "更新已连接文本节点；没有可用文本节点时创建并连接一个新节点。",
            tool="create_or_update_text_node",
        ))
    elif summary["selected_text_node_id"]:
        steps.append(_step(
            "apply_prompt",
            "update_text_node",
            "更新当前文本节点",
            "把整理后的提示词写回当前选择的文本节点。",
            tool="update_text_node",
        ))
    else:
        steps.append(_step(
            "apply_prompt",
            "apply_prompt_to_input",
            "创建提示词节点",
            "创建文本节点并连接到主模型节点。",
            tool="create_text_node",
        ))

    if wants_generation:
        steps.append(_step(
            "submit_generation",
            "submit_generation",
            "提交图片生成",
            _generation_step_description(decision),
            tool="submit_generation",
            approval=True,
        ))
        steps.append(_step(
            "monitor_generation",
            "monitor_generation",
            "跟踪生成结果",
            "持续读取现有任务状态，直到归档和 Telegram 阶段完成。",
            tool="get_generation_status",
        ))

    steps = steps[:MAX_PLAN_STEPS]
    return {
        "schema_version": AGENT_SCHEMA_VERSION,
        "plan_id": f"plan_{uuid.uuid4().hex[:12]}",
        "summary": "将先整理提示词，再修改画布" + ("并提交生成。" if wants_generation else "。"),
        "goal": goal,
        "scope": scope,
        "task_domain": "image",
        "artifact_type": "image",
        "steps": steps,
        "approval_required": True,
        "generation_requested": wants_generation,
        "execution_policy": {
            "supervised": True,
            "max_steps": MAX_PLAN_STEPS,
            "max_generation_rounds": MAX_GENERATION_ROUNDS,
            "destructive_tools_enabled": False,
            "settings_write_enabled": False,
            "direct_telegram_enabled": False,
        },
        "confirmation": decision,
    }


class AgentRuntime:
    def __init__(
        self,
        *,
        task_getter: Callable[[str], dict[str, Any] | None] = get_task,
        task_canceler: Callable[..., Any] = update_task_status,
        prompt_refiner: Callable[..., dict[str, Any]] = polish_prompt,
    ) -> None:
        agent_store.init_agent_store()
        self._task_getter = task_getter
        self._task_canceler = task_canceler
        self._prompt_refiner = prompt_refiner
        self._lock = threading.RLock()
        self._conditions: dict[str, threading.Condition] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._action_results: dict[tuple[str, str], dict[str, Any]] = {}

    def recover_after_restart(self) -> int:
        return agent_store.mark_interrupted_runs()

    def _condition(self, run_id: str) -> threading.Condition:
        with self._lock:
            condition = self._conditions.get(run_id)
            if condition is None:
                condition = threading.Condition(self._lock)
                self._conditions[run_id] = condition
            return condition

    def _require_run(self, run_id: str) -> dict[str, Any]:
        run = agent_store.get_run(_text(run_id, 160))
        if not run:
            raise AgentRunNotFound("Agent 运行不存在")
        return run

    def _emit(
        self,
        run_id: str,
        event_type: str,
        *,
        status: str = "",
        step_index: int | None = None,
        message: str = "",
        payload: Any = None,
    ) -> dict[str, Any]:
        return agent_store.append_event(
            run_id,
            event_type,
            status=status,
            step_index=step_index,
            message=message,
            payload=payload,
        )

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = payload if isinstance(payload, dict) else {}
        goal = _text(payload.get("goal") or payload.get("message"), 2_000)
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
        client = payload.get("client") if isinstance(payload.get("client"), dict) else {}
        client_task_id = _text(client.get("agent_task_id"), 160)
        plan = build_plan(goal, context, options)
        request = {
            "goal": goal,
            "options": copy.deepcopy(options),
            "client": copy.deepcopy(client),
        }
        with self._lock:
            if client_task_id:
                existing = agent_store.find_run_by_client_task_id(client_task_id)
                if existing:
                    return self.get_run(existing["run_id"])
            run_id = f"agent_{int(time.time())}_{uuid.uuid4().hex[:10]}"
            run = agent_store.create_run(
                run_id,
                goal=goal,
                request=request,
                context=context,
                plan=plan,
            )
            self._emit(
                run_id,
                "plan_created",
                status="awaiting_approval",
                message=f"已生成 {len(plan.get('steps') or [])} 步执行计划，等待确认。",
                payload={"plan": plan},
            )
        return self.get_run(run_id)

    def get_run(self, run_id: str, *, events_since: int = 0, event_limit: int = 240) -> dict[str, Any]:
        run = self._require_run(run_id)
        events = agent_store.list_events(run_id, since=events_since, limit=event_limit)
        return {
            "ok": True,
            **run,
            "events": events,
            "latest_event": agent_store.latest_event(run_id),
            "capabilities": {
                "can_approve": run.get("status") == "awaiting_approval",
                "can_revise": (
                    run.get("status") == "awaiting_approval"
                    and bool((run.get("plan") or {}).get("generation_requested"))
                    and (run.get("plan") or {}).get("task_domain") != "video"
                ),
                "can_pause": run.get("status") in {"running", "waiting_for_action"},
                "can_resume": run.get("status") == "paused",
                "can_cancel": run.get("status") not in TERMINAL_RUN_STATUSES,
                "can_rollback": run.get("status") in {"succeeded", "failed", "canceled", "paused"},
            },
        }

    def list_runs(self, *, limit: int = 20, offset: int = 0, status: str = "") -> dict[str, Any]:
        runs = agent_store.list_runs(limit=limit, offset=offset, status=status)
        return {"ok": True, "runs": runs, "count": len(runs)}

    def delete_run(self, run_id: str) -> dict[str, Any]:
        """Delete an inactive run without touching generated output files."""
        clean_id = _text(run_id, 160)
        with self._lock:
            run = self._require_run(clean_id)
            status = str(run.get("status") or "")
            thread = self._threads.get(clean_id)
            if status not in (TERMINAL_RUN_STATUSES | {"awaiting_approval"}):
                raise AgentRunConflict("运行中的任务需先取消或等待完成后再删除")
            if thread and thread.is_alive():
                raise AgentRunConflict("任务线程仍在结束处理中，请稍后再删除")
            if not agent_store.delete_run(clean_id):
                raise AgentRunNotFound("Agent 运行不存在")
            self._threads.pop(clean_id, None)
            self._conditions.pop(clean_id, None)
            stale_actions = [key for key in self._action_results if key[0] == clean_id]
            for key in stale_actions:
                self._action_results.pop(key, None)
        return {"ok": True, "deleted": True, "run_id": clean_id}

    def approve_run(self, run_id: str, approval: dict[str, Any] | None = None) -> dict[str, Any]:
        run = self._require_run(run_id)
        if run.get("status") != "awaiting_approval":
            raise AgentRunConflict("当前运行不在等待确认状态")
        request = dict(run.get("request") or {})
        request["approval"] = approval if isinstance(approval, dict) else {}
        control = dict(run.get("control") or {})
        control.update({
            "pause_requested": False,
            "cancel_requested": False,
            "rollback_requested": False,
            "recovered_after_restart": False,
            "operation": "execute",
        })
        agent_store.update_run(
            run_id,
            request=request,
            control=control,
            status="running",
            started_at=int(time.time()),
            error="",
        )
        self._emit(run_id, "run_approved", status="running", message="执行计划已确认，Agent 开始工作。")
        self._spawn(run_id, self._execute_run)
        return self.get_run(run_id)

    def revise_run(self, run_id: str, instruction: str) -> dict[str, Any]:
        run = self._require_run(run_id)
        if run.get("status") != "awaiting_approval":
            raise AgentRunConflict("只有等待确认的计划可以调整")
        plan = copy.deepcopy(run.get("plan") or {})
        if not plan.get("generation_requested"):
            raise AgentRunConflict("本轮计划不包含图片生成参数")
        instruction = _text(instruction, 1_000)
        if not instruction:
            raise ValueError("请输入要调整的要求")

        summary = summarize_context(run.get("context") or {})
        current = plan.get("confirmation") if isinstance(plan.get("confirmation"), dict) else {}
        decision, recognized = infer_generation_decision(instruction, summary, base=current)
        if not recognized:
            raise ValueError("没有识别到生成参数，请直接说明模型、画幅、分辨率、质量、数量、归档或 Telegram 要求")

        plan["confirmation"] = decision
        steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
        for step in steps:
            if isinstance(step, dict) and step.get("kind") == "submit_generation":
                step["description"] = _generation_step_description(decision)
        plan["steps"] = steps

        request = copy.deepcopy(run.get("request") or {})
        revisions = request.get("decision_revisions") if isinstance(request.get("decision_revisions"), list) else []
        revisions.append({
            "instruction": instruction,
            "recognized_fields": recognized,
            "created_at": int(time.time()),
        })
        request["decision_revisions"] = revisions[-12:]
        agent_store.update_run(run_id, plan=plan, request=request)
        self._emit(
            run_id,
            "plan_revised",
            status="awaiting_approval",
            message=f"Agent 已更新生成决策：{decision.get('decision_summary') or _decision_summary(decision)}",
            payload={"confirmation": decision, "recognized_fields": recognized},
        )
        return self.get_run(run_id)

    def _spawn(self, run_id: str, target: Callable[[str], None]) -> None:
        with self._lock:
            current = self._threads.get(run_id)
            if current and current.is_alive():
                return

            def runner() -> None:
                try:
                    target(run_id)
                finally:
                    with self._lock:
                        if self._threads.get(run_id) is threading.current_thread():
                            self._threads.pop(run_id, None)

            thread = threading.Thread(target=runner, name=f"AgentRuntime-{run_id[-8:]}", daemon=True)
            self._threads[run_id] = thread
            thread.start()

    def _spawn_after_current(self, run_id: str, target: Callable[[str], None]) -> None:
        """Start a replacement phase after a terminal worker finishes unwinding."""
        with self._lock:
            current = self._threads.get(run_id)
            if not current or not current.is_alive():
                self._spawn(run_id, target)
                return

        def wait_then_start() -> None:
            current.join()
            self._spawn(run_id, target)

        threading.Thread(
            target=wait_then_start,
            name=f"AgentPhase-{run_id[-8:]}",
            daemon=True,
        ).start()

    def _update_step(self, run_id: str, index: int, status: str, **extra: Any) -> dict[str, Any]:
        run = self._require_run(run_id)
        plan = copy.deepcopy(run.get("plan") or {})
        steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
        if 0 <= index < len(steps):
            steps[index]["status"] = status
            steps[index].update(extra)
            plan["steps"] = steps
            agent_store.update_run(run_id, plan=plan, current_step=index)
        return plan

    def _check_control(self, run_id: str) -> dict[str, Any]:
        condition = self._condition(run_id)
        while True:
            run = self._require_run(run_id)
            control = run.get("control") if isinstance(run.get("control"), dict) else {}
            if _bool(control.get("rollback_requested"), False):
                raise AgentRunRollback("运行已切换到画布回滚")
            if _bool(control.get("cancel_requested"), False) or run.get("status") == "canceled":
                raise AgentRunCanceled("运行已取消")
            if not _bool(control.get("pause_requested"), False) and run.get("status") != "paused":
                return run
            with condition:
                condition.wait(timeout=0.5)

    def _working_state(self, run: dict[str, Any]) -> dict[str, Any]:
        result = run.get("result") if isinstance(run.get("result"), dict) else {}
        summary = summarize_context(run.get("context") or {})
        return {
            "prompt": _text(result.get("prompt") or summary.get("current_prompt") or run.get("goal")),
            "prompt_meta": copy.deepcopy(result.get("prompt_meta") if isinstance(result.get("prompt_meta"), dict) else {}),
            "text_node_id": _text(result.get("text_node_id") or summary.get("selected_text_node_id"), 160),
            "task_id": _text(result.get("task_id") or run.get("task_id"), 160),
            "analysis": copy.deepcopy(result.get("analysis") if isinstance(result.get("analysis"), dict) else {}),
            "artifact_type": _text(result.get("artifact_type") or (run.get("plan") or {}).get("artifact_type") or "image", 40),
            "video_node_id": _text(result.get("video_node_id") or summary.get("video_node_id"), 160),
        }

    def _save_working(self, run_id: str, working: dict[str, Any], **extra: Any) -> None:
        result = {
            "prompt": _text(working.get("prompt")),
            "prompt_meta": copy.deepcopy(working.get("prompt_meta") or {}),
            "text_node_id": _text(working.get("text_node_id"), 160),
            "task_id": _text(working.get("task_id"), 160),
            "analysis": copy.deepcopy(working.get("analysis") or {}),
            "artifact_type": _text(working.get("artifact_type") or "image", 40),
            "video_node_id": _text(working.get("video_node_id"), 160),
            **extra,
        }
        agent_store.update_run(run_id, result=result, task_id=result.get("task_id") or "")

    def _execute_run(self, run_id: str) -> None:
        try:
            run = self._check_control(run_id)
            plan = run.get("plan") if isinstance(run.get("plan"), dict) else {}
            steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
            if not steps:
                raise AgentRuntimeError("执行计划为空")
            working = self._working_state(run)
            self._emit(run_id, "run_started", status="running", message="Agent 正在执行已批准的计划。")
            for index, step in enumerate(steps):
                if step.get("status") == "succeeded":
                    continue
                self._check_control(run_id)
                kind = _text(step.get("kind"), 80)
                self._update_step(run_id, index, "running", started_at=int(time.time()))
                agent_store.update_run(run_id, status="running", current_step=index, waiting_action_id="")
                self._emit(
                    run_id,
                    "step_started",
                    status="running",
                    step_index=index,
                    message=_text(step.get("title") or kind, 300),
                    payload={"step": step},
                )

                step_result = self._execute_step(run_id, index, step, working)
                self._update_step(
                    run_id,
                    index,
                    "succeeded",
                    finished_at=int(time.time()),
                    output=step_result,
                )
                agent_store.update_run(run_id, current_step=index + 1, status="running", waiting_action_id="")
                self._save_working(run_id, working)
                self._emit(
                    run_id,
                    "step_completed",
                    status="succeeded",
                    step_index=index,
                    message=f"{step.get('title') or kind}完成。",
                    payload={"result": step_result},
                )

            final_result = {
                "prompt": working.get("prompt") or "",
                "prompt_meta": working.get("prompt_meta") or {},
                "text_node_id": working.get("text_node_id") or "",
                "task_id": working.get("task_id") or "",
                "analysis": working.get("analysis") or {},
                "artifact_type": working.get("artifact_type") or plan.get("artifact_type") or "image",
                "video_node_id": working.get("video_node_id") or "",
                "steps_completed": len(steps),
            }
            agent_store.update_run(
                run_id,
                status="succeeded",
                result=final_result,
                task_id=working.get("task_id") or "",
                waiting_action_id="",
                finished_at=int(time.time()),
                error="",
            )
            self._emit(run_id, "run_completed", status="succeeded", message="Agent 计划已执行完成。", payload=final_result)
        except AgentRunRollback:
            run = agent_store.get_run(run_id) or {}
            control = dict(run.get("control") or {})
            control.update({
                "pause_requested": False,
                "cancel_requested": False,
                "rollback_requested": False,
                "operation": "rollback",
            })
            agent_store.update_run(
                run_id,
                status="rolling_back",
                control=control,
                waiting_action_id="",
                error="",
            )
            self._execute_rollback(run_id)
        except AgentRunCanceled:
            current = agent_store.get_run(run_id) or {}
            agent_store.update_run(
                run_id,
                status="canceled",
                waiting_action_id="",
                finished_at=int(time.time()),
                error="运行已取消",
            )
            if current.get("status") != "canceled":
                self._emit(run_id, "run_canceled", status="canceled", message="Agent 运行已取消。")
        except Exception as exc:
            run = agent_store.get_run(run_id) or {}
            index = int(run.get("current_step") or 0)
            self._update_step(run_id, index, "failed", error=_text(exc, 2_000), finished_at=int(time.time()))
            agent_store.update_run(
                run_id,
                status="failed",
                waiting_action_id="",
                finished_at=int(time.time()),
                error=_text(exc, 2_000),
            )
            self._emit(run_id, "run_failed", status="failed", step_index=index, message=f"Agent 执行失败：{exc}")

    def _execute_step(
        self,
        run_id: str,
        index: int,
        step: dict[str, Any],
        working: dict[str, Any],
    ) -> dict[str, Any]:
        kind = _text(step.get("kind"), 80)
        run = self._require_run(run_id)
        summary = summarize_context(run.get("context") or {})
        request = run.get("request") if isinstance(run.get("request"), dict) else {}
        options = request.get("options") if isinstance(request.get("options"), dict) else {}

        if kind == "inspect_canvas":
            return {
                "task_domain": summary.get("task_domain") or "image",
                "node_count": summary["node_count"],
                "edge_count": summary["edge_count"],
                "image_node_count": summary["image_node_count"],
                "selected_node_id": summary["selected_node_id"],
                "input_node_id": summary["input_node_id"],
                "video_node_id": summary.get("video_node_id") or "",
                "first_frame_node_id": summary.get("first_frame_node_id") or "",
            }
        if kind == "rewrite_prompt":
            refined, meta = self._refine_prompt(run, working, options)
            working["prompt"] = refined
            working["prompt_meta"] = meta
            return {"prompt_preview": refined[:420], **meta}
        if kind == "monitor_generation":
            if not working.get("task_id"):
                return {"skipped": True, "reason": "没有生成任务"}
            task = self._monitor_generation(run_id, _text(working.get("task_id"), 160), index, options)
            return {
                "task_id": task.get("task_id") or working.get("task_id"),
                "status": task.get("status"),
                "result_files": task.get("result_files") or [],
                "display_error": task.get("display_error") or task.get("error") or "",
            }
        if kind in CLIENT_ACTION_KINDS:
            action = self._build_client_action(kind, run, working, summary, options)
            result = self._request_client_action(run_id, index, action)
            if result.get("ok") is False or result.get("error"):
                raise AgentRuntimeError(_text(result.get("error") or "画布动作执行失败", 2_000))
            payload = result.get("result") if isinstance(result.get("result"), dict) else result
            if kind == "analyze_images":
                analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
                candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
                selected = next((item for item in candidates if isinstance(item, dict) and _text(item.get("text"))), None)
                working["analysis"] = analysis
                if selected and summary.get("task_domain") != "video":
                    working["prompt"] = _text(selected.get("text"))
            elif kind == "compile_h3_prompt":
                compiled_prompt = _text(payload.get("prompt") or payload.get("compiled_prompt"))
                if not compiled_prompt:
                    raise AgentRuntimeError("H3 提示词编译动作没有返回可用内容")
                working["prompt"] = compiled_prompt
                working["prompt_meta"] = copy.deepcopy(payload.get("provenance") or payload.get("meta") or {})
            elif kind in {"update_text_node", "apply_prompt_to_input"}:
                working["text_node_id"] = _text(payload.get("node_id") or payload.get("nodeId") or working.get("text_node_id"), 160)
            elif kind in {"submit_generation", "submit_video_generation"}:
                task_id = _text(payload.get("task_id") or payload.get("taskId"), 160)
                if not task_id:
                    raise AgentRuntimeError("生成动作没有返回 task_id")
                working["task_id"] = task_id
                if kind == "submit_video_generation":
                    working["artifact_type"] = "video"
                    working["video_node_id"] = _text(payload.get("video_node_id") or summary.get("video_node_id"), 160)
                agent_store.update_run(run_id, task_id=task_id)
            return payload
        raise AgentRuntimeError(f"不支持的 Agent 步骤：{kind}")

    def _refine_prompt(
        self,
        run: dict[str, Any],
        working: dict[str, Any],
        options: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        current = _text(working.get("prompt"))
        goal = _text(run.get("goal"), 2_000)
        if _bool(options.get("skip_model"), False):
            fallback = current or goal
            return fallback, {"provider": "local", "model": "none", "fallback": True}
        instruction = "\n\n".join(part for part in [
            f"当前可用提示词：\n{current}" if current else "",
            f"本轮 Agent 执行目标：\n{goal}",
            "请保留用户已经明确的主体、构图、风格、比例和文字要求，输出可直接用于本次图片任务的正式提示词。",
        ] if part)
        try:
            result = self._prompt_refiner(instruction or goal, {
                "provider": options.get("provider"),
                "model": options.get("model"),
                "reasoning_effort": options.get("reasoning_effort") or "medium",
            })
            refined = _text(
                result.get("full_prompt")
                or result.get("compact_prompt")
                or result.get("prompt")
                or result.get("rewritten_prompt")
            )
            if not refined:
                raise AgentRuntimeError("提示词模型没有返回可用内容")
            meta = {
                "provider": _text(result.get("provider"), 80),
                "model": _text(result.get("model"), 160),
                "reasoning_effort": _text(result.get("reasoning_effort"), 40),
                "warning": _text(result.get("warning"), 600),
                "fallback": bool(result.get("fallback")),
            }
            return refined, meta
        except Exception as exc:
            fallback = current or goal
            if current and goal and goal not in current:
                fallback = f"{current}\n\n本轮调整目标：{goal}".strip()
            if not fallback:
                raise
            return fallback, {
                "provider": "local",
                "model": "fallback",
                "fallback": True,
                "warning": f"提示词模型不可用，已保留原始内容：{_text(exc, 480)}",
            }

    def _build_client_action(
        self,
        kind: str,
        run: dict[str, Any],
        working: dict[str, Any],
        summary: dict[str, Any],
        options: dict[str, Any],
    ) -> dict[str, Any]:
        base = {
            "type": kind,
            "run_id": run.get("run_id"),
            "goal": run.get("goal"),
        }
        if kind == "analyze_images":
            return {
                **base,
                "image_node_ids": summary.get("image_node_ids") or [],
                "message": run.get("goal") or "分析画布参考图",
            }
        if kind == "compile_h3_prompt":
            plan = run.get("plan") if isinstance(run.get("plan"), dict) else {}
            confirmation = plan.get("confirmation") if isinstance(plan.get("confirmation"), dict) else {}
            return {
                **base,
                "video_node_id": summary.get("video_node_id") or summary.get("generation_node_id") or "",
                "first_frame_node_id": summary.get("first_frame_node_id") or "",
                "current_prompt": working.get("prompt") or summary.get("current_prompt") or "",
                "analysis": copy.deepcopy(working.get("analysis") or {}),
                "mode": confirmation.get("mode") or "image_to_video",
                "h3_mode": confirmation.get("h3_mode") or "I2VA",
                "duration_seconds": confirmation.get("duration_seconds") or 15,
                "aspect_ratio": confirmation.get("aspect_ratio") or "3:4",
            }
        if kind == "update_text_node":
            return {
                **base,
                "node_id": summary.get("selected_text_node_id") or working.get("text_node_id") or "",
                "text": working.get("prompt") or run.get("goal") or "",
                "prompt_meta": copy.deepcopy(working.get("prompt_meta") or {}),
            }
        if kind == "apply_prompt_to_input":
            return {
                **base,
                "input_node_id": summary.get("input_node_id") or "input",
                "text": working.get("prompt") or run.get("goal") or "",
                "prompt_meta": copy.deepcopy(working.get("prompt_meta") or {}),
            }
        if kind == "connect_nodes":
            if summary.get("task_domain") == "video":
                return {
                    **base,
                    "from_node_id": summary.get("first_frame_node_id") or "",
                    "to_node_id": summary.get("video_node_id") or summary.get("generation_node_id") or "",
                    "input_role": "first_frame",
                }
            return {
                **base,
                "from_node_id": options.get("from_node_id") or "",
                "to_node_id": options.get("to_node_id") or summary.get("input_node_id") or "input",
            }
        if kind == "submit_generation":
            params = copy.deepcopy(summary.get("params") or {})
            approval = (run.get("request") or {}).get("approval")
            provider = summary.get("provider") or "gpt"
            archive_enabled = summary.get("archive_enabled", True)
            telegram_enabled = summary.get("telegram_enabled", True)
            plan = run.get("plan") if isinstance(run.get("plan"), dict) else {}
            confirmation = plan.get("confirmation") if isinstance(plan.get("confirmation"), dict) else {}
            if confirmation:
                for key in ("ratio", "resolution", "quality", "image_count", "archive_enabled", "telegram_enabled"):
                    if key in confirmation:
                        params[key] = confirmation[key]
                for source, target in {
                    "image_count": "imageCount",
                    "archive_enabled": "archiveEnabled",
                    "telegram_enabled": "telegramEnabled",
                }.items():
                    if source in confirmation:
                        params[target] = confirmation[source]
                requested_provider = _text(confirmation.get("provider"), 40).lower()
                if requested_provider in {"gpt", "google"}:
                    provider = requested_provider
                archive_enabled = _bool(confirmation.get("archive_enabled"), archive_enabled)
                telegram_enabled = _bool(confirmation.get("telegram_enabled"), telegram_enabled)
            if isinstance(approval, dict):
                overrides = approval.get("params") if isinstance(approval.get("params"), dict) else {}
                params.update(overrides)
                alias_keys = {
                    "image_count": "imageCount",
                    "archive_enabled": "archiveEnabled",
                    "telegram_enabled": "telegramEnabled",
                }
                for source, target in alias_keys.items():
                    if source in overrides:
                        params[target] = overrides[source]
                for key in ("ratio", "resolution", "image_count", "imageCount", "model"):
                    if key in approval:
                        params[key] = approval[key]
                requested_provider = _text(approval.get("provider"), 40).lower()
                if requested_provider in {"gpt", "google", "comfy", "upscale"}:
                    provider = requested_provider
                archive_enabled = _bool(
                    overrides.get("archive_enabled", overrides.get("archiveEnabled", approval.get("archive_enabled"))),
                    archive_enabled,
                )
                telegram_enabled = _bool(
                    overrides.get("telegram_enabled", overrides.get("telegramEnabled", approval.get("telegram_enabled"))),
                    telegram_enabled,
                )
            params["archiveEnabled"] = archive_enabled
            params["telegramEnabled"] = telegram_enabled
            return {
                **base,
                "result_node_id": summary.get("result_node_id") or summary.get("input_node_id") or "input",
                "provider": provider,
                "prompt": working.get("prompt") or run.get("goal") or "",
                "params": params,
            }
        if kind == "submit_video_generation":
            return {
                **base,
                "video_node_id": summary.get("video_node_id") or summary.get("generation_node_id") or "",
                "generation_node_id": summary.get("generation_node_id") or summary.get("video_node_id") or "",
                "prompt": working.get("prompt") or run.get("goal") or "",
                "artifact_type": "video",
            }
        if kind == "rollback_canvas":
            return {**base, "snapshot_key": run.get("run_id")}
        raise AgentRuntimeError(f"不支持的客户端动作：{kind}")

    def _request_client_action(self, run_id: str, step_index: int | None, action: dict[str, Any]) -> dict[str, Any]:
        action_id = f"action_{uuid.uuid4().hex[:14]}"
        action = {**action, "action_id": action_id}
        condition = self._condition(run_id)
        agent_store.update_run(run_id, status="waiting_for_action", waiting_action_id=action_id)
        self._emit(
            run_id,
            "action_required",
            status="waiting_for_action",
            step_index=step_index,
            message=f"等待桌面执行：{action.get('type')}",
            payload={"action": action},
        )
        deadline = time.monotonic() + ACTION_TIMEOUT_SECONDS
        key = (run_id, action_id)
        while time.monotonic() < deadline:
            control_started = time.monotonic()
            self._check_control(run_id)
            deadline += max(0.0, time.monotonic() - control_started)
            with condition:
                result = self._action_results.pop(key, None)
                if result is not None:
                    agent_store.update_run(run_id, status="running", waiting_action_id="")
                    return result
                condition.wait(timeout=0.5)
        agent_store.update_run(run_id, waiting_action_id="")
        raise AgentRuntimeError("等待桌面执行动作超时")

    def submit_action_result(
        self,
        run_id: str,
        action_id: str,
        *,
        result: dict[str, Any] | None = None,
        error: str = "",
    ) -> dict[str, Any]:
        run = self._require_run(run_id)
        action_id = _text(action_id, 180)
        if not action_id:
            raise ValueError("缺少 action_id")
        waiting_action_id = _text(run.get("waiting_action_id"), 180)
        if not waiting_action_id:
            raise AgentRunConflict("当前运行没有等待中的桌面动作")
        if waiting_action_id != action_id:
            raise AgentRunConflict("动作回执与当前等待动作不匹配")
        payload = {
            "ok": not bool(error),
            "action_id": action_id,
            "result": result if isinstance(result, dict) else {},
            "error": _text(error, 2_000),
        }
        self._emit(
            run_id,
            "action_result",
            status="failed" if error else "succeeded",
            step_index=int(run.get("current_step") or 0),
            message=f"桌面动作{'失败' if error else '已完成'}。",
            payload=payload,
        )
        condition = self._condition(run_id)
        with condition:
            self._action_results[(run_id, action_id)] = payload
            condition.notify_all()
        return self.get_run(run_id)

    def _monitor_generation(
        self,
        run_id: str,
        task_id: str,
        step_index: int,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        run = self._require_run(run_id)
        is_video = (run.get("plan") or {}).get("task_domain") == "video"
        timeout_seconds = _int(
            options.get("task_timeout_seconds"),
            7_200 if is_video else 1_800,
            30,
            14_400 if is_video else 3_600,
        )
        poll_interval = max(0.4, min(float(options.get("poll_interval_seconds") or 1.4), 10.0))
        deadline = time.monotonic() + timeout_seconds
        last_signature: tuple[Any, ...] | None = None
        missing_reads = 0
        while time.monotonic() < deadline:
            control_started = time.monotonic()
            self._check_control(run_id)
            deadline += max(0.0, time.monotonic() - control_started)
            task = self._task_getter(task_id)
            if not task:
                missing_reads += 1
                if missing_reads >= 5:
                    raise AgentRuntimeError("生成任务不存在或已被清理")
                time.sleep(poll_interval)
                continue
            status = _text(task.get("status"), 80)
            signature = (
                status,
                _text(task.get("stage"), 100),
                _text(task.get("progress_text"), 500),
                task.get("progress"),
            )
            if signature != last_signature:
                last_signature = signature
                self._emit(
                    run_id,
                    "generation_progress",
                    status=status,
                    step_index=step_index,
                    message=_text(task.get("progress_text") or status or "生成中", 500),
                    payload={
                        "task_id": task_id,
                        "task_status": status,
                        "stage": task.get("stage") or "",
                        "progress": task.get("progress") or 0,
                    },
                )
            if status in TERMINAL_TASK_STATUSES:
                if status in {"failed", "telegram_failed", "canceled"}:
                    raise AgentRuntimeError(_text(task.get("display_error") or task.get("error") or f"生成任务{status}", 2_000))
                return task
            time.sleep(poll_interval)
        raise AgentRuntimeError(f"等待{'视频' if is_video else '图片'}生成完成超时")

    def pause_run(self, run_id: str) -> dict[str, Any]:
        run = self._require_run(run_id)
        if run.get("status") not in {"running", "waiting_for_action"}:
            raise AgentRunConflict("当前运行不能暂停")
        control = dict(run.get("control") or {})
        control["pause_requested"] = True
        agent_store.update_run(run_id, control=control, status="paused")
        self._emit(run_id, "run_paused", status="paused", message="Agent 已暂停；已经提交的后台生成任务不会因此删除。")
        condition = self._condition(run_id)
        with condition:
            condition.notify_all()
        return self.get_run(run_id)

    def resume_run(self, run_id: str) -> dict[str, Any]:
        run = self._require_run(run_id)
        if run.get("status") != "paused":
            raise AgentRunConflict("当前运行不在暂停状态")
        control = dict(run.get("control") or {})
        recovered = _bool(control.pop("recovered_after_restart", False), False)
        operation = _text(control.get("operation") or "execute", 40)
        control["pause_requested"] = False
        control["rollback_requested"] = False
        waiting_action_id = "" if recovered else _text(run.get("waiting_action_id"), 180)
        next_status = (
            "rolling_back"
            if operation == "rollback"
            else ("waiting_for_action" if waiting_action_id else "running")
        )
        agent_store.update_run(
            run_id,
            control=control,
            status=next_status,
            waiting_action_id=waiting_action_id,
            error="",
        )
        self._emit(run_id, "run_resumed", status=next_status, message="Agent 已继续执行。")
        condition = self._condition(run_id)
        with condition:
            condition.notify_all()
        target = self._execute_rollback if operation == "rollback" else self._execute_run
        self._spawn(run_id, target)
        return self.get_run(run_id)

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        run = self._require_run(run_id)
        if run.get("status") in TERMINAL_RUN_STATUSES:
            return self.get_run(run_id)
        control = dict(run.get("control") or {})
        control.update({
            "cancel_requested": True,
            "pause_requested": False,
            "rollback_requested": False,
        })
        task_id = _text(run.get("task_id"), 160)
        if task_id:
            try:
                self._task_canceler(task_id, "canceled", "Agent 已取消生成任务", stage="canceled")
            except Exception:
                pass
        agent_store.update_run(
            run_id,
            control=control,
            status="canceled",
            waiting_action_id="",
            finished_at=int(time.time()),
            error="运行已取消",
        )
        self._emit(run_id, "run_canceled", status="canceled", message="Agent 运行已取消。")
        condition = self._condition(run_id)
        with condition:
            condition.notify_all()
        return self.get_run(run_id)

    def request_rollback(self, run_id: str) -> dict[str, Any]:
        run = self._require_run(run_id)
        if run.get("status") not in {"succeeded", "failed", "canceled", "paused"}:
            raise AgentRunConflict("请先暂停或等待当前运行结束，再回滚画布")
        with self._lock:
            current = self._threads.get(run_id)
            handoff_from_paused = bool(
                run.get("status") == "paused"
                and current
                and current.is_alive()
            )
        control = dict(run.get("control") or {})
        control.update({
            "cancel_requested": False,
            "pause_requested": False,
            "rollback_requested": handoff_from_paused,
            "recovered_after_restart": False,
            "operation": "rollback",
        })
        agent_store.update_run(
            run_id,
            status="rolling_back",
            control=control,
            waiting_action_id="",
            error="",
        )
        self._emit(run_id, "rollback_requested", status="rolling_back", message="正在请求桌面恢复 Agent 执行前的画布。")
        condition = self._condition(run_id)
        with condition:
            condition.notify_all()
        if not handoff_from_paused:
            self._spawn_after_current(run_id, self._execute_rollback)
        return self.get_run(run_id)

    def _execute_rollback(self, run_id: str) -> None:
        try:
            run = self._require_run(run_id)
            result = self._request_client_action(
                run_id,
                None,
                {"type": "rollback_canvas", "run_id": run_id, "snapshot_key": run_id},
            )
            if result.get("ok") is False or result.get("error"):
                raise AgentRuntimeError(_text(result.get("error") or "画布回滚失败", 2_000))
            current = agent_store.get_run(run_id) or {}
            control = dict(current.get("control") or {})
            control.update({"rollback_requested": False, "operation": ""})
            agent_store.update_run(
                run_id,
                status="rolled_back",
                control=control,
                waiting_action_id="",
                finished_at=int(time.time()),
                error="",
            )
            self._emit(run_id, "rollback_completed", status="rolled_back", message="画布已恢复到 Agent 执行前。")
        except AgentRunCanceled:
            return
        except Exception as exc:
            current = agent_store.get_run(run_id) or {}
            control = dict(current.get("control") or {})
            control.update({"rollback_requested": False, "operation": ""})
            agent_store.update_run(
                run_id,
                status="failed",
                control=control,
                waiting_action_id="",
                finished_at=int(time.time()),
                error=_text(exc, 2_000),
            )
            self._emit(run_id, "rollback_failed", status="failed", message=f"画布回滚失败：{exc}")


_RUNTIME: AgentRuntime | None = None
_RUNTIME_LOCK = threading.Lock()


def get_agent_runtime() -> AgentRuntime:
    global _RUNTIME
    if _RUNTIME is None:
        with _RUNTIME_LOCK:
            if _RUNTIME is None:
                _RUNTIME = AgentRuntime()
    return _RUNTIME


__all__ = [
    "AGENT_SCHEMA_VERSION",
    "MAX_PLAN_STEPS",
    "MAX_GENERATION_ROUNDS",
    "AgentRuntime",
    "AgentRuntimeError",
    "AgentRunNotFound",
    "AgentRunConflict",
    "AgentRunRollback",
    "build_plan",
    "summarize_context",
    "get_agent_runtime",
]
