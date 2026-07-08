from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from typing import Any, Callable, Iterator

from .account_pool import AccountPool
from .account_store import LIMITED_STATUS, VERIFICATION_STATUS
from .backend_runtime import build_backend_for_lease, mark_verification_required, verification_exhausted_message
from .openai_backend import ImageGenerationLimitError, ImageGenerationStatus, OpenAIBackend, VerificationRequiredError

IMAGE_TIMEOUT_SECS = 420
MAX_IMAGE_COUNT = 8
ACQUIRE_RETRY_SLEEP_SECS = 1.0
RETRYABLE_UPSTREAM_IMAGE_ERROR_MARKERS = (
    "content_types=code,model_editable_context,system_error",
    "system_error=",
    "temporalio.service.rpcerror",
    "rpcerror",
    "图片生成服务调用失败",
    "image generation service call failed",
    "timed out before the stream produced a conversation id",
    "timed out while reading stream",
    "image stream interrupted",
    "remote end closed connection",
    "connection aborted",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
)
NON_RETRYABLE_UPSTREAM_IMAGE_ERROR_MARKERS = (
    "blocked by upstream moderation",
    "moderation",
    "safety policy",
    "policy violation",
    "browser verification",
    "turnstile",
    "arkose",
    "unauthorized",
    "http 401",
    "token_invalidated",
    "refresh_token_invalidated",
    "quota",
    "rate limit",
)


def _coerce_timeout_seconds(value: Any) -> int:
    try:
        timeout = int(value or IMAGE_TIMEOUT_SECS)
    except (TypeError, ValueError):
        timeout = IMAGE_TIMEOUT_SECS
    return max(60, min(900, timeout))


def _coerce_image_count(value: Any) -> int:
    try:
        count = int(value or 1)
    except (TypeError, ValueError):
        count = 1
    return max(1, min(MAX_IMAGE_COUNT, count))


def _restore_at_from_status(status: ImageGenerationStatus | None) -> str:
    if not status:
        return ""
    return str(status.reset_after or "").strip()


def _quota_message(email: str, status: ImageGenerationStatus | None = None) -> str:
    prefix = f"{email}: " if email else ""
    if not status:
        return prefix + "ChatGPT image generation quota reached"
    details = []
    if status.title:
        details.append(status.title)
    if status.description:
        details.append(status.description)
    if status.reset_after:
        details.append(f"恢复时间 {status.reset_after}")
    elif status.resets_after_text:
        details.append(f"恢复 {status.resets_after_text}")
    if status.remaining is not None:
        details.append(f"剩余额度 {status.remaining}")
    if status.limit is not None:
        details.append(f"上限 {status.limit:g}")
    return prefix + ("；".join(details) if details else "ChatGPT image generation quota reached")


def _mark_limited(pool: AccountPool, access_token: str, status: ImageGenerationStatus | None, error: str = "") -> None:
    try:
        pool.store.update_account(
            access_token,
            {
                "status": LIMITED_STATUS,
                "quota": 0,
                "image_quota_unknown": False,
                "restore_at": _restore_at_from_status(status),
            },
        )
    finally:
        pool.mark_result(access_token, False, error)


def _exhausted_message_from_accounts(pool: AccountPool, limit_errors: list[str] | None = None) -> str:
    messages = list(limit_errors or [])
    has_limited = False
    has_verification = False
    for account in pool.store.list_public_accounts():
        email = str(account.get("email") or "")
        if str(account.get("status") or "") == VERIFICATION_STATUS:
            has_verification = True
            messages.append(f"{email}: 需要浏览器验证" if email else "账号需要浏览器验证")
            continue
        if str(account.get("status") or "") != LIMITED_STATUS:
            continue
        has_limited = True
        restore_at = str(account.get("restore_at") or "")
        if restore_at:
            messages.append(f"{email}: 恢复时间 {restore_at}" if email else f"恢复时间 {restore_at}")
        elif email:
            messages.append(f"{email}: 图片额度已用完")
    if messages:
        if has_verification and not has_limited:
            return "ChatGPT account pool browser verification required: " + " | ".join(messages)
        return "ChatGPT account pool image quota exhausted: " + " | ".join(messages)
    return "no available image quota"


