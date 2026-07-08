#!/usr/bin/env python3
"""Generation run/event tracking and user-facing error translation."""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from .database import get_db, update_task_fields

MODERATION_CATEGORY_LABELS = {
    "CHARACTER": "人物/角色",
    "SEXUALLY_EXPLICIT": "露骨/性内容",
    "HATE": "仇恨/歧视内容",
    "HARASSMENT": "骚扰/辱骂内容",
    "VIOLENCE": "暴力内容",
    "DANGEROUS": "危险行为",
    "SELF_HARM": "自伤内容",
    "MEDICAL": "医疗内容",
    "SPAM": "垃圾信息",
    "PROHIBITED_CONTENT": "受限内容",
}


def _now() -> int:
    return int(time.time())


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _short(value: Any, limit: int = 240) -> str:
    return _clean_text(value)[:limit]


def _json_text(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except Exception:
        return json.dumps(str(value), ensure_ascii=False)


def _generate_run_id() -> str:
    return f"run_{_now()}_{uuid.uuid4().hex[:10]}"


def _normalize_key(*values: Any) -> str:
    for value in values:
        text = _clean_text(value).lower()
        if text:
            return text
    return ""


def _first_meaningful_line(text: str) -> str:
    for line in str(text or "").splitlines():
        item = _clean_text(line)
        if not item:
            continue
        if item.startswith("Traceback "):
            continue
        if item.startswith("at "):
            continue
        if item.startswith("File "):
            continue
        if re.fullmatch(r"[\^~\s]+", item):
            continue
        item = re.sub(r"^(?:Error|RuntimeError|Exception|ValueError|TypeError|RuntimeError|RuntimeError):\s*", "", item)
        if item:
            return item
    return ""


def _extract_codes(text: str) -> list[str]:
    matches = []
    for pattern in (
        r"(?:moderation_category|category|blockReason|finishReason|reason)\s*[:=]\s*([A-Z_][A-Z0-9_]+)",
        r"\bcode=([A-Za-z0-9_.:-]+)",
        r"\berror_code=([A-Za-z0-9_.:-]+)",
    ):
        for match in re.findall(pattern, text, flags=re.I):
            item = str(match).strip()
            if item and item not in matches:
                matches.append(item.upper() if item.isalpha() and item.upper() == item else item)
    return matches


def _moderation_detail_text(text: str) -> str:
    categories = []
    for code in _extract_codes(text):
        upper = str(code).upper()
        if upper in MODERATION_CATEGORY_LABELS:
            label = MODERATION_CATEGORY_LABELS[upper]
            if label not in categories:
                categories.append(label)
    if categories:
        return "、".join(categories)
    if "PROHIBITED_CONTENT" in text.upper():
        return "受限内容"
    return ""


def _is_google_route(route: str, provider: str, task_type: str) -> bool:
    joined = " ".join(part for part in (route, provider, task_type) if part).lower()
    return "google" in joined or "gemini" in joined


def _is_gpt_route(route: str, provider: str, task_type: str) -> bool:
    joined = " ".join(part for part in (route, provider, task_type) if part).lower()
    return "gpt" in joined or "codex" in joined or "chatgpt" in joined or "pool" in joined


def _error_code(prefix: str, suffix: str) -> str:
    prefix = _clean_text(prefix).strip(".")
    suffix = _clean_text(suffix).strip(".")
    if prefix and suffix:
        return f"{prefix}.{suffix}"
    return prefix or suffix or "generation.unknown"


def translate_generation_error(
    raw_error: Any,
    *,
    provider: str = "",
    route: str = "",
    task_type: str = "",
    stage: str = "",
    exception_name: str = "",
) -> dict[str, str]:
    """Translate provider/runtime errors into compact Chinese user messages."""
    text = _clean_text(raw_error)
    provider_key = _normalize_key(provider, route, task_type)
    stage_key = _normalize_key(stage)
    exception_key = _normalize_key(exception_name)
    lower = text.lower()

    if not text:
        return {
            "error_code": _error_code(provider_key or "generation", "unknown"),
            "error_category": "unknown",
            "display_error": "生成失败",
            "raw_error": "",
        }

    if provider_key in {"canceled", "cancelled"} or lower in {"canceled", "cancelled"}:
        return {
            "error_code": "task.canceled",
            "error_category": "canceled",
            "display_error": "任务已取消",
            "raw_error": text,
        }

    if (
        "prohibited_content" in lower
        or "blocked by gemini api" in lower
        or "request blocked by gemini api" in lower
        or "promptfeedback" in lower
        or "内容安全过滤" in text
        or "安全过滤" in text
        or "safety" in lower and "moderation" in lower
    ):
        detail = _moderation_detail_text(text)
        display = "Google 图像生成被安全策略拦截"
        if detail:
            display += f"（{detail}）"
        elif "prohibited_content" in lower:
            display += "（PROHIBITED_CONTENT）"
        code = "google.prohibited_content" if _is_google_route(route, provider, task_type) else _error_code(provider_key or "generation", "prohibited_content")
        return {
            "error_code": code,
            "error_category": "safety",
            "display_error": display,
            "raw_error": text,
        }

    if "usage_limit_reached" in lower or "usage limit has been reached" in lower:
        reset_text = ""
        match = re.search(r'"resets_at"\s*:\s*(\d+)', text)
        if match:
            try:
                reset_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(match.group(1))))
                reset_text = f"，预计 {reset_time} 恢复"
            except Exception:
                reset_text = ""
        display = f"本地 GPT 授权额度已用完{reset_text}"
        return {
            "error_code": "codex.usage_limit_reached",
            "error_category": "quota",
            "display_error": display,
            "raw_error": text,
        }

    if (
        "browser verification" in lower
        or "需要浏览器验证" in text
        or "turnstile" in lower
        or "arkose" in lower
    ):
        code = _error_code(provider_key or ("chatgpt_pool" if "pool" in provider_key else "generation"), "verification_required")
        return {
            "error_code": code,
            "error_category": "verification_required",
            "display_error": "ChatGPT 账号池需要浏览器验证",
            "raw_error": text,
        }

    if (
        "quota" in lower
        or "need quota" in lower
        or "insufficient_quota" in lower
        or "image quota exhausted" in lower
        or "image generation quota reached" in lower
        or "free plan limit" in lower
        or "图片创建上限" in text
        or "额度" in text
    ):
        reset_text = ""
        match = re.search(r'(?:恢复时间|resets_after_text=|reset_after=)\s*([^;|]+)', text, re.I)
        if match:
            reset_text = f"，{_short(match.group(1), 80)}"
        provider_label = "Google" if _is_google_route(route, provider, task_type) else ("ChatGPT 账号池" if "pool" in provider_key else "模型")
        display = f"{provider_label} 额度不足或已达上限{reset_text}"
        code = _error_code(provider_key or ("google" if _is_google_route(route, provider, task_type) else "generation"), "quota")
        return {
            "error_code": code,
            "error_category": "quota",
            "display_error": display,
            "raw_error": text,
        }

    if (
        "unauthorized" in lower
        or "invalid api key" in lower
        or "api key is required" in lower
        or "http 401" in lower
        or "http 403" in lower
        or "forbidden" in lower and "quota" not in lower
        or "auth" in lower and "refresh" in lower
    ):
        display = "授权已失效或没有访问权限，请重新登录/刷新授权"
        if "chatgpt_pool" in provider_key or "pool" in provider_key:
            display = "ChatGPT 账号池鉴权失败，请检查 sidecar 或重新登录"
        code = _error_code(provider_key or "generation", "auth")
        return {
            "error_code": code,
            "error_category": "auth",
            "display_error": display,
            "raw_error": text,
        }

    if "missing route" in lower or "not found" in lower and "interface" in lower:
        display = "侧车接口未加载，请重启对应服务后再试"
        if "chatgpt_pool" in provider_key or "pool" in provider_key:
            display = "ChatGPT 账号池 sidecar 未加载接口，请重启 sidecar 后再试"
        return {
            "error_code": _error_code(provider_key or "generation", "missing_route"),
            "error_category": "configuration",
            "display_error": display,
            "raw_error": text,
        }

    if "chunkedencodingerror" in lower or "response ended prematurely" in lower or "stream disconnected" in lower:
        if "before first event" in lower:
            display = "连接在收到模型响应前中断，请检查网络或代理"
        elif "last_event=response.image_generation_call.generating" in lower:
            display = "连接中途断开，已进入图片生成阶段但上游没有完整返回"
        else:
            display = "连接中途断开，通常是上游流或网络中断"
        return {
            "error_code": _error_code(provider_key or "transport", "stream_disconnected"),
            "error_category": "transport",
            "display_error": display,
            "raw_error": text,
        }

    if (
        "sslerror" in lower
        or "ssleoferror" in lower
        or "unexpected_eof_while_reading" in lower
        or "eof occurred in violation of protocol" in lower
        or "max retries exceeded with url" in lower and "httpsconnectionpool" in lower
    ):
        display = "HTTPS 连接在读取响应时被上游提前断开，请稍后重试"
        if "third_party" in provider_key or "change2pro" in lower:
            display = "第三方图片 API 连接中途断开，请稍后重试或检查网络/代理"
        return {
            "error_code": _error_code(provider_key or "transport", "ssl_eof"),
            "error_category": "transport",
            "display_error": display,
            "raw_error": text,
        }

    if "timeout" in lower or "timed out" in lower or "total timeout after" in lower or "first_byte_timeout" in lower:
        display = "请求超时，请稍后重试"
        if "first_byte" in lower:
            display = "首字节超时，请检查上游是否拥堵或网络是否不稳定"
        elif "download" in lower or "read_timeout_during_download" in lower:
            display = "下载过程超时，可能是上游返回过慢或网络中断"
        return {
            "error_code": _error_code(provider_key or "transport", "timeout"),
            "error_category": "transport",
            "display_error": display,
            "raw_error": text,
        }

    if "connection reset" in lower or "connection error" in lower or "remote end closed" in lower or "broken pipe" in lower or "connection refused" in lower or "failed to establish a new connection" in lower:
        display = "连接失败，请检查网络、代理或上游服务是否在线"
        if "connection reset" in lower or "remote end closed" in lower:
            display = "连接被对端中断，通常是网络或上游服务临时异常"
        return {
            "error_code": _error_code(provider_key or "transport", "connection_error"),
            "error_category": "transport",
            "display_error": display,
            "raw_error": text,
        }

    if "did not return image output" in lower or "missing image output" in lower or "returned text instead of image" in lower or "返回了文字而不是图片" in text:
        if any(marker in lower for marker in ("violate", "policy", "safety", "refuse", "cannot")) or "安全" in text:
            display = "模型返回了文字而不是图片，可能触发了安全或内容边界，请调整提示词后重试"
        else:
            display = "模型没有返回可用图片数据，请稍后重试"
        return {
            "error_code": _error_code(provider_key or "generation", "invalid_image_output"),
            "error_category": "output",
            "display_error": display,
            "raw_error": text,
        }

    if "response.failed" in lower or "server_error" in lower:
        request_id = ""
        match = re.search(r"(?:request_id=|request ID\s+)([A-Za-z0-9_-]+)", text, re.I)
        if match:
            request_id = f"（request_id: {match.group(1)}）"
        display = f"上游临时错误{request_id}"
        return {
            "error_code": _error_code(provider_key or "generation", "server_error"),
            "error_category": "upstream",
            "display_error": display,
            "raw_error": text,
        }

    if "http 429" in lower or "rate limit" in lower or "限流" in text:
        display = "请求过于频繁，被上游限流了"
        if "chatgpt_pool" in provider_key or "pool" in provider_key:
            display = "ChatGPT 账号池账号被限流了"
        return {
            "error_code": _error_code(provider_key or "generation", "rate_limited"),
            "error_category": "rate_limit",
            "display_error": display,
            "raw_error": text,
        }

    if "telegram" in lower and "fail" in lower:
        return {
            "error_code": _error_code("telegram", "send_failed"),
            "error_category": "delivery",
            "display_error": "图片生成成功，但发送到 Telegram 失败",
            "raw_error": text,
        }

    summary = _first_meaningful_line(text) or text
    if len(summary) > 180:
        summary = summary[:177] + "..."
    display = summary
    if not re.search(r"[\u4e00-\u9fff]", display):
        display = f"生成失败：{display}"
    code_suffix = "unknown"
    if stage_key:
        code_suffix = stage_key
    elif exception_key and exception_key not in {"exception", "runtimeerror", "valueerror", "typeerror"}:
        code_suffix = exception_key
    return {
        "error_code": _error_code(provider_key or "generation", code_suffix),
        "error_category": "unknown",
        "display_error": display,
        "raw_error": text,
    }


