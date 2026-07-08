from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import requests as std_requests

try:
    from curl_cffi import requests as curl_requests
except Exception:  # pragma: no cover - optional runtime hardening
    curl_requests = None

from .account_store import AccountStore, LIMITED_STATUS, NORMAL_STATUS
from .oauth_flow import CLIENT_ID
from .openai_backend import ImageGenerationStatus, OpenAIBackend
from .utils import now_iso, seconds_until_expiry


TOKEN_URL = "https://auth.openai.com/oauth/token"
LIMIT_PROBE_DELAY_SECONDS = 60
LIMIT_PROBE_TIMEOUT_SECONDS = 60


class AccountLimitProber:
    def __init__(
        self,
        store: AccountStore,
        backend_factory: Callable[..., Any] | None = None,
        probe_delay_seconds: int = LIMIT_PROBE_DELAY_SECONDS,
    ):
        self.store = store
        self._backend_factory = backend_factory or OpenAIBackend
        self.probe_delay_seconds = max(0, int(probe_delay_seconds or 0))

    @staticmethod
    def _parse_restore_at(value: str) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _probe_due(self, restore_at: str, now: datetime | None = None) -> bool:
        parsed = self._parse_restore_at(restore_at)
        if parsed is None:
            return False
        current = now or datetime.now(timezone.utc)
        return parsed + timedelta(seconds=self.probe_delay_seconds) <= current

    def _build_backend(self, access_token: str) -> Any:
        try:
            return self._backend_factory(
                access_token,
                timeout_seconds=LIMIT_PROBE_TIMEOUT_SECONDS,
            )
        except TypeError:
            try:
                return self._backend_factory(access_token, timeout_seconds=LIMIT_PROBE_TIMEOUT_SECONDS)
            except TypeError:
                return self._backend_factory(access_token)

    @staticmethod
    def _quota_updates(status: ImageGenerationStatus) -> dict[str, Any]:
        updates: dict[str, Any] = {"status": NORMAL_STATUS, "restore_at": ""}
        if status.remaining is None:
            updates["image_quota_unknown"] = True
        else:
            updates["quota"] = max(0, int(status.remaining or 0))
            updates["image_quota_unknown"] = False
        return updates

    def probe_due_accounts(self) -> dict[str, Any]:
        probed = 0
        reactivated = 0
        still_limited = 0
        skipped = 0
        errors: list[dict[str, str]] = []
        for account in self.store.list_private_accounts():
            token = str(account.get("access_token") or "")
            if not token or account.get("status") != LIMITED_STATUS:
                continue
            restore_at = str(account.get("restore_at") or "")
            if not self._probe_due(restore_at):
                skipped += 1
                continue
            probed += 1
            try:
                backend = self._build_backend(token)
                status = backend.check_image_generation_status()
                if isinstance(status, ImageGenerationStatus) and status.available:
                    self.store.update_account(token, self._quota_updates(status))
                    self.store.record_refresh_error(token, "")
                    reactivated += 1
                    continue
                still_limited += 1
                next_restore_at = str(getattr(status, "reset_after", "") or restore_at).strip()
                self.store.update_account(
                    token,
                    {
                        "status": LIMITED_STATUS,
                        "quota": 0,
                        "image_quota_unknown": False,
                        "restore_at": next_restore_at,
                    },
                )
                self.store.record_refresh_error(token, "image quota still limited")
            except Exception as exc:
                message = str(exc)
                self.store.record_refresh_error(token, f"limit_probe_failed: {message}")
                errors.append({"token_preview": token[:8] + "...", "error": message})
        return {
            "probed": probed,
            "reactivated": reactivated,
            "still_limited": still_limited,
            "skipped": skipped,
            "errors": errors,
            "items": self.store.list_public_accounts(),
        }


