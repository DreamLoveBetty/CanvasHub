from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from .account_store import AccountStore, NORMAL_STATUS

DEFAULT_LEASE_TIMEOUT_SECONDS = 900


@dataclass(frozen=True)
class AccountLease:
    access_token: str
    email: str
    plan_type: str


class AccountPool:
    def __init__(self, store: AccountStore, max_concurrency: int = 1, lease_timeout_seconds: int = DEFAULT_LEASE_TIMEOUT_SECONDS):
        self.store = store
        self.max_concurrency = max(1, int(max_concurrency or 1))
        self.lease_timeout_seconds = max(60, int(lease_timeout_seconds or DEFAULT_LEASE_TIMEOUT_SECONDS))
        self._lock = threading.RLock()
        self._index = 0
        self._inflight: dict[str, list[float]] = {}

    @staticmethod
    def _is_available(account: dict[str, Any]) -> bool:
        if account.get("status") != NORMAL_STATUS:
            return False
        if bool(account.get("image_quota_unknown")):
            return True
        return int(account.get("quota") or 0) > 0

    def _prune_stale_inflight_locked(self, now: float | None = None) -> None:
        cutoff = float(now if now is not None else time.monotonic()) - self.lease_timeout_seconds
        stale_tokens = []
        for token, started_at_values in list(self._inflight.items()):
            fresh = [started_at for started_at in started_at_values if float(started_at or 0.0) >= cutoff]
            if fresh:
                self._inflight[token] = fresh
            else:
                stale_tokens.append(token)
        for token in stale_tokens:
            self._inflight.pop(token, None)

    def _inflight_count_locked(self, access_token: str) -> int:
        return len(self._inflight.get(str(access_token or ""), []))

    def acquire_available(self, exclude_tokens: set[str] | None = None) -> AccountLease:
        with self._lock:
            excluded = {str(token or "") for token in (exclude_tokens or set())}
            self._prune_stale_inflight_locked()
            candidates = [row for row in self.store.list_private_accounts() if self._is_available(row)]
            candidates = [
                row
                for row in candidates
                if str(row.get("access_token") or "") not in excluded
            ]
            candidates = [
                row
                for row in candidates
                if self._inflight_count_locked(str(row.get("access_token") or "")) < self.max_concurrency
            ]
            if not candidates:
                raise RuntimeError("no available image quota")
            account = candidates[self._index % len(candidates)]
            self._index += 1
            token = str(account.get("access_token") or "")
            self._inflight.setdefault(token, []).append(time.monotonic())
            return AccountLease(
                access_token=token,
                email=str(account.get("email") or ""),
                plan_type=str(account.get("plan_type") or "unknown"),
            )

    def release(self, access_token: str) -> None:
        token = str(access_token or "")
        if not token:
            return
        with self._lock:
            started_at_values = self._inflight.get(token) or []
            if len(started_at_values) <= 1:
                self._inflight.pop(token, None)
            else:
                self._inflight[token] = started_at_values[1:]

    def mark_result(self, access_token: str, success: bool, error: str = "") -> None:
        self.release(access_token)
        self.store.record_result(access_token, success, error)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            self._prune_stale_inflight_locked()
            private_accounts = self.store.list_private_accounts()
            stats = self.store.stats()
            inflight_total = sum(len(values) for values in self._inflight.values())
            saturated_tokens = {
                token
                for token, values in self._inflight.items()
                if len(values or []) >= self.max_concurrency
            }
            ready_accounts = [
                row
                for row in private_accounts
                if self._is_available(row) and str(row.get("access_token") or "") not in saturated_tokens
            ]
            stats["inflight"] = inflight_total
            stats["busy_accounts"] = sum(1 for values in self._inflight.values() if len(values or []) > 0)
            stats["available"] = len(ready_accounts)
            stats["capacity"] = sum(
                max(0, self.max_concurrency - self._inflight_count_locked(str(row.get("access_token") or "")))
                for row in private_accounts
                if self._is_available(row)
            )
            stats["max_account_concurrency"] = self.max_concurrency
        return stats
