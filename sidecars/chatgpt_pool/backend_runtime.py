from __future__ import annotations

from typing import Any, Callable

from .account_pool import AccountLease, AccountPool
from .account_store import VERIFICATION_STATUS
from .openai_backend import OpenAIBackend


def build_backend_for_lease(
    backend_factory: Callable[..., Any],
    lease: AccountLease,
    timeout_seconds: int | None = None,
    deadline_monotonic: float | None = None,
    cancel_event: Any = None,
) -> Any:
    if backend_factory is OpenAIBackend:
        kwargs: dict[str, Any] = {}
        if timeout_seconds is not None:
            kwargs["timeout_seconds"] = timeout_seconds
        if deadline_monotonic is not None:
            kwargs["deadline_monotonic"] = deadline_monotonic
        if cancel_event is not None:
            kwargs["cancel_event"] = cancel_event
        return backend_factory(lease.access_token, **kwargs)
    if timeout_seconds is not None:
        try:
            backend = backend_factory(lease.access_token, timeout_seconds=timeout_seconds)
            set_deadline = getattr(backend, "set_image_deadline", None)
            if callable(set_deadline) and deadline_monotonic is not None:
                set_deadline(deadline_monotonic, cancel_event=cancel_event)
            return backend
        except TypeError:
            pass
    backend = backend_factory(lease.access_token)
    set_deadline = getattr(backend, "set_image_deadline", None)
    if callable(set_deadline) and deadline_monotonic is not None:
        set_deadline(deadline_monotonic, cancel_event=cancel_event)
    return backend


def mark_verification_required(pool: AccountPool, access_token: str, error: str) -> None:
    message = str(error or "ChatGPT web verification required")[:600]
    try:
        pool.store.update_account(
            access_token,
            {
                "status": VERIFICATION_STATUS,
                "quota": 0,
                "image_quota_unknown": True,
                "restore_at": "",
            },
        )
    finally:
        pool.mark_result(access_token, False, message)


def verification_exhausted_message(pool: AccountPool, errors: list[str] | None = None) -> str:
    messages = list(errors or [])
    for account in pool.store.list_public_accounts():
        if str(account.get("status") or "") != VERIFICATION_STATUS:
            continue
        email = str(account.get("email") or "")
        messages.append(f"{email}: 需要浏览器验证" if email else "账号需要浏览器验证")
    if messages:
        return "ChatGPT account pool has no ready accounts: " + " | ".join(messages)
    return "ChatGPT account pool has no ready accounts"
