from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
import math
import threading
import time
from typing import Any, Callable, Iterator

from .account_pool import AccountPool
from .account_store import LIMITED_STATUS, VERIFICATION_STATUS
from .backend_runtime import build_backend_for_lease, mark_verification_required, verification_exhausted_message
from .model_catalog import (
    is_model_unavailable_error,
    normalize_web_model_id,
    resolve_account_image_model,
)
from .openai_backend import ImageGenerationLimitError, ImageGenerationStatus, OpenAIBackend, VerificationRequiredError

IMAGE_TIMEOUT_SECS = 420
MAX_IMAGE_COUNT = 8
MIN_IMAGE_TIMEOUT_SECS = 60
MAX_IMAGE_TIMEOUT_SECS = 900
ACQUIRE_RETRY_SLEEP_SECS = 1.0
INITIAL_ACQUIRE_TIMEOUT_SECS = 180
STREAM_HEARTBEAT_INTERVAL_SECS = 15.0
BATCH_TIMEOUT_BUFFER_SECS = INITIAL_ACQUIRE_TIMEOUT_SECS
MAX_BATCH_TIMEOUT_SECS = MAX_IMAGE_TIMEOUT_SECS * MAX_IMAGE_COUNT + BATCH_TIMEOUT_BUFFER_SECS
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


class ImageGenerationTimeoutError(RuntimeError):
    def __init__(self, index: int, scope: str, timeout_seconds: int):
        self.index = int(index)
        self.scope = scope if scope in {"batch", "queue"} else "image"
        self.timeout_seconds = max(1, int(timeout_seconds))
        if self.scope == "batch":
            message = (
                f"image {self.index + 1}: ChatGPT account pool batch hard timeout "
                f"after {self.timeout_seconds} seconds"
            )
        elif self.scope == "queue":
            message = (
                f"image {self.index + 1}: timed out waiting for an available ChatGPT account "
                f"after {self.timeout_seconds} seconds"
            )
        else:
            message = f"image {self.index + 1}: generation timed out after {self.timeout_seconds} seconds"
        super().__init__(message)


def _coerce_timeout_seconds(value: Any) -> int:
    try:
        timeout = int(value or IMAGE_TIMEOUT_SECS)
    except (TypeError, ValueError):
        timeout = IMAGE_TIMEOUT_SECS
    return max(MIN_IMAGE_TIMEOUT_SECS, min(MAX_IMAGE_TIMEOUT_SECS, timeout))


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


def _batch_timeout_seconds(single_image_timeout_seconds: int, image_count: int, worker_count: int) -> int:
    single_timeout = max(
        MIN_IMAGE_TIMEOUT_SECS,
        min(MAX_IMAGE_TIMEOUT_SECS, int(single_image_timeout_seconds or IMAGE_TIMEOUT_SECS)),
    )
    count = max(1, min(MAX_IMAGE_COUNT, int(image_count or 1)))
    workers = max(1, min(count, int(worker_count or 1)))
    waves = math.ceil(count / workers)
    return min(MAX_BATCH_TIMEOUT_SECS, single_timeout * waves + BATCH_TIMEOUT_BUFFER_SECS)


def _timeout_error(index: int, scope: str, timeout_seconds: int) -> dict[str, Any]:
    exc = ImageGenerationTimeoutError(index, scope, timeout_seconds)
    return {
        "index": int(index),
        "error": str(exc),
        "error_code": "provider_timeout",
        "timeout_scope": exc.scope,
        "timeout_seconds": exc.timeout_seconds,
    }


def _error_from_exception(index: int, exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ImageGenerationTimeoutError):
        return _timeout_error(index, exc.scope, exc.timeout_seconds)
    return {"index": int(index), "error": str(exc)}


def _raise_if_image_timed_out(
    index: int,
    cancel_event: threading.Event,
    image_deadline: float | None,
    batch_deadline: float,
    single_image_timeout_seconds: int,
    batch_timeout_seconds: int,
) -> None:
    now = time.monotonic()
    if cancel_event.is_set() or now >= batch_deadline:
        raise ImageGenerationTimeoutError(index, "batch", batch_timeout_seconds)
    if image_deadline is not None and now >= image_deadline:
        raise ImageGenerationTimeoutError(index, "image", single_image_timeout_seconds)