def _upstream_errors_message(errors: list[str]) -> str:
    details = [str(item or "").strip() for item in (errors or []) if str(item or "").strip()]
    if not details:
        return "ChatGPT account pool upstream image generation failed"
    return "ChatGPT account pool upstream image generation failed after trying available accounts: " + " | ".join(details[:4])


def _is_retryable_upstream_image_error(error: Exception | str) -> bool:
    text = str(error or "").strip().lower()
    if not text:
        return False
    if any(marker in text for marker in NON_RETRYABLE_UPSTREAM_IMAGE_ERROR_MARKERS):
        return False
    return any(marker in text for marker in RETRYABLE_UPSTREAM_IMAGE_ERROR_MARKERS)


def _parallel_worker_count(pool: AccountPool, image_count: int) -> int:
    try:
        capacity = int((pool.stats() or {}).get("capacity") or 0)
    except Exception:
        capacity = 0
    return max(1, min(max(1, image_count), capacity or 1))


def _acquire_available_with_queue(
    pool: AccountPool,
    exclude_tokens: set[str],
    timeout_seconds: int,
) -> Any:
    deadline = time.monotonic() + max(60, int(timeout_seconds or IMAGE_TIMEOUT_SECS)) + 60
    while True:
        try:
            return pool.acquire_available(exclude_tokens=exclude_tokens)
        except RuntimeError as exc:
            message = str(exc)
            if "no available image quota" not in message.lower():
                raise
            try:
                stats = pool.stats()
            except Exception:
                stats = {}
            if int(stats.get("inflight") or 0) > 0 and time.monotonic() < deadline:
                time.sleep(ACQUIRE_RETRY_SLEEP_SECS)
                continue
            raise


def _generate_one_image(
    index: int,
    prompt: str,
    model: str,
    size: Any,
    quality: str,
    timeout_seconds: int,
    pool: AccountPool,
    backend_factory: Callable[[str], Any],
) -> dict[str, str]:
    limited_tokens_this_image: set[str] = set()
    retry_tokens_this_image: set[str] = set()
    limit_errors: list[str] = []
    upstream_errors: list[str] = []
    while True:
        lease = None
        try:
            lease = _acquire_available_with_queue(pool, limited_tokens_this_image | retry_tokens_this_image, timeout_seconds)
            backend = build_backend_for_lease(backend_factory, lease, timeout_seconds)
            if hasattr(backend, "check_image_generation_status"):
                status = backend.check_image_generation_status()
                if isinstance(status, ImageGenerationStatus) and not status.available:
                    message = _quota_message(lease.email, status)
                    limit_errors.append(message)
                    limited_tokens_this_image.add(lease.access_token)
                    _mark_limited(pool, lease.access_token, status, message)
                    continue
            item = backend.generate_image(prompt, model, size, quality)
            b64_json = str(item.get("b64_json") or "")
            if not b64_json:
                raise RuntimeError("upstream did not return b64_json")
            pool.mark_result(lease.access_token, True)
            return {
                "b64_json": b64_json,
                "revised_prompt": str(item.get("revised_prompt") or prompt),
            }
        except ImageGenerationLimitError as exc:
            message = _quota_message(lease.email if lease else "", exc.status) if exc.status else str(exc)
            limit_errors.append(message)
            if lease is None:
                raise RuntimeError(_exhausted_message_from_accounts(pool, limit_errors)) from exc
            limited_tokens_this_image.add(lease.access_token)
            _mark_limited(pool, lease.access_token, exc.status, message)
            continue
        except VerificationRequiredError as exc:
            message = f"{lease.email}: {exc}" if lease and lease.email else str(exc)
            limit_errors.append(message)
            if lease is None:
                raise RuntimeError(verification_exhausted_message(pool, limit_errors)) from exc
            limited_tokens_this_image.add(lease.access_token)
            mark_verification_required(pool, lease.access_token, message)
            continue
        except RuntimeError as exc:
            if "no available image quota" in str(exc).lower():
                if lease is not None:
                    pool.mark_result(lease.access_token, False, str(exc))
                if upstream_errors:
                    raise RuntimeError(_upstream_errors_message(upstream_errors)) from exc
                raise RuntimeError(_exhausted_message_from_accounts(pool, limit_errors)) from exc
            if lease is not None and _is_retryable_upstream_image_error(exc):
                message = f"{lease.email}: {exc}" if lease.email else str(exc)
                upstream_errors.append(message)
                retry_tokens_this_image.add(lease.access_token)
                pool.mark_result(lease.access_token, False, str(exc))
                continue
            if lease is not None:
                pool.mark_result(lease.access_token, False, str(exc))
            raise RuntimeError(f"image {index + 1}: {exc}") from exc
        except Exception as exc:
            if lease is not None:
                pool.mark_result(lease.access_token, False, str(exc))
            raise RuntimeError(f"image {index + 1}: {exc}") from exc