def _task_generation_fields(run_id: str | None = None, error_info: dict[str, str] | None = None) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if run_id:
        fields["last_run_id"] = run_id
    if error_info:
        fields["error_code"] = error_info.get("error_code") or ""
        fields["display_error"] = error_info.get("display_error") or ""
        fields["error"] = error_info.get("display_error") or ""
        fields["raw_error"] = error_info.get("raw_error") or ""
    return fields


def start_generation_run(
    task_id: str,
    task_type: str,
    *,
    provider: str = "",
    route: str = "",
    prompt: str = "",
    params: dict[str, Any] | None = None,
    stage: str = "preparing",
    status: str = "running",
    parent_run_id: str = "",
) -> dict[str, Any]:
    """Create a new logical generation run and bump task summary counters."""
    run_id = _generate_run_id()
    now = _now()
    payload = params if isinstance(params, dict) else {}
    with get_db() as conn:
        current = conn.execute(
            "SELECT COALESCE(run_count, 0) AS run_count FROM tasks WHERE task_id=?",
            (_clean_text(task_id),),
        ).fetchone()
        next_run_count = int(current["run_count"] if current else 0) + 1
        conn.execute(
            """
            INSERT INTO generation_runs (
                run_id, task_id, task_type, provider, route, status, stage,
                prompt, params, parent_run_id, created_at, started_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                task_id,
                _clean_text(task_type),
                _clean_text(provider),
                _clean_text(route),
                _clean_text(status) or "running",
                _clean_text(stage) or "preparing",
                _clean_text(prompt),
                _json_text(payload),
                _clean_text(parent_run_id),
                now,
                now,
                now,
            ),
        )
        conn.commit()
    update_task_fields(
        task_id,
        last_run_id=run_id,
        run_count=next_run_count,
        error="",
        error_code="",
        display_error="",
        error_category="",
        raw_error="",
    )
    return {
        "run_id": run_id,
        "task_id": task_id,
        "task_type": _clean_text(task_type),
        "provider": _clean_text(provider),
        "route": _clean_text(route),
        "status": _clean_text(status) or "running",
        "stage": _clean_text(stage) or "preparing",
        "created_at": now,
    }


def record_generation_event(
    run_id: str,
    task_id: str,
    event_type: str,
    message: str = "",
    *,
    stage: str = "",
    severity: str = "info",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist meaningful run events only."""
    now = _now()
    event_payload = payload if isinstance(payload, dict) else {}
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO generation_events (
                run_id, task_id, event_type, stage, severity, message, payload, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _clean_text(run_id),
                _clean_text(task_id),
                _clean_text(event_type),
                _clean_text(stage),
                _clean_text(severity) or "info",
                _short(message, 500),
                _json_text(event_payload),
                now,
            ),
        )
        conn.commit()
    return {
        "run_id": _clean_text(run_id),
        "task_id": _clean_text(task_id),
        "event_type": _clean_text(event_type),
        "message": _short(message, 500),
        "stage": _clean_text(stage),
        "severity": _clean_text(severity) or "info",
        "payload": event_payload,
        "created_at": now,
    }


