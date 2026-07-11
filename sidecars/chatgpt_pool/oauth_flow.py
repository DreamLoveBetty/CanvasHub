from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
import uuid
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse

import requests as std_requests

try:
    from curl_cffi import requests as curl_requests
except Exception:  # pragma: no cover - optional runtime hardening
    curl_requests = None

from .account_store import AccountStore
from .openai_backend import OpenAIBackend


AUTH_BASE = "https://auth.openai.com"
PLATFORM_BASE = "https://platform.openai.com"
CLIENT_ID = "app_2SKx67EdpoN0G6j64rFvigXD"
REDIRECT_URI = f"{PLATFORM_BASE}/auth/callback"
AUDIENCE = "https://api.openai.com/v1"
AUTH0_CLIENT = "eyJuYW1lIjoiYXV0aDAtc3BhLWpzIiwidmVyc2lvbiI6IjEuMjEuMCJ9"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
SESSION_TTL_SECONDS = 10 * 60
COMPLETED_TTL_SECONDS = 10 * 60


class OAuthError(RuntimeError):
    pass


class OAuthService:
    def __init__(
        self,
        store: AccountStore,
        token_exchange: Callable[[str, str, str], dict[str, str]] | None = None,
        profile_fetcher: Callable[[str], dict[str, Any]] | None = None,
    ):
        self.store = store
        self._token_exchange = token_exchange or self._exchange_code
        self._profile_fetcher = profile_fetcher or self._fetch_profile
        self._lock = threading.RLock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._completed: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _fetch_profile(access_token: str) -> dict[str, Any]:
        return OpenAIBackend(access_token, timeout_seconds=60).fetch_account_profile()

    @staticmethod
    def _public_result(result: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in result.items() if not str(key).startswith("_")}

    def _cleanup_locked(self) -> None:
        now = time.time()
        expired_sessions = [
            session_id
            for session_id, session in self._sessions.items()
            if not session.get("exchanging") and float(session.get("expires_at") or 0) <= now
        ]
        for session_id in expired_sessions:
            self._sessions.pop(session_id, None)
        expired_completed = [
            session_id
            for session_id, result in self._completed.items()
            if float(result.get("_expires_at") or 0) <= now
        ]
        for session_id in expired_completed:
            self._completed.pop(session_id, None)

    def _release_exchange(self, session_id: str, error: Exception) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return
            session["exchanging"] = False
            session["last_error"] = str(error)

    def _store_completed_locked(self, session_id: str, state: str, result: dict[str, Any]) -> dict[str, Any]:
        completed = {
            **result,
            "ok": True,
            "pending": False,
            "session_id": session_id,
            "status": "completed",
            "_state": state,
            "_expires_at": time.time() + COMPLETED_TTL_SECONDS,
        }
        self._completed[session_id] = completed
        return self._public_result(completed)

    @staticmethod
    def _pkce() -> tuple[str, str]:
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        return verifier, challenge

    def start(self, email_hint: str = "", force_reauth: bool = False) -> dict[str, str]:
        verifier, challenge = self._pkce()
        session_id = uuid.uuid4().hex
        state = f"{session_id}.{secrets.token_urlsafe(16)}"
        params = {
            "issuer": AUTH_BASE,
            "client_id": CLIENT_ID,
            "audience": AUDIENCE,
            "redirect_uri": REDIRECT_URI,
            "device_id": str(uuid.uuid4()),
            "scope": "openid profile email offline_access",
            "response_type": "code",
            "response_mode": "query",
            "state": state,
            "nonce": secrets.token_urlsafe(32),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "auth0Client": AUTH0_CLIENT,
            "screen_hint": "login_or_signup",
            "max_age": "0",
        }
        # Kept for API compatibility with the frontend. The upstream flow is
        # more reliable when it always starts a fresh platform OAuth session.
        if force_reauth:
            params["screen_hint"] = "login_or_signup"
            params["max_age"] = "0"
        if str(email_hint or "").strip():
            params["login_hint"] = str(email_hint).strip()
        now = time.time()
        with self._lock:
            self._cleanup_locked()
            self._sessions[session_id] = {
                "code_verifier": verifier,
                "state": state,
                "created_at": now,
                "expires_at": now + SESSION_TTL_SECONDS,
                "redirect_uri": REDIRECT_URI,
                "exchanging": False,
            }
        return {
            "session_id": session_id,
            "state": state,
            "authorize_url": f"{AUTH_BASE}/api/accounts/authorize?{urlencode(params)}",
            "redirect_uri_prefix": REDIRECT_URI,
            "expires_in": str(SESSION_TTL_SECONDS),
        }

    @staticmethod
    def _code_and_state(callback: str) -> tuple[str, str]:
        raw = str(callback or "").strip()
        if not raw:
            return "", ""
        if raw.startswith(("http://", "https://")):
            parsed = parse_qs(urlparse(raw).query)
            return str((parsed.get("code") or [""])[0]).strip(), str((parsed.get("state") or [""])[0]).strip()
        return raw, ""

    def finish(self, session_id: str, callback: str) -> dict[str, Any]:
        code, state = self._code_and_state(callback)
        if not code:
            raise OAuthError("missing OAuth code")
        state_sid = state.split(".", 1)[0] if state else ""
        sid = state_sid or str(session_id or "").strip()
        if not sid:
            raise OAuthError("missing OAuth session")

        with self._lock:
            self._cleanup_locked()
            completed = self._completed.get(sid)
            if completed:
                if state and completed.get("_state") and state != completed["_state"]:
                    raise OAuthError("OAuth state mismatch")
                return self._public_result(completed)
            session = self._sessions.get(sid)
            if not session:
                raise OAuthError("OAuth session expired or not found")
            if state and session.get("state") and state != session["state"]:
                raise OAuthError("OAuth state mismatch")
            if session.get("exchanging"):
                return {
                    "ok": True,
                    "pending": True,
                    "session_id": sid,
                    "status": "exchanging",
                    "message": "OAuth token exchange is already in progress",
                }
            session["exchanging"] = True
            session.pop("last_error", None)
            exchange_session = dict(session)
            token_data = dict(session.get("_token_data") or {})

        if not token_data:
            try:
                token_data = self._token_exchange(
                    code,
                    str(exchange_session.get("code_verifier") or ""),
                    str(exchange_session.get("redirect_uri") or REDIRECT_URI),
                )
            except Exception as exc:
                if isinstance(exc, OAuthError):
                    self._release_exchange(sid, exc)
                    raise
                error = OAuthError(f"OAuth token exchange failed: {exc}")
                self._release_exchange(sid, error)
                raise error from exc
            if not token_data.get("access_token") or not token_data.get("refresh_token"):
                error = OAuthError("OAuth token response missing access_token or refresh_token")
                self._release_exchange(sid, error)
                raise error
            with self._lock:
                current = self._sessions.get(sid)
                if current:
                    current["_token_data"] = dict(token_data)

        access_token = str(token_data.get("access_token") or "")
        try:
            result = self.store.upsert_accounts([{**token_data, "source_type": "oauth_login"}])
        except Exception as exc:
            error = OAuthError(f"OAuth account save failed: {exc}")
            self._release_exchange(sid, error)
            raise error from exc

        try:
            profile = self._profile_fetcher(access_token)
            updates = {key: value for key, value in profile.items() if key in {"email", "user_id", "plan_type"} and value}
            if updates:
                self.store.update_account(access_token, updates)
                result["items"] = self.store.list_public_accounts()
        except Exception:
            pass

        final_result = {
            **result,
            "account": self.store.public_account(access_token) or {},
        }
        with self._lock:
            self._sessions.pop(sid, None)
            return self._store_completed_locked(sid, str(exchange_session.get("state") or state), final_result)

    @staticmethod
    def _is_curl_tls_runtime_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return "tls connect error" in message or "openssl_internal:invalid library" in message

    @staticmethod
    def _exchange_code(code: str, code_verifier: str, redirect_uri: str) -> dict[str, str]:
        headers = {
            "accept": "application/json",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/json",
            "origin": PLATFORM_BASE,
            "referer": f"{PLATFORM_BASE}/",
            "user-agent": USER_AGENT,
            "auth0-client": AUTH0_CLIENT,
            "sec-ch-ua": '"Google Chrome";v="145", "Not?A_Brand";v="8", "Chromium";v="145"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        }
        payload = {
            "client_id": CLIENT_ID,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
        response = None
        curl_session = None
        curl_error: Exception | None = None
        if curl_requests is not None:
            try:
                curl_session = curl_requests.Session(impersonate="chrome", verify=False)
                response = curl_session.post(
                    f"{AUTH_BASE}/api/accounts/oauth/token",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
            except Exception as exc:
                if not OAuthService._is_curl_tls_runtime_error(exc):
                    raise OAuthError(f"OAuth token exchange request failed: {exc}") from exc
                curl_error = exc
            finally:
                if curl_session is not None:
                    curl_session.close()

        if response is None:
            try:
                response = std_requests.post(
                    f"{AUTH_BASE}/api/accounts/oauth/token",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
            except Exception as exc:
                fallback_detail = f"; curl_cffi TLS error: {curl_error}" if curl_error else ""
                raise OAuthError(f"OAuth token exchange request failed: {exc}{fallback_detail}") from exc

        try:
            data = response.json() if response.text else {}
        except ValueError:
            data = {}
        if response.status_code != 200 or not isinstance(data, dict):
            detail = ""
            if isinstance(data, dict):
                detail = str(data.get("error_description") or data.get("error") or data.get("message") or "")
            detail = detail or str(getattr(response, "text", "") or "")[:300]
            raise OAuthError(f"OAuth token exchange failed: HTTP {response.status_code}{': ' + detail if detail else ''}")
        return {
            "access_token": str(data.get("access_token") or ""),
            "refresh_token": str(data.get("refresh_token") or ""),
            "id_token": str(data.get("id_token") or ""),
        }