def _acquire_available_with_queue(
    pool: AccountPool,
    exclude_tokens: set[str],
    timeout_seconds: int,
    *,
    deadline: float | None = None,
    check_deadline: Callable[[], None] | None = None,
    deadline_error: Callable[[], Exception] | None = None,
) -> Any:
    deadline_at = (
        float(deadline)
        if deadline is not None
        else time.monotonic() + max(MIN_IMAGE_TIMEOUT_SECS, int(timeout_seconds or IMAGE_TIMEOUT_SECS)) + 60
    )
    while True:
        if check_deadline:
            check_deadline()
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
            remaining = deadline_at - time.monotonic()
            if int(stats.get("inflight") or 0) > 0 and remaining > 0:
                time.sleep(min(ACQUIRE_RETRY_SLEEP_SECS, remaining))
                continue
            if check_deadline:
                check_deadline()
            if remaining <= 0 and deadline_error:
                raise deadline_error()
            raise


def _call_with_model_adaptation(backend: Any, requested_model: str, call: Callable[[str], dict[str, Any]]):
    actual_model, normalized_requested, adapted = resolve_account_image_model(backend, requested_model)
    try:
        return call(actual_model), actual_model, normalized_requested, adapted
    except Exception as exc:
        if not is_model_unavailable_error(exc):
            raise
        fallback_model, _, _ = resolve_account_image_model(
            backend,
            requested_model,
            force=True,
            excluded={actual_model},
        )
        if not fallback_model or fallback_model == actual_model:
            raise
        item = call(fallback_model)
        return item, fallback_model, normalized_requested, True