def finish_generation_run(
    run_id: str,
    task_id: str,
    *,
    status: str,
    stage: str = "",
    provider: str = "",
    route: str = "",
    result_file: str = "",
    result_files: list[str] | None = None,
    image_count: int | None = None,
    error_info: dict[str, str] | None = None,
    error_type: str = "",
    parent_run_id: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Finalize a run and update the task summary fields."""
    now = _now()
    fields: dict[str, Any] = {
        "status": _clean_text(status) or "succeeded",
        "finished_at": now,
        "updated_at": now,
    }
    if stage:
        fields["stage"] = _clean_text(stage)
    if provider:
        fields["provider"] = _clean_text(provider)
    if route:
        fields["route"] = _clean_text(route)
    if result_file:
        fields["result_file"] = _clean_text(result_file)
    if result_files is not None:
        fields["result_files"] = _json_text(result_files)
    if image_count is not None:
        try:
            fields["image_count"] = max(0, int(image_count))
        except Exception:
            fields["image_count"] = 0
    if error_info:
        fields["error"] = error_info.get("display_error") or error_info.get("raw_error") or ""
        fields["raw_error"] = error_info.get("raw_error") or ""
        fields["error_code"] = error_info.get("error_code") or ""
        fields["display_error"] = error_info.get("display_error") or ""
        fields["error_category"] = error_info.get("error_category") or ""
    if error_type:
        fields["error_type"] = _clean_text(error_type)
    if parent_run_id:
        fields["parent_run_id"] = _clean_text(parent_run_id)
    if meta is not None:
        fields["meta"] = _json_text(meta)

    with get_db() as conn:
        assignments = ", ".join(f"{key}=?" for key in fields.keys())
        conn.execute(
            f"UPDATE generation_runs SET {assignments} WHERE run_id=? AND task_id=?",
            list(fields.values()) + [_clean_text(run_id), _clean_text(task_id)],
        )
        conn.commit()

    task_updates = {"last_run_id": run_id}
    if error_info:
        task_updates.update(_task_generation_fields(run_id, error_info))
    else:
        task_updates.update({
            "error": "",
            "error_code": "",
            "display_error": "",
            "error_category": "",
            "raw_error": "",
        })
    update_task_fields(task_id, **task_updates)

    return {
        "run_id": _clean_text(run_id),
        "task_id": _clean_text(task_id),
        **fields,
    }


def get_generation_run(run_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM generation_runs WHERE run_id=?",
            (_clean_text(run_id),),
        ).fetchone()
        return dict(row) if row else None


def get_generation_runs(task_id: str, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM generation_runs
            WHERE task_id=?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (_clean_text(task_id), int(limit), int(offset)),
        ).fetchall()
        return [dict(row) for row in rows]


def get_generation_events(run_id: str, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM generation_events
            WHERE run_id=?
            ORDER BY created_at ASC, event_id ASC
            LIMIT ? OFFSET ?
            """,
            (_clean_text(run_id), int(limit), int(offset)),
        ).fetchall()
        return [dict(row) for row in rows]
