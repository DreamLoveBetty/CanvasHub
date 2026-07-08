from __future__ import annotations

from typing import Any, Callable

from .account_pool import AccountPool
from .backend_runtime import build_backend_for_lease, mark_verification_required, verification_exhausted_message
from .openai_backend import OpenAIBackend, SEARCH_MODEL, SEARCH_POLL_INTERVAL_SECS, SEARCH_TIMEOUT_SECS, VerificationRequiredError


def search_web(
    body: dict[str, Any],
    pool: AccountPool,
    backend_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    prompt = str(body.get("prompt") or body.get("query") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    model = str(body.get("model") or SEARCH_MODEL).strip() or SEARCH_MODEL
    try:
        timeout_secs = float(body.get("timeout_seconds") or body.get("timeout") or SEARCH_TIMEOUT_SECS)
    except (TypeError, ValueError):
        timeout_secs = SEARCH_TIMEOUT_SECS
    timeout_secs = max(30.0, min(900.0, timeout_secs))
    backend_factory = backend_factory or OpenAIBackend

    skipped_tokens: set[str] = set()
    verification_errors: list[str] = []
    while True:
        lease = None
        try:
            lease = pool.acquire_available(exclude_tokens=skipped_tokens)
            backend = build_backend_for_lease(backend_factory, lease)
            result = backend.search(
                prompt,
                model=model,
                timeout_secs=timeout_secs,
                poll_interval_secs=SEARCH_POLL_INTERVAL_SECS,
            )
            pool.mark_result(lease.access_token, True)
            return {"ok": True, "model": model, "result": result}
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
