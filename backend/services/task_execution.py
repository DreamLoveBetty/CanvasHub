"""Bounded generation slots and worker-thread lifetime.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _current_generation_limit(*, _GENERATION_CONCURRENCY_LIMIT, get_max_concurrent_tasks):
    if _GENERATION_CONCURRENCY_LIMIT is not None:
        return _GENERATION_CONCURRENCY_LIMIT
    return get_max_concurrent_tasks()


def _generation_busy_message(*, _current_generation_limit):
    return f"生成任务已满（最多 {_current_generation_limit()} 个并发），请稍后重试"


def _generation_busy_payload(*, _current_generation_limit, _generation_busy_message):
    return {
        "ok": False,
        "error": "GenerationQueueFull",
        "message": _generation_busy_message(),
        "max_concurrent_tasks": _current_generation_limit(),
    }


def _acquire_generation_slot(*, _GENERATION_SEMAPHORE):
    """Try to acquire a generation slot. Returns False (no slot) without blocking."""
    sem = _GENERATION_SEMAPHORE
    if sem is None:
        return True
    acquired = sem.acquire(blocking=False)
    return bool(acquired)


def _release_generation_slot(*, _GENERATION_SEMAPHORE):
    """Release a generation slot. Safe to call even if semaphore is unset."""
    sem = _GENERATION_SEMAPHORE
    if sem is None:
        return
    try:
        sem.release()
    except ValueError:
        pass


def _run_generation_target(target, args, kwargs, *, _release_generation_slot):
    try:
        target(*args, **kwargs)
    finally:
        _release_generation_slot()


def _start_generation_thread(
    target,
    args=(),
    kwargs=None,
    *,
    _acquire_generation_slot,
    _release_generation_slot,
    _run_generation_target,
    threading,
):
    if not _acquire_generation_slot():
        return None
    kwargs = kwargs or {}
    thread = threading.Thread(
        target=_run_generation_target,
        args=(target, args, kwargs),
        daemon=True,
    )
    try:
        thread.start()
    except Exception:
        _release_generation_slot()
        raise
    return thread
