from __future__ import annotations

import base64
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable

from .account_pool import AccountPool
from .account_store import LIMITED_STATUS
from .backend_runtime import build_backend_for_lease, mark_verification_required, verification_exhausted_message
from .openai_backend import (
    EDITABLE_FILE_TIMEOUT_SECS,
    ImageGenerationLimitError,
    OpenAIBackend,
    VerificationRequiredError,
)


RETRYABLE_PSD_ACCOUNT_ERROR_MARKERS = (
    "system_error",
    "image generation service call failed",
    "timed out before the stream produced a conversation id",
    "timed out while reading stream",
    "image stream interrupted",
    "does not contain an alpha channel",
    "background is not truly transparent",
    "does not contain a detectable visible region",
    "transparent alpha split",
    "sslerror",
    "ssl eof",
    "unexpected_eof_while_reading",
    "remote end closed connection",
    "connection reset",
    "connection aborted",
    "max retries exceeded",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
)


def _is_retryable_psd_account_error(error: Exception | str) -> bool:
    text = str(error or "").strip().lower()
    return bool(text) and any(marker in text for marker in RETRYABLE_PSD_ACCOUNT_ERROR_MARKERS)


def _psd_account_errors_message(errors: list[str]) -> str:
    details = [str(item or "").strip() for item in errors if str(item or "").strip()]
    if not details:
        return "transparent PSD generation failed for all available ChatGPT accounts"
    return "transparent PSD generation failed after trying available ChatGPT accounts: " + " | ".join(details[:4])


def _mark_image_limited(pool: AccountPool, access_token: str, error: ImageGenerationLimitError, message: str) -> None:
    status = error.status
    try:
        pool.store.update_account(
            access_token,
            {
                "status": LIMITED_STATUS,
                "quota": 0,
                "image_quota_unknown": False,
                "restore_at": str(status.reset_after or "").strip(),
            },
        )
    finally:
        pool.mark_result(access_token, False, message)


def _artifact_payload(path: Path, role: str) -> dict[str, Any]:
    return {
        "role": role,
        "filename": path.name,
        "b64": base64.b64encode(path.read_bytes()).decode("ascii"),
        "size": path.stat().st_size,
    }


def generate_editable_file(
    body: dict[str, Any],
    pool: AccountPool,
    kind: str,
    backend_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    kind = str(kind or "").strip().lower()
    if kind not in {"ppt", "psd"}:
        raise ValueError("kind must be ppt or psd")
    base64_images = body.get("base64_images")
    if base64_images is None:
        base64_images = body.get("images")
    if not isinstance(base64_images, list):
        base64_images = []
    base64_images = [str(item or "").strip() for item in base64_images if str(item or "").strip()]
    if kind == "psd" and not base64_images:
        raise ValueError("psd generation requires base64_images")

    backend_factory = backend_factory or OpenAIBackend
    skipped_tokens: set[str] = set()
    verification_errors: list[str] = []
    psd_account_errors: list[str] = []
    image_limit_errors: list[str] = []
    while True:
        lease = None
        try:
            lease = pool.acquire_available(exclude_tokens=skipped_tokens)
            with TemporaryDirectory(prefix=f"chatgpt_pool_{kind}_") as tmp:
                backend = build_backend_for_lease(
                    backend_factory,
                    lease,
                    int(EDITABLE_FILE_TIMEOUT_SECS) if kind == "psd" else None,
                )
                if kind == "psd":
                    result = backend.export_psd_zip(base64_images, prompt, tmp)
                else:
                    result = backend.export_ppt_zip(base64_images, prompt, tmp)
                payload = {
                    "created": int(time.time()),
                    "task_id": str(body.get("client_task_id") or ""),
                    "status": "succeeded",
                    "kind": kind,
                    "model": "gpt-image-2" if kind == "psd" else "gpt-5-5-thinking",
                    "result": {
                        "conversation_id": str(result.get("conversation_id") if isinstance(result, dict) else result.conversation_id),
                        "primary": _artifact_payload(Path(result.get("primary_path") if isinstance(result, dict) else result.primary_path), "primary"),
                        "zip": _artifact_payload(Path(result.get("zip_path") if isinstance(result, dict) else result.zip_path), "source_zip"),
                    },
                }
            pool.mark_result(lease.access_token, True)
            return payload
        except ImageGenerationLimitError as exc:
            message = f"{lease.email}: {exc}" if lease and lease.email else str(exc)
            image_limit_errors.append(message)
            if lease is None:
                raise RuntimeError(_psd_account_errors_message(image_limit_errors)) from exc
            skipped_tokens.add(lease.access_token)
            _mark_image_limited(pool, lease.access_token, exc, message)
            continue
        except VerificationRequiredError as exc:
            message = f"{lease.email}: {exc}" if lease and lease.email else str(exc)
            verification_errors.append(message)
            if lease is None:
                raise RuntimeError(verification_exhausted_message(pool, verification_errors)) from exc
            skipped_tokens.add(lease.access_token)
            mark_verification_required(pool, lease.access_token, message)
            continue
        except RuntimeError as exc:
            if "no available image quota" in str(exc).lower():
                if psd_account_errors:
                    raise RuntimeError(_psd_account_errors_message([*verification_errors, *psd_account_errors])) from exc
                if image_limit_errors:
                    raise RuntimeError(_psd_account_errors_message(image_limit_errors)) from exc
                if verification_errors:
                    raise RuntimeError(verification_exhausted_message(pool, verification_errors)) from exc
            if kind == "psd" and lease is not None and _is_retryable_psd_account_error(exc):
                message = f"{lease.email}: {exc}" if lease.email else str(exc)
                psd_account_errors.append(message)
                skipped_tokens.add(lease.access_token)
                pool.mark_result(lease.access_token, False, str(exc))
                print(
                    f"[chatgpt-pool] transparent PSD generation failed for {lease.email or 'account'}; trying next account: {exc}",
                    flush=True,
                )
                continue
            if lease is not None:
                pool.mark_result(lease.access_token, False, str(exc))
            raise
        except Exception as exc:
            if kind == "psd" and lease is not None and _is_retryable_psd_account_error(exc):
                message = f"{lease.email}: {exc}" if lease.email else str(exc)
                psd_account_errors.append(message)
                skipped_tokens.add(lease.access_token)
                pool.mark_result(lease.access_token, False, str(exc))
                print(
                    f"[chatgpt-pool] transparent PSD transport failed for {lease.email or 'account'}; trying next account: {exc}",
                    flush=True,
                )
                continue
            if lease is not None:
                pool.mark_result(lease.access_token, False, str(exc))
            raise