def _image_list_from_body(body: dict[str, Any]) -> list[str]:
    value = body.get("base64_images")
    if value is None:
        value = body.get("images")
    if value is None:
        value = body.get("image")
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item or "").strip() for item in value if str(item or "").strip()]


def edit_image(
    body: dict[str, Any],
    pool: AccountPool,
    backend_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    ctx = _request_context({**body, "n": 1}, pool, backend_factory)
    images = _image_list_from_body(body)
    if not images:
        raise ValueError("image or base64_images is required")
    mask = str(body.get("mask") or "").strip() or None
    backend_factory = ctx["backend_factory"]
    limited_tokens_this_edit: set[str] = set()
    limit_errors: list[str] = []
    while True:
        lease = None
        try:
            lease = _acquire_available_with_queue(pool, limited_tokens_this_edit, int(ctx["timeout_seconds"]))
            backend = build_backend_for_lease(backend_factory, lease, int(ctx["timeout_seconds"]))
            if hasattr(backend, "check_image_generation_status"):
                status = backend.check_image_generation_status()
                if isinstance(status, ImageGenerationStatus) and not status.available:
                    message = _quota_message(lease.email, status)
                    limit_errors.append(message)
                    limited_tokens_this_edit.add(lease.access_token)
                    _mark_limited(pool, lease.access_token, status, message)
                    continue
            item = backend.edit_image(ctx["prompt"], images, ctx["model"], ctx["size"], ctx["quality"], mask=mask)
            b64_json = str(item.get("b64_json") or "")
            if not b64_json:
                raise RuntimeError("upstream did not return b64_json")
            pool.mark_result(lease.access_token, True)
            return {
                "created": int(time.time()),
                "data": [
                    {
                        "b64_json": b64_json,
                        "revised_prompt": str(item.get("revised_prompt") or ctx["prompt"]),
                    }
                ],
            }
        except ImageGenerationLimitError as exc:
            message = _quota_message(lease.email if lease else "", exc.status) if exc.status else str(exc)
            limit_errors.append(message)
            if lease is None:
                raise RuntimeError(_exhausted_message_from_accounts(pool, limit_errors)) from exc
            limited_tokens_this_edit.add(lease.access_token)
            _mark_limited(pool, lease.access_token, exc.status, message)
            continue
        except VerificationRequiredError as exc:
            message = f"{lease.email}: {exc}" if lease and lease.email else str(exc)
            limit_errors.append(message)
            if lease is None:
                raise RuntimeError(verification_exhausted_message(pool, limit_errors)) from exc
            limited_tokens_this_edit.add(lease.access_token)
            mark_verification_required(pool, lease.access_token, message)
            continue
        except RuntimeError as exc:
            if "no available image quota" in str(exc).lower():
                if lease is not None:
                    pool.mark_result(lease.access_token, False, str(exc))
                raise RuntimeError(_exhausted_message_from_accounts(pool, limit_errors)) from exc
            if lease is not None:
                pool.mark_result(lease.access_token, False, str(exc))
            raise RuntimeError(f"image edit: {exc}") from exc
        except Exception as exc:
            if lease is not None:
                pool.mark_result(lease.access_token, False, str(exc))
            raise RuntimeError(f"image edit: {exc}") from exc


def _errors_message(errors: list[dict[str, Any]]) -> str:
    if not errors:
        return "ChatGPT account pool image generation failed"
    details = []
    for item in errors[:4]:
        details.append(f"#{int(item.get('index') or 0) + 1}: {item.get('error')}")
    suffix = f" (+{len(errors) - 4} more)" if len(errors) > 4 else ""
    return "ChatGPT account pool image generation failed: " + " | ".join(details) + suffix


def _request_context(
    body: dict[str, Any],
    pool: AccountPool,
    backend_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    model = str(body.get("model") or "gpt-image-2")
    if model != "gpt-image-2":
        raise ValueError("unsupported model for chatgpt_pool v1: gpt-image-2 only")
    n = _coerce_image_count(body.get("n") or 1)
    response_format = str(body.get("response_format") or "b64_json")
    if response_format != "b64_json":
        raise ValueError("chatgpt_pool v1 supports response_format=b64_json only")
    timeout_seconds = _coerce_timeout_seconds(body.get("timeout_seconds") or body.get("timeout"))
    return {
        "prompt": prompt,
        "model": model,
        "n": n,
        "size": body.get("size"),
        "quality": str(body.get("quality") or "auto"),
        "timeout_seconds": timeout_seconds,
        "backend_factory": backend_factory or OpenAIBackend,
        "worker_count": _parallel_worker_count(pool, n),
    }


def generate_images(
    body: dict[str, Any],
    pool: AccountPool,
    backend_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    ctx = _request_context(body, pool, backend_factory)
    n = int(ctx["n"])
    results: list[dict[str, str] | None] = [None] * n
    errors: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=int(ctx["worker_count"]), thread_name_prefix="chatgpt-pool-image") as executor:
        futures = {
            executor.submit(
                _generate_one_image,
                index,
                ctx["prompt"],
                ctx["model"],
                ctx["size"],
                ctx["quality"],
                ctx["timeout_seconds"],
                pool,
                ctx["backend_factory"],
            ): index
            for index in range(n)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:
                errors.append({"index": index, "error": str(exc)})

    data = [item for item in results if item]
    if not data:
        raise RuntimeError(_errors_message(errors))
    response: dict[str, Any] = {"created": int(time.time()), "data": data}
    if errors:
        response["partial_errors"] = sorted(errors, key=lambda item: int(item.get("index") or 0))
    return response


def stream_images(
    body: dict[str, Any],
    pool: AccountPool,
    backend_factory: Callable[[str], Any] | None = None,
) -> Iterator[dict[str, Any]]:
    ctx = _request_context(body, pool, backend_factory)
    n = int(ctx["n"])
    results: list[dict[str, str] | None] = [None] * n
    errors: list[dict[str, Any]] = []
    yield {
        "type": "started",
        "created": int(time.time()),
        "requested": n,
        "worker_count": int(ctx["worker_count"]),
    }

    with ThreadPoolExecutor(max_workers=int(ctx["worker_count"]), thread_name_prefix="chatgpt-pool-image") as executor:
        futures = {
            executor.submit(
                _generate_one_image,
                index,
                ctx["prompt"],
                ctx["model"],
                ctx["size"],
                ctx["quality"],
                ctx["timeout_seconds"],
                pool,
                ctx["backend_factory"],
            ): index
            for index in range(n)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                item = future.result()
                results[index] = item
                yield {
                    "type": "image",
                    "created": int(time.time()),
                    "index": index,
                    "item": item,
                }
            except Exception as exc:
                error = {"index": index, "error": str(exc)}
                errors.append(error)
                yield {
                    "type": "error",
                    "created": int(time.time()),
                    **error,
                }

    data = [item for item in results if item]
    final: dict[str, Any] = {
        "type": "final",
        "created": int(time.time()),
        "data": data,
    }
    if errors:
        final["partial_errors"] = sorted(errors, key=lambda item: int(item.get("index") or 0))
    if not data:
        final["error"] = _errors_message(errors)
    yield final
