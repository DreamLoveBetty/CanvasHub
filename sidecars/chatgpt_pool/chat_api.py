from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from .account_pool import AccountPool
from .backend_runtime import build_backend_for_lease, mark_verification_required, verification_exhausted_message
from .openai_backend import CHAT_MODEL, CHAT_TIMEOUT_SECS, OpenAIBackend, VerificationRequiredError


def _messages_from_body(body: dict[str, Any]) -> list[dict[str, Any]]:
    messages = body.get("messages")
    if isinstance(messages, list) and messages:
        clean = [item for item in messages if isinstance(item, dict)]
        if clean:
            return clean
    prompt = str(body.get("prompt") or body.get("input") or "").strip()
    if prompt:
        return [{"role": "user", "content": prompt}]
    raise ValueError("messages or prompt is required")


def _completion_response(model: str, content: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "conversation_id": str(result.get("conversation_id") or ""),
        "assistant_message_id": str(result.get("assistant_message_id") or ""),
    }


def create_chat_completion(
    body: dict[str, Any],
    pool: AccountPool,
    backend_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    if bool(body.get("stream")):
        raise ValueError("stream is not supported")
    messages = _messages_from_body(body)
    model = str(body.get("model") or CHAT_MODEL).strip() or CHAT_MODEL
    try:
        timeout_secs = float(body.get("timeout_seconds") or body.get("timeout") or CHAT_TIMEOUT_SECS)
    except (TypeError, ValueError):
        timeout_secs = CHAT_TIMEOUT_SECS
    timeout_secs = max(30.0, min(300.0, timeout_secs))
    base64_images = body.get("base64_images")
    if base64_images is None:
        base64_images = body.get("images")
    if not isinstance(base64_images, list):
        base64_images = []
    base64_images = [str(item or "").strip() for item in base64_images if str(item or "").strip()]
    backend_factory = backend_factory or OpenAIBackend

    skipped_tokens: set[str] = set()
    verification_errors: list[str] = []
    while True:
        lease = None
        try:
            lease = pool.acquire_available(exclude_tokens=skipped_tokens)
            backend = build_backend_for_lease(backend_factory, lease)
            if base64_images:
                result = backend.chat_completion_with_images(
                    messages,
                    base64_images,
                    model=model,
                    timeout_secs=timeout_secs,
                )
            else:
                result = backend.chat_completion(messages, model=model, timeout_secs=timeout_secs)
            content = str(result.get("content") or "").strip()
            if not content:
                raise RuntimeError("chat completion returned empty text")
            pool.mark_result(lease.access_token, True)
            return _completion_response(model, content, result)
        except VerificationRequiredError as exc:
            message = f"{lease.email}: {exc}" if lease and lease.email else str(exc)
            verification_errors.append(message)
            if lease is None:
                raise RuntimeError(verification_exhausted_message(pool, verification_errors)) from exc
            skipped_tokens.add(lease.access_token)
            mark_verification_required(pool, lease.access_token, message)
            continue
        except RuntimeError as exc:
            if "no available image quota" in str(exc).lower() and verification_errors:
                raise RuntimeError(verification_exhausted_message(pool, verification_errors)) from exc
            if lease is not None:
                pool.mark_result(lease.access_token, False, str(exc))
            raise
        except Exception as exc:
            if lease is not None:
                pool.mark_result(lease.access_token, False, str(exc))
            raise
