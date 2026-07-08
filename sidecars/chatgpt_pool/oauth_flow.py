from __future__ import annotations

import base64
import hashlib
import secrets
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


class OAuthError(RuntimeError):
    pass


class OAuthService:
    def __init__(
        self,
        store: AccountStore,
        token_exchange: Callable[[str, str, str], dict[str, str]] | None = None,
    ):
        self.store = store
        self._token_exchange = token_exchange or self._exchange_code
        self._sessions: dict[str, dict[str, Any]] = {}

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
        self._sessions[session_id] = {
            "code_verifier": verifier,
            "state": state,
            "created_at": time.time(),
            "redirect_uri": REDIRECT_URI,
        }
        return {
            "session_id": session_id,
            "state": state,
            "authorize_url": f"{AUTH_BASE}/api/accounts/authorize?{urlencode(params)}",
            "redirect_uri_prefix": REDIRECT_URI,
            "expires_in": "600",
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
        session = self._sessions.get(sid)
        if not session:
            raise OAuthError("OAuth session expired or not found")
        if state and session.get("state") and state != session["state"]:
            raise OAuthError("OAuth state mismatch")
        token_data = self._token_exchange(code, session["code_verifier"], str(session.get("redirect_uri") or REDIRECT_URI))
        if not token_data.get("access_token") or not token_data.get("refresh_token"):
            raise OAuthError("OAuth token response missing access_token or refresh_token")
        result = self.store.upsert_accounts([{**token_data, "source_type": "oauth_login"}])
        try:
            profile = OpenAIBackend(str(token_data.get("access_token") or ""), timeout_seconds=60).fetch_account_profile()
            updates = {key: value for key, value in profile.items() if key in {"email", "user_id", "plan_type"} and value}
            if updates:
                self.store.update_account(str(token_data.get("access_token") or ""), updates)
                result["items"] = self.store.list_public_accounts()
        except Exception:
            pass
        self._sessions.pop(sid, None)
        return {"ok": True, "account": result["items"][0] if result.get("items") else {}, **result}

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
        session = None
        try:
            if curl_requests is not None:
                session = curl_requests.Session(impersonate="chrome", verify=False)
                response = session.post(
                    f"{AUTH_BASE}/api/accounts/oauth/token",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
            else:
                response = std_requests.post(
                    f"{AUTH_BASE}/api/accounts/oauth/token",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
        finally:
            if session is not None:
                session.close()
        data = response.json() if response.text else {}
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