class TokenRefresher:
    def __init__(
        self,
        store: AccountStore,
        token_exchange: Callable[[str], dict[str, str]] | None = None,
        refresh_skew_seconds: int = 24 * 60 * 60,
    ):
        self.store = store
        self._token_exchange = token_exchange or self._exchange_refresh_token
        self.refresh_skew_seconds = refresh_skew_seconds

    def _sync_account_profile(self, access_token: str) -> None:
        try:
            profile = OpenAIBackend(
                access_token,
                timeout_seconds=60,
            ).fetch_account_profile()
        except Exception:
            return
        updates = {
            key: value
            for key, value in profile.items()
            if key in {"email", "user_id", "plan_type"} and str(value or "").strip()
        }
        if updates:
            self.store.update_account(access_token, updates)

    @staticmethod
    def _exchange_refresh_token(refresh_token: str) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
        }
        payload = {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": CLIENT_ID}
        session = None
        try:
            if curl_requests is not None:
                session = curl_requests.Session(impersonate="chrome", verify=True)
                response = session.post(TOKEN_URL, headers=headers, data=payload, timeout=60)
            else:
                response = std_requests.post(TOKEN_URL, headers=headers, data=payload, timeout=60)
        finally:
            if session is not None:
                session.close()
        data = response.json() if response.text else {}
        if response.status_code != 200 or not isinstance(data, dict) or not data.get("access_token"):
            detail = ""
            if isinstance(data, dict):
                detail = str(data.get("error_description") or data.get("error") or data.get("message") or "")
            detail = detail or str(getattr(response, "text", "") or "")[:300]
            raise RuntimeError(f"oauth_refresh_http_{response.status_code}{': ' + detail if detail else ''}")
        return {
            "access_token": str(data.get("access_token") or ""),
            "refresh_token": str(data.get("refresh_token") or refresh_token),
            "id_token": str(data.get("id_token") or ""),
        }

    def _needs_refresh(self, account: dict[str, Any], force: bool) -> bool:
        if force:
            return True
        remaining = seconds_until_expiry(str(account.get("access_token") or ""))
        return remaining is not None and remaining <= self.refresh_skew_seconds

    def refresh_expiring(self, force: bool = False) -> dict[str, Any]:
        refreshed = 0
        errors: list[dict[str, str]] = []
        for account in self.store.list_private_accounts():
            token = str(account.get("access_token") or "")
            refresh_token = str(account.get("refresh_token") or "")
            if not token or not refresh_token or not self._needs_refresh(account, force):
                continue
            try:
                token_data = self._token_exchange(refresh_token)
                account = self.store.apply_refreshed_tokens(token, token_data)
                self._sync_account_profile(str((account or {}).get("access_token") or token_data.get("access_token") or token))
                refreshed += 1
            except Exception as exc:
                self.store.record_refresh_error(token, str(exc))
                errors.append({"token_preview": token[:8] + "...", "error": str(exc)})
        return {"refreshed": refreshed, "errors": errors, "items": self.store.list_public_accounts()}

    def sync_account_profiles(self) -> dict[str, Any]:
        synced = 0
        errors: list[dict[str, str]] = []
        for account in self.store.list_private_accounts():
            token = str(account.get("access_token") or "")
            if not token:
                continue
            try:
                before = self.store.public_account(token) or {}
                self._sync_account_profile(token)
                after = self.store.public_account(token) or {}
                if any(before.get(key) != after.get(key) for key in ("email", "user_id", "plan_type")):
                    synced += 1
            except Exception as exc:
                errors.append({"token_preview": token[:8] + "...", "error": str(exc)})
        return {"synced": synced, "errors": errors, "items": self.store.list_public_accounts()}

    def keepalive_refresh_tokens(self, min_age_seconds: int = 3 * 24 * 60 * 60) -> dict[str, Any]:
        now = time.time()
        refreshed = 0
        errors: list[dict[str, str]] = []
        for account in self.store.list_private_accounts():
            token = str(account.get("access_token") or "")
            refresh_token = str(account.get("refresh_token") or "")
            if not token or not refresh_token:
                continue
            last = str(account.get("last_refresh_at") or account.get("created_at") or "")
            # If we cannot parse the timestamp cheaply, treat it as due; this is
            # intentionally conservative for keeping refresh tokens alive.
            due = True
            try:
                from datetime import datetime

                parsed = datetime.fromisoformat(last.replace("Z", "+00:00"))
                due = now - parsed.timestamp() >= min_age_seconds
            except Exception:
                due = True
            if not due:
                continue
            try:
                token_data = self._token_exchange(refresh_token)
                account = self.store.apply_refreshed_tokens(token, token_data)
                self._sync_account_profile(str((account or {}).get("access_token") or token_data.get("access_token") or token))
                refreshed += 1
            except Exception as exc:
                self.store.record_refresh_error(token, str(exc))
                errors.append({"token_preview": token[:8] + "...", "error": str(exc)})
        return {"refreshed": refreshed, "errors": errors, "items": self.store.list_public_accounts()}