def _generate_one_image(
    index: int,
    prompt: str,
    model: str,
    size: Any,
    quality: str,
    timeout_seconds: int,
    pool: AccountPool,
    backend_factory: Callable[[str], Any],
    cancel_event: threading.Event,
    batch_deadline: float,
    batch_timeout_seconds: int,
) -> dict[str, str]:
    image_deadline: float | None = None

    def check_deadline() -> None:
        _raise_if_image_timed_out(
            index,
            cancel_event,
            image_deadline,
            batch_deadline,
            timeout_seconds,
            batch_timeout_seconds,
        )

    limited_tokens_this_image: set[str] = set()
    retry_tokens_this_image: set[str] = set()
    limit_errors: list[str] = []
    upstream_errors: list[str] = []
    while True:
        lease = None
        lease_active = False

        def finish_lease(success: bool, error: str = "") -> None:
            nonlocal lease_active
            if lease is None or not lease_active:
                return
            lease_active = False
            pool.mark_result(lease.access_token, success, error)

        try:
            check_deadline()
            acquire_started_at = time.monotonic()
            if image_deadline is None:
                acquire_timeout_seconds = max(
                    1,
                    min(INITIAL_ACQUIRE_TIMEOUT_SECS, math.ceil(batch_deadline - acquire_started_at)),
                )
                acquire_deadline = min(
                    batch_deadline,
                    acquire_started_at + acquire_timeout_seconds,
                )
                acquire_deadline_error = lambda: ImageGenerationTimeoutError(
                    index,
                    "queue",
                    acquire_timeout_seconds,
                )
            else:
                acquire_deadline = min(image_deadline, batch_deadline)
                acquire_deadline_error = None
            lease = _acquire_available_with_queue(
                pool,
                limited_tokens_this_image | retry_tokens_this_image,
                timeout_seconds,
                deadline=acquire_deadline,
                check_deadline=check_deadline,
                deadline_error=acquire_deadline_error,
            )
            lease_active = True
            if image_deadline is None:
                image_deadline = time.monotonic() + max(
                    MIN_IMAGE_TIMEOUT_SECS,
                    int(timeout_seconds or IMAGE_TIMEOUT_SECS),
                )
            check_deadline()
            effective_deadline = min(image_deadline, batch_deadline)
            remaining_seconds = max(1, math.ceil(effective_deadline - time.monotonic()))
            backend = build_backend_for_lease(
                backend_factory,
                lease,
                remaining_seconds,
                deadline_monotonic=effective_deadline,
                cancel_event=cancel_event,
            )
            if hasattr(backend, "check_image_generation_status"):
                status = backend.check_image_generation_status()
                check_deadline()
                if isinstance(status, ImageGenerationStatus) and not status.available:
                    message = _quota_message(lease.email, status)
                    limit_errors.append(message)
                    limited_tokens_this_image.add(lease.access_token)
                    lease_active = False
                    _mark_limited(pool, lease.access_token, status, message)
                    continue

            def generate_with_remaining_budget(selected_model: str) -> dict[str, Any]:
                check_deadline()
                remaining = max(1, math.ceil(min(image_deadline, batch_deadline) - time.monotonic()))
                if hasattr(backend, "timeout_seconds"):
                    try:
                        backend.timeout_seconds = min(int(backend.timeout_seconds), remaining)
                    except (AttributeError, TypeError, ValueError):
                        pass
                return backend.generate_image(prompt, selected_model, size, quality)

            item, actual_model, requested_model, model_adapted = _call_with_model_adaptation(
                backend,
                model,
                generate_with_remaining_budget,
            )
            check_deadline()
            b64_json = str(item.get("b64_json") or "")
            if not b64_json:
                raise RuntimeError("upstream did not return b64_json")
            finish_lease(True)
            return {
                "b64_json": b64_json,
                "revised_prompt": str(item.get("revised_prompt") or prompt),
                "model": actual_model,
                "requested_model": requested_model,
                "model_adapted": model_adapted,
            }
        except ImageGenerationLimitError as exc:
            message = _quota_message(lease.email if lease else "", exc.status) if exc.status else str(exc)
            limit_errors.append(message)
            if lease is None:
                raise RuntimeError(_exhausted_message_from_accounts(pool, limit_errors)) from exc
            limited_tokens_this_image.add(lease.access_token)
            lease_active = False
            _mark_limited(pool, lease.access_token, exc.status, message)
            continue
        except VerificationRequiredError as exc:
            message = f"{lease.email}: {exc}" if lease and lease.email else str(exc)
            limit_errors.append(message)
            if lease is None:
                raise RuntimeError(verification_exhausted_message(pool, limit_errors)) from exc
            limited_tokens_this_image.add(lease.access_token)
            lease_active = False
            mark_verification_required(pool, lease.access_token, message)
            continue
        except ImageGenerationTimeoutError as exc:
            finish_lease(False, str(exc))
            raise
        except RuntimeError as exc:
            try:
                check_deadline()
            except ImageGenerationTimeoutError as timeout_exc:
                finish_lease(False, str(timeout_exc))
                raise timeout_exc from exc
            if "no available image quota" in str(exc).lower():
                finish_lease(False, str(exc))
                if upstream_errors:
                    raise RuntimeError(_upstream_errors_message(upstream_errors)) from exc
                raise RuntimeError(_exhausted_message_from_accounts(pool, limit_errors)) from exc
            if lease is not None and _is_retryable_upstream_image_error(exc):
                message = f"{lease.email}: {exc}" if lease.email else str(exc)
                upstream_errors.append(message)
                retry_tokens_this_image.add(lease.access_token)
                finish_lease(False, str(exc))
                check_deadline()
                continue
            finish_lease(False, str(exc))
            raise RuntimeError(f"image {index + 1}: {exc}") from exc
        except Exception as exc:
            try:
                check_deadline()
            except ImageGenerationTimeoutError as timeout_exc:
                finish_lease(False, str(timeout_exc))
                raise timeout_exc from exc
            finish_lease(False, str(exc))
            raise RuntimeError(f"image {index + 1}: {exc}") from exc
        finally:
            if lease is not None and lease_active:
                lease_active = False
                pool.release(lease.access_token)


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
            item, actual_model, requested_model, model_adapted = _call_with_model_adaptation(
                backend,
                ctx["model"],
                lambda selected_model: backend.edit_image(
                    ctx["prompt"],
                    images,
                    selected_model,
                    ctx["size"],
                    ctx["quality"],
                    mask=mask,
                ),
            )
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
                        "model": actual_model,
                        "requested_model": requested_model,
                        "model_adapted": model_adapted,
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
    if any(str(item.get("error_code") or "") == "provider_timeout" for item in errors):
        return "ChatGPT account pool image generation timed out before any image completed: " + " | ".join(details) + suffix
    return "ChatGPT account pool image generation failed: " + " | ".join(details) + suffix


