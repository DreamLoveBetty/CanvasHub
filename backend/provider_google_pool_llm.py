"""Google OAuth account-pool LLM transport for prompt tools.

Talks only to the local Google pool sidecar (`/v1beta/models...`); the sidecar owns
accounts, tokens, quota and account rotation. No credentials are returned here.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from io import BytesIO
from typing import Any, Callable, Iterator

import requests

PROVIDER_ID = "google_pool"
PROVIDER_LABEL = "Google OAuth 账号池"
DEFAULT_MODEL_PREFERENCE = (
    "gemini-3-flash",
    "gemini-2.5-flash",
    "claude-sonnet-4-6",
    "gemini-2.5-pro",
)
_TEXT_PREFIXES = ("gemini-", "claude-", "gpt-oss-")
_EXCLUDED_PREFIXES = ("chat_", "tab_")
_LABELS = {
    "gemini-3-flash": "Gemini 3 Flash",
    "gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite",
    "gemini-3.5-flash-lite": "Gemini 3.5 Flash Lite",
    "gemini-3.8-flash-tiered": "Gemini 3.8 Flash Tiered",
    "gemini-2.5-pro": "Gemini 2.5 Pro",
    "gemini-2.5-flash": "Gemini 2.5 Flash",
    "gemini-2.5-flash-lite": "Gemini 2.5 Flash Lite",
    "gemini-2.5-flash-thinking": "Gemini 2.5 Flash Thinking",
    "claude-sonnet-4-6": "Claude Sonnet 4.6",
    "claude-opus-4-6-thinking": "Claude Opus 4.6 Thinking",
    "gpt-oss-120b-medium": "GPT-OSS 120B Medium",
}


def is_text_model(name: str) -> bool:
    model = str(name or "").strip().lower().removeprefix("models/")
    if not model or "-image" in model or model.startswith(_EXCLUDED_PREFIXES):
        return False
    return model.startswith(_TEXT_PREFIXES)


def model_label(name: str) -> str:
    if name in _LABELS:
        return _LABELS[name]
    match = re.fullmatch(r"claude-(opus|sonnet|haiku)-(\d+)-(\d+)(?:-(.+))?", name)
    if match:
        family, major, minor, tier = match.groups()
        label = f"Claude {family.title()} {major}.{minor}"
        return f"{label} {tier.title()}" if tier else label
    return name


class GooglePoolLLM:
    def __init__(
        self,
        get_transport: Callable[[], dict[str, Any]],
        session_factory: Callable[[], requests.Session] = requests.Session,
        timeout_seconds: int = 180,
    ):
        self.get_transport = get_transport
        self.session_factory = session_factory
        self.timeout_seconds = timeout_seconds

    # -- transport -------------------------------------------------------------
    def _connection(self) -> tuple[str, dict[str, str]]:
        cfg = self.get_transport() or {}
        base = str(cfg.get("base_url") or "http://127.0.0.1:18080").rstrip("/")
        key = str(cfg.get("auth_key") or "")
        if not key:
            raise RuntimeError("账号服务认证未配置，请先配置 sidecar")
        return base, {"Authorization": "Bearer " + key}

    def _session(self) -> requests.Session:
        session = self.session_factory()
        session.trust_env = False
        return session

    @staticmethod
    def _error_message(response: requests.Response, fallback: str) -> str:
        try:
            data = response.json()
            if isinstance(data, dict) and data.get("error"):
                return str(data["error"])
        except ValueError:
            pass
        return f"{fallback}（HTTP {response.status_code}）"

    # -- models ----------------------------------------------------------------
    def refresh_catalog(self) -> dict[str, Any]:
        base, headers = self._connection()
        try:
            with self._session() as s, s.post(
                base + "/api/google-pool/models-refresh",
                headers=headers,
                json={},
                timeout=(5, 150),
                allow_redirects=False,
            ) as r:
                if not 200 <= r.status_code < 300:
                    raise RuntimeError(self._error_message(r, "Google 账号池模型刷新失败"))
                data = r.json()
                return data if isinstance(data, dict) else {}
        except requests.RequestException:
            raise RuntimeError("Google 账号池服务无法连接，请检查 sidecar 是否已启动") from None

    def list_models(self, refresh: bool = False) -> tuple[list[dict[str, Any]], str]:
        warning = ""
        if refresh:
            try:
                result = self.refresh_catalog()
                errors = result.get("errors") or []
                if errors:
                    warning = "部分账号刷新失败：" + "；".join(str(e) for e in errors[:2])
            except RuntimeError as exc:
                warning = str(exc)
        try:
            names = self._fetch_model_names()
        except RuntimeError as exc:
            return [], str(exc)
        if not names and not refresh:
            # Accounts last refreshed by an image-only sidecar have no LLM catalog yet.
            try:
                self.refresh_catalog()
                names = self._fetch_model_names()
            except RuntimeError as exc:
                warning = str(exc)
        models = [
            {
                "id": name,
                "label": model_label(name),
                "description": "Google OAuth 账号池",
                "default_reasoning_effort": "",
                "reasoning_efforts": [],
                "available": True,
            }
            for name in names
        ]
        if not models and not warning:
            warning = "Google 账号池暂无可用 LLM 模型，请先在账号池添加并刷新账号"
        return models, warning

    def _fetch_model_names(self) -> list[str]:
        base, headers = self._connection()
        try:
            with self._session() as s, s.get(
                base + "/v1beta/models",
                params={"type": "text"},
                headers=headers,
                timeout=(5, 30),
                allow_redirects=False,
            ) as r:
                if not 200 <= r.status_code < 300:
                    raise RuntimeError(self._error_message(r, "Google 账号池模型读取失败"))
                data = r.json()
        except requests.RequestException:
            raise RuntimeError("Google 账号池服务无法连接，请检查 sidecar 是否已启动") from None
        except ValueError:
            raise RuntimeError("Google 账号池返回无效模型列表") from None
        names = []
        for item in (data.get("models") if isinstance(data, dict) else None) or []:
            name = str((item or {}).get("name") or "").removeprefix("models/")
            if is_text_model(name):
                names.append(name)
        return sorted(set(names), key=self._sort_key)

    @staticmethod
    def _sort_key(name: str) -> tuple[int, str]:
        if name in DEFAULT_MODEL_PREFERENCE:
            return (DEFAULT_MODEL_PREFERENCE.index(name), name)
        order = 10 if name.startswith("gemini-") else 20 if name.startswith("claude-") else 30
        return (order, name)

    @staticmethod
    def default_model(models: list[dict[str, Any]]) -> str:
        ids = [str(m.get("id") or "") for m in models]
        for name in DEFAULT_MODEL_PREFERENCE:
            if name in ids:
                return name
        return ids[0] if ids else ""

    # -- generation ------------------------------------------------------------
    @staticmethod
    def _inline_image(image: str) -> dict[str, Any] | None:
        value = str(image or "").strip()
        if not value:
            return None
        if value.startswith(("http://", "https://")):
            try:
                resp = requests.get(value, timeout=(5, 30))
                resp.raise_for_status()
                raw = resp.content
            except requests.RequestException:
                return None
        else:
            match = re.match(r"^data:image/[a-zA-Z0-9.+-]+;base64,(.*)$", value, re.S)
            payload = match.group(1) if match else value
            try:
                raw = base64.b64decode(payload, validate=False)
            except (binascii.Error, ValueError):
                return None
        if not raw:
            return None
        mime = _detect_mime(raw)
        if mime is None:
            raw, mime = _to_jpeg(raw)
            if raw is None:
                return None
        return {"inlineData": {"mimeType": mime, "data": base64.b64encode(raw).decode("ascii")}}

    def build_body(self, prompt: str, system: str, images: list[str] | None = None) -> dict[str, Any]:
        parts: list[dict[str, Any]] = [{"text": str(prompt or "")}]
        for image in images or []:
            part = self._inline_image(image)
            if part:
                parts.append(part)
        body: dict[str, Any] = {"contents": [{"role": "user", "parts": parts}]}
        if str(system or "").strip():
            body["systemInstruction"] = {"parts": [{"text": str(system).strip()}]}
        return body

    def stream(self, prompt: str, system: str, model: str, images: list[str] | None = None) -> Iterator[str]:
        if not is_text_model(model):
            raise RuntimeError(f"不是 Google 账号池 LLM 模型：{model}")
        base, headers = self._connection()
        body = self.build_body(prompt, system, images)
        emitted = False
        final_text = ""
        try:
            with self._session() as s, s.post(
                f"{base}/v1beta/models/{model}:streamGenerateContent?alt=sse",
                headers={**headers, "Accept": "text/event-stream"},
                json=body,
                stream=True,
                timeout=(15, self.timeout_seconds),
                allow_redirects=False,
            ) as r:
                if not 200 <= r.status_code < 300:
                    raise RuntimeError(self._error_message(r, "Google 账号池推理失败"))
                for raw_line in r.iter_lines(decode_unicode=False):
                    if not raw_line:
                        continue
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except ValueError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    if event.get("error"):
                        raise RuntimeError(str(event.get("error")))
                    text = _candidate_text(event)
                    if event.get("google_pool_delta"):
                        if text:
                            emitted = True
                            yield text
                        continue
                    final_text = text
                    break
        except requests.RequestException as exc:
            raise RuntimeError(f"Google 账号池推理连接中断：{type(exc).__name__}") from None
        if not emitted:
            if not final_text:
                raise RuntimeError("Google 账号池模型未返回内容")
            yield final_text

    def call(self, prompt: str, system: str, model: str, images: list[str] | None = None) -> str:
        return "".join(self.stream(prompt, system, model, images)).strip()


def _candidate_text(event: dict[str, Any]) -> str:
    texts = []
    for candidate in event.get("candidates") or []:
        content = (candidate or {}).get("content") or {}
        for part in content.get("parts") or []:
            if isinstance(part, dict) and part.get("thought") is not True and isinstance(part.get("text"), str):
                texts.append(part["text"])
    return "".join(texts)


def _detect_mime(raw: bytes) -> str | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def _to_jpeg(raw: bytes) -> tuple[bytes | None, str]:
    try:
        from PIL import Image  # type: ignore

        with Image.open(BytesIO(raw)) as picture:
            out = BytesIO()
            picture.convert("RGB").save(out, format="JPEG", quality=88)
            return out.getvalue(), "image/jpeg"
    except Exception:
        return None, ""