def _request_context(
    body: dict[str, Any],
    pool: AccountPool,
    backend_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    model = normalize_web_model_id(body.get("model") or "gpt-image-2")
    n = _coerce_image_count(body.get("n") or 1)
    response_format = str(body.get("response_format") or "b64_json")
    if response_format != "b64_json":
        raise ValueError("chatgpt_pool v1 supports response_format=b64_json only")
    timeout_seconds = _coerce_timeout_seconds(body.get("timeout_seconds") or body.get("timeout"))
    worker_count = _parallel_worker_count(pool, n)
    return {
        "prompt": prompt,
        "model": model,
        "n": n,
        "size": body.get("size"),
        "quality": str(body.get("quality") or "auto"),
        "timeout_seconds": timeout_seconds,
        "backend_factory": backend_factory or OpenAIBackend,
        "worker_count": worker_count,
        "batch_timeout_seconds": _batch_timeout_seconds(timeout_seconds, n, worker_count),
    }


def _start_image_batch(
    ctx: dict[str, Any],
    pool: AccountPool,
) -> tuple[ThreadPoolExecutor, dict[Future, int], threading.Event, float, float]:
    cancel_event = threading.Event()
    batch_started_at = time.monotonic()
    batch_timeout_seconds = int(ctx["batch_timeout_seconds"])
    batch_deadline = batch_started_at + batch_timeout_seconds
    executor = ThreadPoolExecutor(
        max_workers=int(ctx["worker_count"]),
        thread_name_prefix="chatgpt-pool-image",
    )
    futures: dict[Future, int] = {}
    try:
        for index in range(int(ctx["n"])):
            future = executor.submit(
                _generate_one_image,
                index,
                ctx["prompt"],
                ctx["model"],
                ctx["size"],
                ctx["quality"],
                ctx["timeout_seconds"],
                pool,
                ctx["backend_factory"],
                cancel_event,
                batch_deadline,
                batch_timeout_seconds,
            )
            futures[future] = index
    except BaseException:
        cancel_event.set()
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    return executor, futures, cancel_event, batch_started_at, batch_deadline


def _shutdown_image_batch(
    executor: ThreadPoolExecutor,
    pending: set[Future],
    cancel_event: threading.Event,
) -> None:
    if pending:
        cancel_event.set()
        for future in pending:
            future.cancel()
    executor.shutdown(wait=False, cancel_futures=True)


def _pending_batch_timeout_errors(
    pending: set[Future],
    futures: dict[Future, int],
    batch_timeout_seconds: int,
) -> list[dict[str, Any]]:
    return [
        _timeout_error(index, "batch", batch_timeout_seconds)
        for index in sorted(futures[future] for future in pending)
    ]


def _resolve_completed_image_futures(
    completed: set[Future],
    futures: dict[Future, int],
    results: list[dict[str, str] | None],
) -> tuple[list[tuple[int, dict[str, str]]], list[dict[str, Any]]]:
    images: list[tuple[int, dict[str, str]]] = []
    errors: list[dict[str, Any]] = []
    for future in sorted(completed, key=lambda item: futures[item]):
        index = futures[future]
        try:
            item = future.result()
            results[index] = item
            images.append((index, item))
        except Exception as exc:
            errors.append(_error_from_exception(index, exc))
    return images, errors


def generate_images(
    body: dict[str, Any],
    pool: AccountPool,
    backend_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    ctx = _request_context(body, pool, backend_factory)
    n = int(ctx["n"])
    results: list[dict[str, str] | None] = [None] * n
    errors: list[dict[str, Any]] = []
    executor, futures, cancel_event, _, batch_deadline = _start_image_batch(ctx, pool)
    pending = set(futures)
    timeout_errors: list[dict[str, Any]] = []
    try:
        while pending:
            remaining = batch_deadline - time.monotonic()
            if remaining <= 0:
                completed = {future for future in pending if future.done()}
                pending.difference_update(completed)
                _, completed_errors = _resolve_completed_image_futures(completed, futures, results)
                errors.extend(completed_errors)
                if not pending:
                    continue
                timeout_errors = _pending_batch_timeout_errors(
                    pending,
                    futures,
                    int(ctx["batch_timeout_seconds"]),
                )
                break
            completed, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
            if not completed:
                continue
            _, completed_errors = _resolve_completed_image_futures(completed, futures, results)
            errors.extend(completed_errors)
    finally:
        _shutdown_image_batch(executor, pending, cancel_event)

    if timeout_errors:
        errors.extend(timeout_errors)

    data = [item for item in results if item]
    if not data:
        if any(str(item.get("error_code") or "") == "provider_timeout" for item in errors):
            return {
                "created": int(time.time()),
                "data": [],
                "requested": n,
                "completed": 0,
                "error": _errors_message(errors),
                "error_code": "provider_timeout",
                "timed_out": True,
                "partial_errors": sorted(errors, key=lambda item: int(item.get("index") or 0)),
            }
        raise RuntimeError(_errors_message(errors))
    response: dict[str, Any] = {"created": int(time.time()), "data": data}
    if errors:
        response["partial_errors"] = sorted(errors, key=lambda item: int(item.get("index") or 0))
    if any(str(item.get("error_code") or "") == "provider_timeout" for item in errors):
        response["timed_out"] = True
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
        "single_image_timeout_seconds": int(ctx["timeout_seconds"]),
        "batch_timeout_seconds": int(ctx["batch_timeout_seconds"]),
    }

    executor, futures, cancel_event, started_at, batch_deadline = _start_image_batch(ctx, pool)
    pending = set(futures)
    timeout_errors: list[dict[str, Any]] = []
    try:
        while pending:
            remaining = batch_deadline - time.monotonic()
            if remaining <= 0:
                completed = {future for future in pending if future.done()}
                pending.difference_update(completed)
                completed_images, completed_errors = _resolve_completed_image_futures(completed, futures, results)
                for index, item in completed_images:
                    yield {
                        "type": "image",
                        "created": int(time.time()),
                        "index": index,
                        "item": item,
                    }
                for error in completed_errors:
                    errors.append(error)
                    yield {
                        "type": "error",
                        "created": int(time.time()),
                        **error,
                    }
                if not pending:
                    continue
                timeout_errors = _pending_batch_timeout_errors(
                    pending,
                    futures,
                    int(ctx["batch_timeout_seconds"]),
                )
                break
            completed, pending = wait(
                pending,
                timeout=min(STREAM_HEARTBEAT_INTERVAL_SECS, remaining),
                return_when=FIRST_COMPLETED,
            )
            if not completed:
                if time.monotonic() >= batch_deadline:
                    continue
                yield {
                    "type": "heartbeat",
                    "created": int(time.time()),
                    "elapsed_seconds": int(time.monotonic() - started_at),
                    "remaining_seconds": max(0, math.ceil(batch_deadline - time.monotonic())),
                    "pending": len(pending),
                    "requested": n,
                }
                continue
            completed_images, completed_errors = _resolve_completed_image_futures(completed, futures, results)
            for index, item in completed_images:
                yield {
                    "type": "image",
                    "created": int(time.time()),
                    "index": index,
                    "item": item,
                }
            for error in completed_errors:
                errors.append(error)
                yield {
                    "type": "error",
                    "created": int(time.time()),
                    **error,
                }
    finally:
        _shutdown_image_batch(executor, pending, cancel_event)

    if timeout_errors:
        errors.extend(timeout_errors)
        for error in timeout_errors:
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
        "requested": n,
        "completed": len(data),
    }
    if errors:
        final["partial_errors"] = sorted(errors, key=lambda item: int(item.get("index") or 0))
    if not data:
        final["error"] = _errors_message(errors)
        if any(str(item.get("error_code") or "") == "provider_timeout" for item in errors):
            final["error_code"] = "provider_timeout"
    if any(str(item.get("error_code") or "") == "provider_timeout" for item in errors):
        final["timed_out"] = True
    yield final
