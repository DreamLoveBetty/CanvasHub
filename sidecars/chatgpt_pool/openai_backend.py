from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import queue
import re
import shutil
import subprocess
import threading
import time
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from PIL import Image, ImageChops, ImageStat

from .pow import build_legacy_requirements_token, build_proof_token, parse_pow_resources
from .utils import new_uuid


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
IMAGE_POLL_SETTLE_SECS = 2.0
IMAGE_LIBRARY_LOOKBACK_GRACE_SECS = 300.0
IMAGE_LIBRARY_RECENT_LIMIT = 25
IMAGE_LIBRARY_RECENT_MAX_PAGES = 3
IMAGE_STREAM_CONNECT_TIMEOUT_SECS = 30.0
IMAGE_STREAM_READ_TIMEOUT_SECS = 120.0
IMAGE_ACTIVE_STATUS_MARKERS = {"requested", "queued", "in_progress", "running", "processing", "pending"}
IMAGE_TERMINAL_STATUS_MARKERS = {"finished_successfully", "finished_partial_completion", "failed", "cancelled", "canceled"}
IMAGE_POLICY_REFUSAL_MARKERS = (
    "违反了我们的内容政策",
    "违反我们的内容政策",
    "可能违反内容政策",
    "生成的图片可能违反",
    "潜在欺诈或诈骗活动",
    "content policy",
    "safety policy",
    "can't help with that image",
    "cannot help with that image",
    "unable to generate that image",
    "can't create that image",
    "cannot create that image",
)
NETWORK_RETRY_ATTEMPTS = 3
NETWORK_RETRY_BASE_DELAY_SECS = 1.5
SEARCH_MODEL = "gpt-5-5"
SEARCH_TIMEOUT_SECS = 300.0
SEARCH_POLL_INTERVAL_SECS = 3.0
SEARCH_DONE_STATUS = {"finished_successfully", "finished_partial_completion"}
SEARCH_CONVERSATION_ID_RE = re.compile(r'"conversation_id"\s*:\s*"([^"]+)"')
SEARCH_URL_RE = re.compile(r"https?://[^\s\"'<>）)\]}]+")
CHAT_MODEL = "auto"
CHAT_TIMEOUT_SECS = 180.0
EDITABLE_FILE_MODEL = "gpt-5-5-thinking"
EDITABLE_FILE_THINKING_EFFORT = "extended"
EDITABLE_FILE_TIMEOUT_SECS = 1200.0
EDITABLE_FILE_POLL_INTERVAL_SECS = 5.0
EDITABLE_FILE_DOWNLOAD_TIMEOUT_SECS = 90.0
EDITABLE_FILE_DOWNLOAD_POLL_INTERVAL_SECS = 3.0
EDITABLE_FILE_CLIENT_VERSION = "prod-bede35f9dcd856d080e012478f0c1031faa2588e"
EDITABLE_FILE_CLIENT_BUILD_NUMBER = "6631702"
ADOBE_CONNECTOR_ID = "connector_69312da8e4dc81919370cb86fd172b6c"
ADOBE_CONNECTOR_NAME = "Adobe (formerly Photoshop)"
ADOBE_CONNECTOR_ACTIONS = [
    "adobe_mandatory_init",
    "asset_openai_file_upload",
    "image_select_subject",
    "image_select_by_prompt",
    "image_invert_selection",
    "image_remove_background",
]
ADOBE_CONNECTOR_SCOPES = ["AdobeID", "openid", "offline_access"]
ADOBE_CONNECTOR_CALLBACK_URL = "https://chatgpt.com/connector_platform_oauth_redirect"
ADOBE_GUEST_TOKEN_URL = "https://auth.services.adobe.com/signin/v1/ims/guest/tokens"
ADOBE_GUEST_EXCHANGE_URL = "https://adobeid-na1.services.adobe.com/ims/fromSusi"
ADOBE_GUEST_DEFAULT_CLIENT_ID = "oai-third-party-prod"
ADOBE_NETWORK_RETRY_ATTEMPTS = 3
ADOBE_NETWORK_RETRY_BASE_DELAY_SECS = 1.5
ADOBE_OAUTH_FLOW_ATTEMPTS = 2
ADOBE_MASK_SETTLE_SECS = 30.0
ADOBE_MAX_MASKS = 8
ADOBE_ADDITIONAL_MASK_COUNT = 4
ADOBE_ADDITIONAL_MASK_TIMEOUT_SECS = 90.0
PSD_MIN_FILE_SIZE = 1024
PSD_MIN_LAYER_COVERAGE = 0.0005
PSD_MAX_LAYER_COVERAGE = 0.995
EDITABLE_FILE_PPT_PROMPT = """我需要你根据用户的需求，来制作一个可以编辑的PPT，你可以使用Agent来做，你不要再继续询问用户问题，内容风格、版式、配色、内容结构和页面信息你可以自行补充并直接执行。整体的流程如下：
1. 用生图的方式，帮我生成一个精美的产品介绍ppt，5-6个页面
2. 帮我把以上涉及到的所有图像和形状素材拆分成单独png，每个素材单独一张图片，不要有遗漏，让我可以直接在ppt里拼接素材还原，不要文字
3. 利用以上所有图片和形状素材，帮我还原你第一次生成的展示ppt，我需要是可编辑的ppt格式，主要部分需要你单独还原插入，文字需要可以编辑
最后只需要给我生成一个PPT文件，以及生成中遇到的各种素材压缩包zip文件就行。"""
EDITABLE_FILE_PSD_PROMPT = """必须使用 Adobe (formerly Photoshop) 连接器处理上传图片。
先调用 adobe_mandatory_init，再调用 asset_openai_file_upload 上传图片，最后调用 image_select_subject 获取主主体黑白选区蒙版。
不要判断或解释连接器是否可用；工具已经完成授权，请在找到工具后直接调用。
不要调用 Python，不要生成 PSD，不要创建占位文件。完成后仅简短确认蒙版已生成。"""
ASSET_POINTER_RE = re.compile(r"(?:file-service|sediment)://([A-Za-z0-9_-]+)")
EDITABLE_ASSET_POINTER_RE = ASSET_POINTER_RE
EDITABLE_ZIP_MIME_TYPES = {"application/zip", "application/x-zip-compressed"}
EDITABLE_PSD_MIME_TYPES = {"image/vnd.adobe.photoshop", "application/vnd.adobe.photoshop"}
EDITABLE_PPT_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-powerpoint",
}
EDITABLE_PSD_EXPORT_FILE_RE = re.compile(r"(?:sandbox:)?(/mnt/data/[^\s\"'\)\]]+\.(?:psd|zip))", re.IGNORECASE)
EDITABLE_PPT_EXPORT_FILE_RE = re.compile(r"(?:sandbox:)?(/mnt/data/[^\s\"'\)\]]+\.(?:pptx?|zip))", re.IGNORECASE)
FILE_ID_RE = re.compile(r"\b(file[-_](?!service\b)[A-Za-z0-9_-]+)\b")
IMAGE_LIMIT_MARKERS = (
    "free plan limit for image generation",
    "image generations requests",
    "image generation quota",
    "image generation limit",
    "you've hit the free plan limit",
    "you have hit the free plan limit",
    "你已达到图片创建上限",
    "图片创建上限",
    "图片生成额度",
)


@dataclass
class EditableFileArtifact:
    attachment_id: str = ""
    file_id: str = ""
    name: str = ""
    mime_type: str = ""
    create_time: float = 0.0
    author_role: str = ""
    sandbox_path: str = ""
    message_id: str = ""


@dataclass
class EditableFileExportResult:
    conversation_id: str
    primary_path: Path
    zip_path: Path


@dataclass
class AdobeMaskArtifact:
    output_url: str
    description: str
    width: int = 0
    height: int = 0
    request_id: str = ""


class _AdobeOAuthFormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag.lower() == "form":
            self.current = {
                "action": values.get("action", ""),
                "method": values.get("method", "get").lower(),
                "id": values.get("id", ""),
                "fields": [],
            }
            self.forms.append(self.current)
        elif tag.lower() == "input" and self.current is not None and values.get("name"):
            self.current["fields"].append((values["name"], values.get("value", "")))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "form":
            self.current = None


class UpstreamError(RuntimeError):
    pass


class VerificationRequiredError(UpstreamError):
    def __init__(self, message: str = "ChatGPT web verification required", challenges: list[str] | None = None):
        self.challenges = list(challenges or [])
        detail = f"{message}: {', '.join(self.challenges)}" if self.challenges else message
        super().__init__(detail)


@dataclass
class ImageGenerationStatus:
    available: bool = True
    remaining: int | None = None
    reset_after: str = ""
    resets_after_text: str = ""
    limit: float | None = None
    title: str = ""
    description: str = ""


class ImageGenerationLimitError(UpstreamError):
    def __init__(self, status: ImageGenerationStatus | None = None, message: str = ""):
        self.status = status or ImageGenerationStatus(available=False)
        super().__init__(message or self._format_message(self.status))

    @staticmethod
    def _format_message(status: ImageGenerationStatus) -> str:
        parts = ["ChatGPT image generation quota reached"]
        if status.title:
            parts.append(status.title)
        if status.description:
            parts.append(status.description)
        if status.reset_after:
            parts.append(f"reset_after={status.reset_after}")
        if status.resets_after_text:
            parts.append(f"resets_after_text={status.resets_after_text}")
        if status.remaining is not None:
            parts.append(f"remaining={status.remaining}")
        if status.limit is not None:
            parts.append(f"limit={status.limit:g}")
        return "; ".join(parts)


@dataclass
class Requirements:
    token: str
    proof_token: str = ""
    turnstile_token: str = ""
    so_token: str = ""


def ensure_ok(response: requests.Response, context: str) -> None:
    if 200 <= int(response.status_code) < 300:
        return
    raise UpstreamError(f"{context} failed: HTTP {response.status_code}: {response.text[:500]}")


def iter_sse_payloads(response: requests.Response) -> Iterable[str]:
    for line in response.iter_lines(chunk_size=1024 * 1024, decode_unicode=True):
        if not line:
            continue
        if isinstance(line, bytes):
            line = line.decode("utf-8", "replace")
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload:
            yield payload


def add_unique(values: list[str], candidates: list[str]) -> None:
    for candidate in candidates:
        if candidate and candidate not in values:
            values.append(candidate)


def extract_ids(payload: str) -> tuple[str, list[str], list[str]]:
    conversation_match = re.search(r'"conversation_id"\s*:\s*"([^"]+)"', payload)
    conversation_id = conversation_match.group(1) if conversation_match else ""
    file_ids = re.findall(r"(file[-_](?!service\b)[A-Za-z0-9_-]+)", payload)
    attachment_ids = ASSET_POINTER_RE.findall(payload)
    return conversation_id, file_ids, attachment_ids


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_image_prompt(prompt: str, size: str | None, quality: str = "auto") -> str:
    """Map OpenAI-compatible image options onto the Web conversation prompt surface."""
    text = str(prompt or "").strip()
    hints: list[str] = []
    if size:
        hints.append(f"输出图片尺寸为 {size}。")
    quality_value = str(quality or "auto").strip().lower()
    if quality_value and quality_value != "auto":
        hints.append(f"输出图片质量为 {quality_value}。")
    return f"{text}\n\n{''.join(hints)}" if hints else text


def build_image_edit_prompt(prompt: str, size: str | None, quality: str = "auto", has_mask: bool = False) -> str:
    """Map OpenAI-compatible edit options onto the Web multimodal prompt surface."""
    text = str(prompt or "").strip()
    instructions = [
        "请基于上传的参考图进行图像编辑，保持未要求变化的主体、构图和视觉身份一致。",
        "只输出最终编辑后的图片，不需要解释过程。",
    ]
    if has_mask:
        instructions.append("最后一张上传图片是编辑蒙版：白色或不透明区域为可编辑区域，黑色或透明区域应尽量保持不变。")
    option_text = build_image_prompt("", size, quality).strip()
    if option_text:
        instructions.append(option_text)
    return "\n".join([text, "", *instructions]).strip()


class OpenAIBackend:
    def __init__(
        self,
        access_token: str,
        timeout_seconds: int = 420,
        deadline_monotonic: float | None = None,
        cancel_event: Any = None,
    ):
        # Lightweight legacy account-pool transport: keep the Web request surface
        # small and stable. Do not mix browser cookies, sec-ch hints, proxy/TLS
        # impersonation, or per-account browser profile data into this HTTP path.
        self.base_url = "https://chatgpt.com"
        self.access_token = access_token
        self.timeout_seconds = max(60, int(timeout_seconds or 420))
        self._image_deadline_monotonic = float(deadline_monotonic) if deadline_monotonic is not None else None
        self._image_cancel_event = cancel_event
        self.user_agent = USER_AGENT
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Origin": self.base_url,
                "Referer": self.base_url + "/",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "OAI-Language": "zh-CN",
                "OAI-Device-Id": new_uuid(),
                "OAI-Session-Id": new_uuid(),
                "Authorization": f"Bearer {access_token}",
            }
        )
        self.pow_script_sources: list[str] = []
        self.pow_data_build = ""

    def set_image_deadline(self, deadline_monotonic: float, cancel_event: Any = None) -> None:
        deadline = float(deadline_monotonic)
        if self._image_deadline_monotonic is None:
            self._image_deadline_monotonic = deadline
        else:
            self._image_deadline_monotonic = min(self._image_deadline_monotonic, deadline)
        if cancel_event is not None:
            self._image_cancel_event = cancel_event

    def _image_remaining_seconds(self) -> float:
        if self._image_cancel_event is not None and self._image_cancel_event.is_set():
            raise UpstreamError("ChatGPT image generation canceled at the batch deadline")
        if self._image_deadline_monotonic is None:
            return float(max(1, self.timeout_seconds))
        remaining = self._image_deadline_monotonic - time.monotonic()
        if remaining <= 0:
            raise UpstreamError("ChatGPT image generation timed out at the absolute image deadline")
        return remaining

    def _image_request_timeout(self, requested: Any) -> Any:
        if self._image_deadline_monotonic is None:
            return requested
        remaining = self._image_remaining_seconds()
        if isinstance(requested, tuple):
            return tuple(max(0.1, min(float(value), remaining)) for value in requested)
        try:
            requested_seconds = float(requested)
        except (TypeError, ValueError):
            requested_seconds = remaining
        return max(0.1, min(requested_seconds, remaining))

    @staticmethod
    def _transient_exceptions() -> tuple[type[BaseException], ...]:
        return (
            requests.exceptions.ProxyError,
            requests.exceptions.ConnectionError,
            requests.exceptions.ReadTimeout,
            requests.exceptions.Timeout,
        )

    def _headers(self, path: str, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(self.session.headers)
        headers["X-OpenAI-Target-Path"] = path
        headers["X-OpenAI-Target-Route"] = path
        if extra:
            headers.update(extra)
        return headers

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        last_error: Exception | None = None
        requested_timeout = kwargs.get("timeout", self.timeout_seconds)
        for attempt in range(1, NETWORK_RETRY_ATTEMPTS + 1):
            try:
                if self._image_deadline_monotonic is not None:
                    kwargs["timeout"] = self._image_request_timeout(requested_timeout)
                return self.session.request(method, url, **kwargs)
            except self._transient_exceptions() as exc:
                last_error = exc
                if attempt >= NETWORK_RETRY_ATTEMPTS:
                    break
                delay = NETWORK_RETRY_BASE_DELAY_SECS * attempt
                print(
                    f"[chatgpt-pool] transient network error on {method.upper()} {urlparse(url).path}; "
                    f"retrying {attempt}/{NETWORK_RETRY_ATTEMPTS - 1}: {exc}",
                    flush=True,
                )
                if self._image_deadline_monotonic is not None:
                    delay = min(delay, self._image_remaining_seconds())
                time.sleep(delay)
        if last_error:
            raise last_error
        raise RuntimeError("request failed without response")

    def _bootstrap(self) -> None:
        if self._image_deadline_monotonic is not None:
            self._image_remaining_seconds()
        response = self._request("GET", self.base_url + "/", timeout=30)
        ensure_ok(response, "bootstrap")
        self.pow_script_sources, self.pow_data_build = parse_pow_resources(response.text)
        if self._image_deadline_monotonic is not None:
            self._image_remaining_seconds()

    def _requirements(self) -> Requirements:
        if self._image_deadline_monotonic is not None:
            self._image_remaining_seconds()
        path = "/backend-api/sentinel/chat-requirements"
        body = {"p": build_legacy_requirements_token(USER_AGENT, self.pow_script_sources, self.pow_data_build)}
        response = self.session.post(
            self.base_url + path,
            headers=self._headers(path, {"Content-Type": "application/json"}),
            json=body,
            timeout=self._image_request_timeout(30),
        )
        ensure_ok(response, "chat_requirements")
        data = response.json()
        challenges = self._required_challenges(data)
        if challenges:
            raise VerificationRequiredError("chat requirements require browser verification", challenges)
        proof_token = ""
        proof = data.get("proofofwork") or {}
        if proof.get("required"):
            proof_token = build_proof_token(str(proof.get("seed") or ""), str(proof.get("difficulty") or ""), USER_AGENT, self.pow_script_sources, self.pow_data_build)
        token = str(data.get("token") or "")
        if not token:
            raise UpstreamError("missing chat requirements token")
        if self._image_deadline_monotonic is not None:
            self._image_remaining_seconds()
        return Requirements(
            token=token,
            proof_token=proof_token,
            turnstile_token=str(data.get("turnstile_token") or ""),
            so_token=str(data.get("so_token") or ""),
        )

    def _required_challenges(self, data: Any) -> list[str]:
        if not isinstance(data, dict):
            return []
        challenges: list[str] = []
        # Legacy lightweight HTTP mode tolerated `turnstile.required=true` and
        # continued with the returned Sentinel token + PoW/SO tokens. Treating
        # that flag as fatal caused all accounts to be marked `需要验证` before
        # the old chain could try the actual conversation request.
        for key in ("arkose",):
            value = data.get(key)
            if isinstance(value, dict) and value.get("required"):
                challenges.append(key)
            elif data.get(f"{key}_required"):
                challenges.append(key)
        sentinel = data.get("sentinel") if isinstance(data.get("sentinel"), dict) else {}
        for key in ("arkose",):
            value = sentinel.get(key)
            if isinstance(value, dict) and value.get("required") and key not in challenges:
                challenges.append(key)
        return challenges

    def _timezone(self) -> str:
        return "Asia/Shanghai"

    def _timezone_offset_min(self) -> int:
        return -480

    def _client_contextual_info(self, time_since_loaded: int = 300, **overrides: Any) -> dict[str, Any]:
        info: dict[str, Any] = {
            "is_dark_mode": False,
            "time_since_loaded": int(time_since_loaded),
            "page_height": 900,
            "page_width": 1400,
            "pixel_ratio": 2,
            "screen_height": 1440,
            "screen_width": 2560,
            "app_name": "chatgpt.com",
        }
        info.update({key: value for key, value in overrides.items() if value is not None})
        return info

    def fetch_account_profile(self) -> dict[str, str]:
        """Fetch stable account metadata that is not always present in OAuth JWTs."""
        profile: dict[str, str] = {}
        try:
            me = self._get_json("/backend-api/me")
            if isinstance(me, dict):
                profile["email"] = str(me.get("email") or "").strip()
                profile["user_id"] = str(me.get("id") or "").strip()
        except Exception:
            pass
        try:
            check = self._get_json("/backend-api/accounts/check/v4-2023-04-27")
            plan_type = self._extract_account_plan_type(check)
            if plan_type:
                profile["plan_type"] = plan_type
        except Exception:
            pass
        return {key: value for key, value in profile.items() if value}

    def fetch_model_catalog(self) -> dict[str, Any]:
        """Return the account-scoped model picker catalog used by ChatGPT Web."""
        return self._get_json("/backend-api/models?history_and_training_disabled=false")

    def _get_json(self, path: str) -> dict[str, Any]:
        response = self._request("GET", self.base_url + path, headers=self._headers(path, {"Accept": "application/json"}), timeout=30)
        ensure_ok(response, path)
        data = response.json()
        return data if isinstance(data, dict) else {}

    def _extract_account_plan_type(self, data: Any) -> str:
        accounts = data.get("accounts") if isinstance(data, dict) else {}
        if not isinstance(accounts, dict):
            return ""
        candidates = []
        for item in accounts.values():
            if not isinstance(item, dict):
                continue
            account = item.get("account") if isinstance(item.get("account"), dict) else {}
            plan_type = str(account.get("plan_type") or "").strip()
            if not plan_type:
                continue
            candidates.append((bool(account.get("is_deactivated")), plan_type))
        for is_deactivated, plan_type in candidates:
            if not is_deactivated:
                return plan_type
        return candidates[0][1] if candidates else ""

    def check_image_generation_status(self) -> ImageGenerationStatus:
        """Read the same account-level image quota metadata the ChatGPT web UI uses."""
        path = "/backend-api/conversation/init"
        response = self._request(
            "POST",
            self.base_url + path,
            headers=self._headers(path, {"Accept": "application/json", "Content-Type": "application/json"}),
            json={},
            timeout=30,
        )
        ensure_ok(response, path)
        data = response.json()
        return self._extract_image_generation_status(data)

    def _extract_image_generation_status(self, data: Any) -> ImageGenerationStatus:
        blocked_feature = self._find_feature_entry(data, "blocked_features", "name", "image_gen")
        progress = self._find_feature_entry(data, "limits_progress", "feature_name", "image_gen")
        reset_after = str(
            (progress or {}).get("reset_after")
            or (blocked_feature or {}).get("resets_after")
            or ""
        ).strip()
        status = ImageGenerationStatus(
            available=True,
            remaining=_int_or_none((progress or {}).get("remaining")),
            reset_after=reset_after,
            resets_after_text=str((blocked_feature or {}).get("resets_after_text") or "").strip(),
            limit=_float_or_none((blocked_feature or {}).get("limit")),
            title=str((blocked_feature or {}).get("title") or "").strip(),
            description=str((blocked_feature or {}).get("description") or "").strip(),
        )
        if blocked_feature or status.remaining == 0:
            status.available = False
        return status

    def _find_feature_entry(self, data: Any, list_key: str, name_key: str, feature_name: str) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {}
        values = data.get(list_key)
        if not isinstance(values, list):
            return {}
        for item in values:
            if isinstance(item, dict) and str(item.get(name_key) or "") == feature_name:
                return item
        return {}

    def _image_model_slug(self, model: str) -> str:
        value = str(model or "gpt-image-2").strip()
        if value == "gpt-image-2":
            return "gpt-5-5"
        return value if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value) else "gpt-5-5"

    def _image_headers(self, path: str, requirements: Requirements, conduit_token: str = "", accept: str = "*/*") -> dict[str, str]:
        extra = {
            "Content-Type": "application/json",
            "Accept": accept,
            "OpenAI-Sentinel-Chat-Requirements-Token": requirements.token,
        }
        if requirements.proof_token:
            extra["OpenAI-Sentinel-Proof-Token"] = requirements.proof_token
        if requirements.turnstile_token:
            extra["OpenAI-Sentinel-Turnstile-Token"] = requirements.turnstile_token
        if requirements.so_token:
            extra["OpenAI-Sentinel-SO-Token"] = requirements.so_token
        if conduit_token:
            extra["X-Conduit-Token"] = conduit_token
        if accept == "text/event-stream":
            extra["X-Oai-Turn-Trace-Id"] = new_uuid()
        return self._headers(path, extra)

    def _conversation_headers(self, path: str, requirements: Requirements) -> dict[str, str]:
        return self._image_headers(path, requirements, accept="text/event-stream")

    def _chat_message_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and str(item.get("type") or "") in {"text", "input_text", "output_text"}:
                    parts.append(str(item.get("text") or ""))
            return "".join(parts)
        return ""

    def _api_messages_to_conversation_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "user").strip().lower() or "user"
            content = self._chat_message_text(item.get("content") or item.get("text") or "")
            if not content:
                continue
            converted.append(
                {
                    "id": new_uuid(),
                    "author": {"role": role},
                    "content": {"content_type": "text", "parts": [content]},
                }
            )
        return converted

    def _conversation_payload(self, messages: list[dict[str, Any]], model: str) -> dict[str, Any]:
        converted = self._api_messages_to_conversation_messages(messages)
        if not converted:
            raise ValueError("messages are required")
        return {
            "action": "next",
            "messages": converted,
            "model": str(model or CHAT_MODEL).strip() or CHAT_MODEL,
            "parent_message_id": "client-created-root",
            "conversation_mode": {"kind": "primary_assistant"},
            "conversation_origin": None,
            "force_paragen": False,
            "force_paragen_model_slug": "",
            "force_rate_limit": False,
            "force_use_sse": True,
            "history_and_training_disabled": True,
            "reset_rate_limits": False,
            "suggestions": [],
            "supported_encodings": [],
            "system_hints": [],
            "timezone": self._timezone(),
            "timezone_offset_min": self._timezone_offset_min(),
            "variant_purpose": "comparison_implicit",
            "websocket_request_id": new_uuid(),
            "client_contextual_info": self._client_contextual_info(time_since_loaded=30),
        }

    def chat_completion(self, messages: list[dict[str, Any]], model: str = CHAT_MODEL, timeout_secs: float = CHAT_TIMEOUT_SECS) -> dict[str, Any]:
        """Run a plain ChatGPT web chat turn and collect the assistant text."""
        if not self.access_token:
            raise RuntimeError("access_token is required for chat")
        model = str(model or CHAT_MODEL).strip() or CHAT_MODEL
        self._bootstrap()
        requirements = self._requirements()
        path = "/backend-api/conversation"
        response = self.session.post(
            self.base_url + path,
            headers=self._conversation_headers(path, requirements),
            json=self._conversation_payload(messages, model),
            timeout=max(30, min(300, int(timeout_secs or CHAT_TIMEOUT_SECS))),
            stream=True,
        )
        ensure_ok(response, path)
        return self._collect_chat_completion_response(response)

    def chat_completion_with_images(
        self,
        messages: list[dict[str, Any]],
        base64_images: list[str],
        model: str = CHAT_MODEL,
        timeout_secs: float = CHAT_TIMEOUT_SECS,
    ) -> dict[str, Any]:
        """Run a ChatGPT web chat turn with uploaded image attachments."""
        if not self.access_token:
            raise RuntimeError("access_token is required for chat")
        images = [str(item or "").strip() for item in (base64_images or []) if str(item or "").strip()]
        if not images:
            raise ValueError("base64_images is empty")
        prompt = self._chat_messages_to_prompt(messages)
        if not prompt:
            raise ValueError("messages are required")
        model = str(model or CHAT_MODEL).strip() or CHAT_MODEL
        uploaded = [self._upload_editable_base64_image(item, index) for index, item in enumerate(images, start=1)]
        self._bootstrap()
        requirements = self._requirements()
        conduit = self._prepare_image_conversation(
            prompt,
            requirements,
            model,
            [str(item.get("mime_type") or "image/png") for item in uploaded],
        )
        response = self._start_multimodal_chat(prompt, requirements, conduit, model, uploaded, timeout_secs)
        return self._collect_chat_completion_response(response)

    def _chat_messages_to_prompt(self, messages: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "user").strip().lower() or "user"
            content = self._chat_message_text(item.get("content") or item.get("text") or "").strip()
            if not content:
                continue
            label = {
                "system": "System",
                "assistant": "Assistant",
                "user": "User",
            }.get(role, role.title())
            parts.append(f"{label}:\n{content}")
        return "\n\n".join(parts).strip()

    def _start_multimodal_chat(
        self,
        prompt: str,
        requirements: Requirements,
        conduit_token: str,
        model: str,
        uploaded: list[dict[str, Any]],
        timeout_secs: float,
    ) -> requests.Response:
        path = "/backend-api/f/conversation"
        parts: list[Any] = [
            {
                "content_type": "image_asset_pointer",
                "asset_pointer": f"sediment://{item['file_id']}",
                "size_bytes": item["file_size"],
                "width": item["width"],
                "height": item["height"],
            }
            for item in uploaded
        ]
        parts.append(prompt)
        message = {
            "id": new_uuid(),
            "author": {"role": "user"},
            "create_time": time.time(),
            "content": {"content_type": "multimodal_text", "parts": parts},
            "metadata": {
                "attachments": [
                    {
                        "id": item["file_id"],
                        "size": item["file_size"],
                        "name": item["file_name"],
                        "mime_type": item["mime_type"],
                        "width": item["width"],
                        "height": item["height"],
                        "source": "library",
                        "library_file_id": item["library_file_id"],
                        "is_big_paste": False,
                    }
                    for item in uploaded
                ],
                "developer_mode_connector_ids": [],
                "selected_sources": [],
                "selected_github_repos": [],
                "selected_all_github_repos": False,
                "serialization_metadata": {"custom_symbol_offsets": []},
            },
        }
        payload = {
            "action": "next",
            "messages": [message],
            "parent_message_id": "client-created-root",
            "model": self._image_model_slug(model),
            "client_prepare_state": "sent",
            "timezone_offset_min": self._timezone_offset_min(),
            "timezone": self._timezone(),
            "conversation_mode": {"kind": "primary_assistant"},
            "enable_message_followups": True,
            "system_hints": ["picture_v2"],
            "supports_buffering": True,
            "supported_encodings": ["v1"],
            "client_contextual_info": self._client_contextual_info(time_since_loaded=401),
        }
        response = self.session.post(
            self.base_url + path,
            headers=self._image_headers(path, requirements, conduit_token, "text/event-stream"),
            json=payload,
            timeout=(30, max(30, min(300, int(timeout_secs or CHAT_TIMEOUT_SECS)))),
            stream=True,
        )
        ensure_ok(response, path)
        return response

    def _collect_chat_completion_response(self, response: requests.Response) -> dict[str, Any]:
        text = ""
        conversation_id = ""
        assistant_message_id = ""
        try:
            for payload in iter_sse_payloads(response):
                if payload == "[DONE]":
                    break
                conversation_id = conversation_id or self._find_chat_value(payload, "conversation_id")
                event = self._parse_chat_event(payload)
                if not isinstance(event, dict):
                    continue
                conversation_id = conversation_id or self._find_chat_value(event, "conversation_id")
                assistant_message_id = assistant_message_id or self._find_assistant_message_id(event)
                next_text = self._chat_event_text(event, text)
                if next_text:
                    text = self._sanitize_chat_text(next_text)
        finally:
            response.close()
        if not text.strip():
            raise RuntimeError("chat completion returned empty text")
        return {
            "conversation_id": conversation_id,
            "assistant_message_id": assistant_message_id,
            "content": text.strip(),
        }

    def _parse_chat_event(self, payload: str) -> Any:
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None

    def _find_chat_value(self, payload: Any, key: str) -> str:
        if isinstance(payload, str):
            if key == "conversation_id":
                match = SEARCH_CONVERSATION_ID_RE.search(payload)
                if match:
                    return match.group(1)
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return ""
        if isinstance(payload, dict):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
            return next((found for item in payload.values() if (found := self._find_chat_value(item, key))), "")
        if isinstance(payload, list):
            return next((found for item in payload if (found := self._find_chat_value(item, key))), "")
        return ""

    def _find_assistant_message_id(self, event: dict[str, Any]) -> str:
        for candidate in (event, event.get("v")):
            if not isinstance(candidate, dict):
                continue
            message = candidate.get("message")
            if isinstance(message, dict) and ((message.get("author") or {}).get("role") or "") == "assistant":
                return str(message.get("id") or "")
        return ""

    def _assistant_message_text(self, message: Any) -> str:
        content = message.get("content") if isinstance(message, dict) else {}
        parts = []
        if isinstance(content, dict):
            if isinstance(content.get("text"), str):
                parts.append(content["text"])
            for part in content.get("parts") or []:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict):
                    parts.extend(str(part.get(key) or "") for key in ("text", "summary", "content") if part.get(key))
        elif isinstance(content, str):
            parts.append(content)
        return "\n".join(part.strip() for part in parts if str(part).strip()).strip()

    def _chat_event_text(self, event: dict[str, Any], current_text: str) -> str:
        for candidate in (event, event.get("v")):
            if not isinstance(candidate, dict):
                continue
            message = candidate.get("message")
            if not isinstance(message, dict):
                continue
            if ((message.get("author") or {}).get("role") or "") != "assistant":
                continue
            text = self._assistant_message_text(message)
            if text:
                return text
        return self._apply_chat_text_patch(event, current_text)

    def _apply_chat_text_patch(self, event: dict[str, Any], current_text: str) -> str:
        if event.get("p") == "/message/content/parts/0":
            return self._apply_chat_patch_op(event, current_text)
        operations = event.get("v")
        if isinstance(operations, str) and current_text and not event.get("p") and not event.get("o"):
            return current_text + operations
        if event.get("o") == "patch" and isinstance(operations, list):
            text = current_text
            for item in operations:
                if isinstance(item, dict):
                    text = self._apply_chat_text_patch(item, text)
            return text
        if isinstance(operations, list):
            text = current_text
            for item in operations:
                if isinstance(item, dict):
                    text = self._apply_chat_text_patch(item, text)
            return text
        return current_text

    def _apply_chat_patch_op(self, operation: dict[str, Any], current_text: str) -> str:
        op = operation.get("o")
        value = str(operation.get("v") or "")
        if op == "append":
            return current_text + value
        if op == "replace":
            return value
        return current_text

    def _sanitize_chat_text(self, text: str) -> str:
        text = str(text or "")

        def replace_annotation(match: re.Match[str]) -> str:
            parts = [part.strip() for part in match.group(1).split("\ue202")]
            if parts and parts[0].lower() == "url":
                label = parts[1] if len(parts) > 1 else ""
                url = parts[2] if len(parts) > 2 else ""
                return f"{label} ({url})" if label and url.startswith(("http://", "https://")) else (label or url)
            return next((part for part in parts[1:] if part and not part.lower().startswith(("turn", "source"))), "")

        text = re.sub(r"\ue200([^\ue201]*)\ue201", replace_annotation, text)
        text = re.sub(r"\ue200[^\ue201]*$", "", text)
        return re.sub(r"\s+([.,;:!?])", r"\1", text)

    def _prepare_image_conversation(
        self,
        prompt: str,
        requirements: Requirements,
        model: str,
        attachment_mime_types: list[str] | None = None,
    ) -> str:
        if self._image_deadline_monotonic is not None:
            self._image_remaining_seconds()
        path = "/backend-api/f/conversation/prepare"
        payload = {
            "action": "next",
            "fork_from_shared_post": False,
            "parent_message_id": new_uuid(),
            "model": self._image_model_slug(model),
            "client_prepare_state": "success",
            "timezone_offset_min": self._timezone_offset_min(),
            "timezone": self._timezone(),
            "conversation_mode": {"kind": "primary_assistant"},
            "system_hints": ["picture_v2"],
            "partial_query": {
                "id": new_uuid(),
                "author": {"role": "user"},
                "content": {"content_type": "text", "parts": [prompt]},
            },
            "supports_buffering": True,
            "supported_encodings": ["v1"],
            "client_contextual_info": self._client_contextual_info(time_since_loaded=180),
        }
        if attachment_mime_types:
            payload["attachment_mime_types"] = attachment_mime_types
        response = self.session.post(
            self.base_url + path,
            headers=self._image_headers(path, requirements),
            json=payload,
            timeout=self._image_request_timeout(60),
        )
        ensure_ok(response, path)
        if self._image_deadline_monotonic is not None:
            self._image_remaining_seconds()
        return str(response.json().get("conduit_token") or "")

    def _start_image_generation(
        self,
        prompt: str,
        requirements: Requirements,
        conduit_token: str,
        model: str,
        uploaded: list[dict[str, Any]] | None = None,
    ) -> requests.Response:
        if self._image_deadline_monotonic is not None:
            self._image_remaining_seconds()
        path = "/backend-api/f/conversation"
        metadata = {
            "developer_mode_connector_ids": [],
            "selected_github_repos": [],
            "selected_all_github_repos": False,
            "system_hints": ["picture_v2"],
            "serialization_metadata": {"custom_symbol_offsets": []},
        }
        message: dict[str, Any] = {
            "id": new_uuid(),
            "author": {"role": "user"},
            "create_time": time.time(),
            "content": {"content_type": "text", "parts": [prompt]},
            "metadata": metadata,
        }
        if uploaded:
            parts: list[Any] = [
                {
                    "content_type": "image_asset_pointer",
                    "asset_pointer": f"sediment://{item['file_id']}",
                    "size_bytes": item["file_size"],
                    "width": item["width"],
                    "height": item["height"],
                }
                for item in uploaded
            ]
            parts.append(prompt)
            message["content"] = {"content_type": "multimodal_text", "parts": parts}
            message["metadata"] = {
                **metadata,
                "attachments": [
                    {
                        "id": item["file_id"],
                        "size": item["file_size"],
                        "name": item["file_name"],
                        "mime_type": item["mime_type"],
                        "width": item["width"],
                        "height": item["height"],
                        "source": "library",
                        "library_file_id": item["library_file_id"],
                        "is_big_paste": False,
                    }
                    for item in uploaded
                ],
                "selected_sources": [],
            }
        payload = {
            "action": "next",
            "messages": [message],
            "parent_message_id": new_uuid(),
            "model": self._image_model_slug(model),
            "client_prepare_state": "sent",
            "timezone_offset_min": self._timezone_offset_min(),
            "timezone": self._timezone(),
            "conversation_mode": {"kind": "primary_assistant"},
            "enable_message_followups": True,
            "system_hints": ["picture_v2"],
            "supports_buffering": True,
            "supported_encodings": ["v1"],
            "client_contextual_info": self._client_contextual_info(time_since_loaded=1200),
            "paragen_cot_summary_display_override": "allow",
            "force_parallel_switch": "auto",
        }
        response = self.session.post(
            self.base_url + path,
            headers=self._image_headers(path, requirements, conduit_token, "text/event-stream"),
            json=payload,
            timeout=self._image_stream_timeout(),
            stream=True,
        )
        ensure_ok(response, path)
        if self._image_deadline_monotonic is not None:
            self._image_remaining_seconds()
        return response

    def _image_stream_timeout(self) -> tuple[float, float]:
        timeout = (
            IMAGE_STREAM_CONNECT_TIMEOUT_SECS,
            max(30.0, min(float(self.timeout_seconds), IMAGE_STREAM_READ_TIMEOUT_SECS)),
        )
        return self._image_request_timeout(timeout)

    def _iter_image_sse_payloads(self, response: requests.Response) -> Iterable[str]:
        if self._image_deadline_monotonic is None:
            yield from iter_sse_payloads(response)
            return

        messages: queue.Queue[tuple[str, Any]] = queue.Queue()

        def read_stream() -> None:
            try:
                for payload in iter_sse_payloads(response):
                    messages.put(("payload", payload))
            except BaseException as exc:
                messages.put(("error", exc))
            finally:
                messages.put(("done", None))

        threading.Thread(
            target=read_stream,
            name="chatgpt-pool-image-sse-reader",
            daemon=True,
        ).start()
        while True:
            remaining = self._image_remaining_seconds()
            try:
                kind, value = messages.get(timeout=min(1.0, remaining))
            except queue.Empty:
                continue
            if kind == "payload":
                yield str(value or "")
                continue
            if kind == "error":
                raise value
            return

    def _get_conversation(self, conversation_id: str) -> dict[str, Any]:
        path = f"/backend-api/conversation/{conversation_id}"
        response = self._request("GET", self.base_url + path, headers=self._headers(path, {"Accept": "application/json"}), timeout=60)
        ensure_ok(response, path)
        return response.json()

    def _summarize_image_poll_state(self, data: Any) -> str:
        if not isinstance(data, dict):
            return type(data).__name__
        mapping = data.get("mapping") if isinstance(data.get("mapping"), dict) else {}
        messages = []
        assistant_messages = 0
        content_types: set[str] = set()
        for node in mapping.values():
            message = (node or {}).get("message") if isinstance(node, dict) else {}
            if not isinstance(message, dict):
                continue
            messages.append(message)
            author = message.get("author") if isinstance(message.get("author"), dict) else {}
            if str(author.get("role") or "") == "assistant":
                assistant_messages += 1
            content = message.get("content")
            if isinstance(content, dict):
                content_type = str(content.get("content_type") or "").strip()
                if content_type:
                    content_types.add(content_type[:80])
        statuses: set[str] = set()
        for obj in self._walk_dicts(data):
            status = str(obj.get("status") or "").strip()
            if status:
                statuses.add(status[:80])
            if len(statuses) >= 5:
                break
        content_summary = ",".join(sorted(content_types)) if content_types else "-"
        status_summary = ",".join(sorted(statuses)) if statuses else "-"
        return (
            f"nodes={len(mapping)}, messages={len(messages)}, "
            f"assistant_messages={assistant_messages}, content_types={content_summary}, statuses={status_summary}"
        )

    def _image_poll_status_values(self, data: Any) -> set[str]:
        statuses: set[str] = set()
        for obj in self._walk_dicts(data):
            status = str(obj.get("status") or "").strip().lower()
            if status:
                statuses.add(status)
        return statuses

    def _image_poll_has_assistant_message(self, data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        mapping = data.get("mapping") if isinstance(data.get("mapping"), dict) else {}
        for node in mapping.values():
            message = (node or {}).get("message") if isinstance(node, dict) else {}
            if not isinstance(message, dict):
                continue
            author = message.get("author") if isinstance(message.get("author"), dict) else {}
            if str(author.get("role") or "") == "assistant":
                return True
        return False

    def _image_poll_system_error_details(self, data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        details: list[str] = []
        mapping = data.get("mapping") if isinstance(data.get("mapping"), dict) else {}
        for node in mapping.values():
            message = (node or {}).get("message") if isinstance(node, dict) else {}
            if not isinstance(message, dict):
                continue
            content = message.get("content") if isinstance(message.get("content"), dict) else {}
            if str(content.get("content_type") or "") != "system_error":
                continue
            name = str(content.get("name") or "").strip()
            text = str(content.get("text") or "").strip()
            detail = ": ".join(part for part in (name, text) if part)
            if detail and detail not in details:
                details.append(detail[:240])
        if not details:
            return ""
        return " | ".join(details)[:600]

    def _image_poll_policy_refusal_details(self, data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        mapping = data.get("mapping") if isinstance(data.get("mapping"), dict) else {}
        for node in mapping.values():
            message = (node or {}).get("message") if isinstance(node, dict) else {}
            if not isinstance(message, dict):
                continue
            author = message.get("author") if isinstance(message.get("author"), dict) else {}
            if str(author.get("role") or "") != "assistant":
                continue
            status = str(message.get("status") or "").strip().lower()
            if status and status not in IMAGE_TERMINAL_STATUS_MARKERS:
                continue
            content = message.get("content") if isinstance(message.get("content"), dict) else {}
            text = self._payload_text(content).strip()
            lower_text = text.lower()
            if text and any(marker in lower_text for marker in IMAGE_POLICY_REFUSAL_MARKERS):
                return text[:600]
        return ""

    def _image_poll_finished_without_assets(self, data: Any) -> bool:
        """Return true when ChatGPT finished a turn but produced no image asset."""
        if not self._image_poll_has_assistant_message(data):
            return False
        statuses = self._image_poll_status_values(data)
        if not statuses:
            return False
        if statuses & IMAGE_ACTIVE_STATUS_MARKERS:
            return False
        return bool(statuses & IMAGE_TERMINAL_STATUS_MARKERS)

    def _extract_image_limit_message(self, payload: Any) -> str:
        text = self._payload_text(payload)
        lower_text = text.lower()
        if not any(marker in lower_text or marker in text for marker in IMAGE_LIMIT_MARKERS):
            return ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            return " ".join(lines)[:500]
        return text[:500]

    def _raise_if_image_limit_message(self, payload: Any) -> None:
        message = self._extract_image_limit_message(payload)
        if message:
            raise ImageGenerationLimitError(message=message)

    def _payload_text(self, payload: Any) -> str:
        parts: list[str] = []
        self._collect_payload_text(payload, parts)
        return "\n".join(part for part in parts if part).strip()

    def _collect_payload_text(self, payload: Any, parts: list[str]) -> None:
        if isinstance(payload, str):
            value = payload.strip()
            if value:
                parts.append(value)
            return
        if isinstance(payload, dict):
            for key in ("text", "summary", "content", "title", "description", "resets_after_text"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
            content = payload.get("content")
            if isinstance(content, dict):
                self._collect_payload_text(content, parts)
            for part in payload.get("parts") or []:
                self._collect_payload_text(part, parts)
            for key, value in payload.items():
                if key in {"text", "summary", "content", "title", "description", "resets_after_text", "parts"}:
                    continue
                if isinstance(value, (dict, list)):
                    self._collect_payload_text(value, parts)
            return
        if isinstance(payload, list):
            for item in payload:
                self._collect_payload_text(item, parts)

    def _poll_image_results(self, conversation_id: str, deadline: float | None = None) -> tuple[list[str], list[str]]:
        local_timeout = (
            self._image_remaining_seconds()
            if self._image_deadline_monotonic is not None
            else max(60, self.timeout_seconds)
        )
        local_deadline = time.time() + local_timeout
        deadline_at = min(float(deadline), local_deadline) if deadline is not None else local_deadline
        file_ids: list[str] = []
        sediment_ids: list[str] = []
        poll_count = 0
        last_summary = "not-polled"
        last_log_at = 0.0
        while time.time() < deadline_at:
            if self._image_deadline_monotonic is not None:
                self._image_remaining_seconds()
            poll_count += 1
            data = self._get_conversation(conversation_id)
            self._raise_if_image_limit_message(data)
            last_summary = self._summarize_image_poll_state(data)
            text = json.dumps(data, ensure_ascii=False)
            _, files, sediments = extract_ids(text)
            add_unique(file_ids, [item for item in files if item != "file_upload"])
            add_unique(sediment_ids, sediments)
            if file_ids or sediment_ids:
                print(
                    "[chatgpt-pool] image result ready: "
                    f"conversation_id={conversation_id}; polls={poll_count}; "
                    f"files={len(file_ids)}; attachments={len(sediment_ids)}",
                    flush=True,
                )
                return file_ids, sediment_ids
            policy_refusal = self._image_poll_policy_refusal_details(data)
            if policy_refusal:
                raise UpstreamError(
                    "Image request was blocked by upstream moderation: "
                    f"conversation_id={conversation_id}; detail={policy_refusal}"
                )
            if self._image_poll_finished_without_assets(data):
                system_error = self._image_poll_system_error_details(data)
                suffix = f"; system_error={system_error}" if system_error else ""
                raise UpstreamError(
                    "ChatGPT conversation finished without image output: "
                    f"conversation_id={conversation_id}; polls={poll_count}; last_state={last_summary}{suffix}"
                )
            now = time.time()
            if now - last_log_at >= 60:
                print(
                    "[chatgpt-pool] waiting for image result: "
                    f"conversation_id={conversation_id}; polls={poll_count}; last_state={last_summary}",
                    flush=True,
                )
                last_log_at = now
            if self._image_deadline_monotonic is None:
                time.sleep(5)
            else:
                sleep_seconds = min(
                    5.0,
                    max(0.0, deadline_at - time.time()),
                    self._image_remaining_seconds(),
                )
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
        raise UpstreamError(
            "ChatGPT image generation timed out while polling results: "
            f"conversation_id={conversation_id}; polls={poll_count}; last_state={last_summary}"
        )

    def _download_url_for_file(self, file_id: str) -> str:
        path = f"/backend-api/files/{file_id}/download"
        response = self._request("GET", self.base_url + path, headers=self._headers(path, {"Accept": "application/json"}), timeout=60)
        ensure_ok(response, path)
        data = response.json()
        return str(data.get("download_url") or data.get("url") or "")

    def _download_url_for_attachment(self, conversation_id: str, attachment_id: str) -> str:
        path = f"/backend-api/conversation/{conversation_id}/attachment/{attachment_id}/download"
        response = self._request("GET", self.base_url + path, headers=self._headers(path, {"Accept": "application/json"}), timeout=60)
        ensure_ok(response, path)
        data = response.json()
        return str(data.get("download_url") or data.get("url") or "")

    def _resolve_image_urls(self, conversation_id: str, file_ids: list[str], sediment_ids: list[str]) -> list[str]:
        urls: list[str] = []
        for file_id in file_ids:
            if self._image_deadline_monotonic is not None:
                self._image_remaining_seconds()
            try:
                url = self._download_url_for_file(file_id)
            except Exception:
                if self._image_deadline_monotonic is not None:
                    self._image_remaining_seconds()
                continue
            if url:
                urls.append(url)
        if urls:
            return urls
        for sediment_id in sediment_ids:
            if self._image_deadline_monotonic is not None:
                self._image_remaining_seconds()
            try:
                url = self._download_url_for_attachment(conversation_id, sediment_id)
            except Exception:
                if self._image_deadline_monotonic is not None:
                    self._image_remaining_seconds()
                continue
            if url:
                urls.append(url)
        if urls:
            return urls
        for sediment_id in sediment_ids:
            if self._image_deadline_monotonic is not None:
                self._image_remaining_seconds()
            try:
                url = self._download_url_for_file(sediment_id)
            except Exception:
                if self._image_deadline_monotonic is not None:
                    self._image_remaining_seconds()
                continue
            if url:
                urls.append(url)
        return urls

    def _get_recent_image_generation_items(self, limit: int = IMAGE_LIBRARY_RECENT_LIMIT, cursor: str = "") -> dict[str, Any]:
        """Read the same Images Library feed used by https://chatgpt.com/images."""
        path = "/backend-api/my/recent/image_gen"
        params: dict[str, Any] = {"limit": max(1, min(100, int(limit or IMAGE_LIBRARY_RECENT_LIMIT)))}
        if cursor:
            params["cursor"] = cursor
        response = self._request(
            "GET",
            self.base_url + path,
            headers=self._headers(path, {"Accept": "application/json"}),
            params=params,
            timeout=60,
        )
        ensure_ok(response, path)
        data = response.json()
        return data if isinstance(data, dict) else {}

    def _image_library_url_candidates(self, item: Any) -> list[str]:
        if not isinstance(item, dict):
            return []
        candidates: list[str] = []

        def add_url(value: Any) -> None:
            if isinstance(value, dict):
                for key in ("path", "url", "download_url"):
                    add_url(value.get(key))
                return
            url = str(value or "").strip()
            if not url:
                return
            if url.startswith("/"):
                url = urljoin(self.base_url, url)
            if url not in candidates:
                candidates.append(url)

        # Prefer the original Estuary asset URL. Thumbnail/derived encodings are
        # only used as a last-resort fallback if source URLs are absent.
        add_url(item.get("url"))
        encodings = item.get("encodings") if isinstance(item.get("encodings"), dict) else {}
        for key in ("source", "md", "ld", "source_wm", "endcard_wm", "unfurl", "thumbnail"):
            add_url(encodings.get(key))
        return candidates

    def _recent_image_library_urls_for_conversation(
        self,
        conversation_id: str,
        started_at: float | None = None,
        limit: int = IMAGE_LIBRARY_RECENT_LIMIT,
        max_pages: int = IMAGE_LIBRARY_RECENT_MAX_PAGES,
    ) -> list[str]:
        """Find Estuary URLs that Images Library knows for a conversation.

        ChatGPT can persist successful Web image assets into the Images Library
        even when the conversation mapping remains text/system_error only.  The
        library feed is keyed by conversation_id, so it is the safest fallback
        after a terminal conversation poll returns no file-service/sediment refs.
        """
        target = str(conversation_id or "").strip()
        if not target:
            return []
        min_created_at = None
        if started_at is not None:
            try:
                min_created_at = float(started_at) - IMAGE_LIBRARY_LOOKBACK_GRACE_SECS
            except (TypeError, ValueError):
                min_created_at = None

        matched: list[tuple[float, list[str]]] = []
        cursor = ""
        for _page in range(max(1, int(max_pages or 1))):
            if self._image_deadline_monotonic is not None:
                self._image_remaining_seconds()
            data = self._get_recent_image_generation_items(limit=limit, cursor=cursor)
            items = data.get("items") if isinstance(data.get("items"), list) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                if str(item.get("conversation_id") or "").strip() != target:
                    continue
                if item.get("output_blocked") is True:
                    continue
                urls = self._image_library_url_candidates(item)
                if not urls:
                    continue
                created_at = _float_or_none(item.get("created_at")) or 0.0
                matched.append((created_at, urls))
            cursor = str(data.get("cursor") or "").strip()
            if not cursor:
                break

        if not matched:
            return []

        recent = [entry for entry in matched if min_created_at is None or entry[0] >= min_created_at]
        selected = recent or matched
        selected.sort(key=lambda entry: entry[0], reverse=True)
        urls: list[str] = []
        for _created_at, candidates in selected:
            for url in candidates:
                if url and url not in urls:
                    urls.append(url)
        if urls:
            print(
                "[chatgpt-pool] image library fallback found Estuary asset: "
                f"conversation_id={conversation_id}; urls={len(urls)}",
                flush=True,
            )
        return urls

    def _download_image(self, url: str) -> bytes:
        if self._image_deadline_monotonic is not None:
            self._image_remaining_seconds()
        response = self._request("GET", url, timeout=120)
        ensure_ok(response, "image_download")
        if self._image_deadline_monotonic is not None:
            self._image_remaining_seconds()
        return response.content

    def search(
        self,
        prompt: str,
        model: str = SEARCH_MODEL,
        timeout_secs: float = SEARCH_TIMEOUT_SECS,
        poll_interval_secs: float = SEARCH_POLL_INTERVAL_SECS,
    ) -> dict[str, Any]:
        """Run a ChatGPT web search / research turn and extract answer + sources."""
        query = str(prompt or "").strip()
        if not query:
            raise ValueError("prompt is required")
        if not self.access_token:
            raise RuntimeError("access_token is required for search")
        conduit_token = self._prepare_search_conversation(query, model)
        self._bootstrap()
        conversation_id = self._run_search_conversation(query, conduit_token, model)
        return self._wait_search_result(conversation_id, timeout_secs, poll_interval_secs)

    def _prepare_search_conversation(self, prompt: str, model: str) -> str:
        path = "/backend-api/f/conversation/prepare"
        response = self.session.post(
            self.base_url + path,
            headers=self._headers(path, {"Accept": "*/*", "Content-Type": "application/json", "X-Conduit-Token": "no-token"}),
            json={
                "action": "next",
                "fork_from_shared_post": False,
                "parent_message_id": "client-created-root",
                "model": model,
                "client_prepare_state": "success",
                "timezone_offset_min": self._timezone_offset_min(),
                "timezone": self._timezone(),
                "conversation_mode": {"kind": "primary_assistant"},
                "system_hints": ["search"],
                "partial_query": {
                    "id": new_uuid(),
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": [prompt]},
                },
                "supports_buffering": True,
                "supported_encodings": ["v1"],
                "client_contextual_info": self._client_contextual_info(time_since_loaded=120),
            },
            timeout=60,
        )
        ensure_ok(response, path)
        token = str(response.json().get("conduit_token") or "")
        if not token:
            raise RuntimeError("missing conduit_token")
        return token

    def _run_search_conversation(self, prompt: str, conduit_token: str, model: str) -> str:
        requirements = self._requirements()
        path = "/backend-api/f/conversation"
        response = self.session.post(
            self.base_url + path,
            headers=self._image_headers(path, requirements, conduit_token, "text/event-stream"),
            json={
                "action": "next",
                "messages": [
                    {
                        "id": new_uuid(),
                        "author": {"role": "user"},
                        "create_time": time.time(),
                        "content": {"content_type": "text", "parts": [prompt]},
                        "metadata": {
                            "developer_mode_connector_ids": [],
                            "selected_github_repos": [],
                            "selected_all_github_repos": False,
                            "system_hints": ["search"],
                            "serialization_metadata": {"custom_symbol_offsets": []},
                        },
                    }
                ],
                "parent_message_id": "client-created-root",
                "model": model,
                "client_prepare_state": "success",
                "timezone_offset_min": self._timezone_offset_min(),
                "timezone": self._timezone(),
                "conversation_mode": {"kind": "primary_assistant"},
                "enable_message_followups": True,
                "system_hints": [],
                "supports_buffering": True,
                "supported_encodings": ["v1"],
                "force_use_search": True,
                "client_reported_search_source": "conversation_composer_web_icon",
                "client_contextual_info": self._client_contextual_info(time_since_loaded=36),
                "paragen_cot_summary_display_override": "allow",
                "force_parallel_switch": "auto",
            },
            timeout=min(self.timeout_seconds, 300),
            stream=True,
        )
        ensure_ok(response, path)
        conversation_id = ""
        try:
            for payload in iter_sse_payloads(response):
                conversation_id = conversation_id or self._find_search_value(payload, "conversation_id")
                if payload == "[DONE]":
                    break
        finally:
            response.close()
        if not conversation_id:
            raise RuntimeError("conversation_id not found in stream")
        return conversation_id

    def _wait_search_result(self, conversation_id: str, timeout_secs: float, poll_interval_secs: float) -> dict[str, Any]:
        deadline = time.time() + max(30.0, float(timeout_secs or SEARCH_TIMEOUT_SECS))
        interval = max(1.0, float(poll_interval_secs or SEARCH_POLL_INTERVAL_SECS))
        last_result: dict[str, Any] | None = None
        last_answer = ""
        stable_hits = 0
        while time.time() < deadline:
            try:
                last_result = self._extract_search_result(conversation_id, self._get_search_conversation(conversation_id))
            except UpstreamError as exc:
                print(f"[chatgpt-pool] search poll failed: {exc}", flush=True)
            if last_result and last_result.get("answer"):
                if last_result.get("status") in SEARCH_DONE_STATUS:
                    return last_result
                answer = str(last_result.get("answer") or "")
                stable_hits = stable_hits + 1 if answer == last_answer else 0
                last_answer = answer
                if stable_hits >= 2:
                    return last_result
            time.sleep(interval)
        if last_result:
            return last_result
        raise RuntimeError(f"timed out waiting for search result: {conversation_id}")

    def _get_search_conversation(self, conversation_id: str) -> dict[str, Any]:
        path = f"/backend-api/conversation/{conversation_id}"
        headers = self._headers(path, {"Accept": "*/*"})
        headers["Referer"] = f"{self.base_url}/c/{conversation_id}"
        headers["X-OpenAI-Target-Route"] = "/backend-api/conversation/{conversation_id}"
        response = self._request("GET", self.base_url + path, headers=headers, timeout=60)
        ensure_ok(response, path)
        return response.json()

    def _extract_search_result(self, conversation_id: str, conversation: dict[str, Any]) -> dict[str, Any]:
        messages = []
        for node in (conversation.get("mapping") or {}).values():
            message = (node or {}).get("message") or {}
            if ((message.get("author") or {}).get("role") or "") == "assistant":
                messages.append(message)
        message = max(messages, key=lambda item: float(item.get("create_time") or 0.0)) if messages else {}
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        finish_details = metadata.get("finish_details") if isinstance(metadata.get("finish_details"), dict) else {}
        answer = self._search_message_text(message)
        sources = self._extract_search_sources(message)
        for url in SEARCH_URL_RE.findall(answer):
            url = self._clean_search_url(url)
            if url and all(item["url"] != url for item in sources):
                sources.append({"title": "", "url": url, "snippet": "", "source_type": ""})
        return {
            "conversation_id": conversation_id,
            "status": str(finish_details.get("type") or metadata.get("status") or self._find_search_value(message, "status") or "").strip(),
            "answer": answer,
            "sources": sources,
            "assistant_message_id": str(message.get("id") or ""),
            "create_time": float(message.get("create_time") or 0.0),
        }

    def _extract_search_sources(self, payload: Any) -> list[dict[str, str]]:
        sources: list[dict[str, str]] = []
        for obj in self._walk_search_dicts(payload):
            metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
            url = self._clean_search_url(obj.get("url") or obj.get("link") or obj.get("source_url") or metadata.get("url"))
            if url and all(item["url"] != url for item in sources):
                sources.append(
                    {
                        "title": str(obj.get("title") or obj.get("name") or obj.get("source") or "").strip(),
                        "url": url,
                        "snippet": str(obj.get("snippet") or obj.get("text") or obj.get("description") or "").strip(),
                        "source_type": str(obj.get("type") or obj.get("source_type") or "").strip(),
                    }
                )
        return sources

    def _search_message_text(self, message: Any) -> str:
        content = message.get("content") if isinstance(message, dict) else {}
        parts = []
        if isinstance(content, dict):
            if isinstance(content.get("text"), str):
                parts.append(content["text"])
            for part in content.get("parts") or []:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict):
                    parts.extend(str(part.get(key) or "") for key in ("text", "summary", "content") if part.get(key))
        elif isinstance(content, str):
            parts.append(content)
        return "\n".join(part.strip() for part in parts if str(part).strip()).strip()

    def _find_search_value(self, payload: Any, key: str) -> str:
        if isinstance(payload, str):
            match = SEARCH_CONVERSATION_ID_RE.search(payload) if key == "conversation_id" else None
            if match:
                return match.group(1)
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return ""
        if isinstance(payload, dict):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
            return next((found for item in payload.values() if (found := self._find_search_value(item, key))), "")
        if isinstance(payload, list):
            return next((found for item in payload if (found := self._find_search_value(item, key))), "")
        return ""

    def _walk_search_dicts(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            return [payload, *(item for value in payload.values() for item in self._walk_search_dicts(value))]
        if isinstance(payload, list):
            return [item for value in payload for item in self._walk_search_dicts(value)]
        return []

    def _clean_search_url(self, value: Any) -> str:
        return str(value or "").strip().rstrip(".,;，。；")

    @staticmethod
    def _editable_prompt(fixed_prompt: str, user_prompt_text: str) -> str:
        extra = str(user_prompt_text or "").strip()
        return fixed_prompt if not extra else fixed_prompt + "\n\n以下是用户补充需求，请直接结合执行：\n" + extra

    def export_ppt_zip(
        self,
        base64_images: list[str] | None,
        prompt: str,
        output_dir: str | Path,
        timeout_secs: float = EDITABLE_FILE_TIMEOUT_SECS,
        poll_interval_secs: float = EDITABLE_FILE_POLL_INTERVAL_SECS,
    ) -> EditableFileExportResult:
        return self._export_editable_file_zip(
            base64_images or [],
            self._editable_prompt(EDITABLE_FILE_PPT_PROMPT, prompt),
            output_dir,
            primary_label="ppt",
            primary_suffixes=(".ppt", ".pptx"),
            primary_mime_types=EDITABLE_PPT_MIME_TYPES,
            primary_mime_keywords=("presentationml.presentation", "ms-powerpoint"),
            primary_default_extension=".pptx",
            export_file_re=EDITABLE_PPT_EXPORT_FILE_RE,
            timeout_secs=timeout_secs,
            poll_interval_secs=poll_interval_secs,
        )

    def export_psd_zip(
        self,
        base64_images: list[str],
        prompt: str,
        output_dir: str | Path,
        timeout_secs: float = EDITABLE_FILE_TIMEOUT_SECS,
        poll_interval_secs: float = EDITABLE_FILE_POLL_INTERVAL_SECS,
    ) -> EditableFileExportResult:
        if not base64_images:
            raise ValueError("base64_images is empty")
        self.session.headers["OAI-Client-Version"] = EDITABLE_FILE_CLIENT_VERSION
        self.session.headers["OAI-Client-Build-Number"] = EDITABLE_FILE_CLIENT_BUILD_NUMBER
        output_path = Path(output_dir).expanduser().resolve()
        output_path.mkdir(parents=True, exist_ok=True)
        source_data, _, _, _, _ = self._decode_editable_base64_image(base64_images[0], 1)
        uploaded = [self._upload_editable_base64_image(base64_images[0], 1)]
        self._ensure_adobe_connector()
        adobe_prompt = EDITABLE_FILE_PSD_PROMPT
        conduit_token = self._prepare_editable_conversation(adobe_prompt, [uploaded[0]["mime_type"]])
        conversation_id = self._run_editable_conversation(
            adobe_prompt,
            uploaded,
            conduit_token,
            connector_ids=[ADOBE_CONNECTOR_ID],
        )
        masks = self._wait_adobe_mask_outputs(
            conversation_id,
            timeout_secs=timeout_secs,
            poll_interval_secs=poll_interval_secs,
        )
        masks = self._collect_additional_adobe_masks(
            conversation_id,
            masks,
            max_additional=ADOBE_ADDITIONAL_MASK_COUNT,
            poll_interval_secs=poll_interval_secs,
        )
        return self._build_adobe_psd_bundle(
            source_data,
            masks,
            output_path,
            conversation_id=conversation_id,
        )

    def _get_adobe_connector_link(self) -> dict[str, Any]:
        path = f"/backend-api/aip/connectors/{ADOBE_CONNECTOR_ID}/link"
        response = self._request(
            "GET",
            self.base_url + path,
            headers=self._headers(path, {"Accept": "*/*"}),
            timeout=30,
        )
        if response.status_code == 404:
            return {}
        ensure_ok(response, path)
        payload = response.json() if response.text else {}
        link = payload.get("link") if isinstance(payload, dict) else {}
        return link if isinstance(link, dict) else {}

    @staticmethod
    def _adobe_link_is_active(link: dict[str, Any]) -> bool:
        return (
            str(link.get("auth_status") or "").upper() == "ACTIVE"
            and str(link.get("connector_status") or "").upper() == "ENABLED"
        )

    def _ensure_adobe_connector(self) -> dict[str, Any]:
        link = self._get_adobe_connector_link()
        if self._adobe_link_is_active(link):
            return link
        last_error: Exception | None = None
        for attempt in range(1, ADOBE_OAUTH_FLOW_ATTEMPTS + 1):
            try:
                path = "/backend-api/aip/connectors/links/oauth"
                response = self._request(
                    "POST",
                    self.base_url + path,
                    headers=self._headers(path, {"Accept": "*/*", "Content-Type": "application/json"}),
                    json={
                        "connector_id": ADOBE_CONNECTOR_ID,
                        "name": ADOBE_CONNECTOR_NAME,
                        "action_names": ADOBE_CONNECTOR_ACTIONS,
                        "requested_scopes": ADOBE_CONNECTOR_SCOPES,
                        "callback_url": ADOBE_CONNECTOR_CALLBACK_URL,
                    },
                    timeout=30,
                )
                ensure_ok(response, path)
                payload = response.json() if response.text else {}
                redirect_url = str(payload.get("redirect_url") or "")
                if not redirect_url:
                    raise RuntimeError("Adobe connector OAuth did not return redirect_url")
                callback_url = self._complete_adobe_guest_oauth(redirect_url)
                callback_path = "/backend-api/aip/connectors/links/oauth/callback"
                callback_response = self._request(
                    "POST",
                    self.base_url + callback_path,
                    headers=self._headers(callback_path, {"Accept": "*/*", "Content-Type": "application/json"}),
                    json={"full_redirect_url": callback_url},
                    timeout=30,
                )
                ensure_ok(callback_response, callback_path)
                link = self._get_adobe_connector_link()
                if self._adobe_link_is_active(link):
                    return link
                status = {
                    "auth_status": link.get("auth_status"),
                    "connector_status": link.get("connector_status"),
                    "auth_status_reason": link.get("auth_status_reason"),
                }
                raise RuntimeError(f"Adobe connector authorization did not become active: {status}")
            except Exception as exc:
                last_error = exc
                if attempt < ADOBE_OAUTH_FLOW_ATTEMPTS:
                    print(
                        "[chatgpt-pool] Adobe OAuth flow did not complete; restarting with fresh state: "
                        f"{exc}",
                        flush=True,
                    )
                    time.sleep(ADOBE_NETWORK_RETRY_BASE_DELAY_SECS * attempt)
        raise RuntimeError(f"Adobe connector OAuth failed after fresh-flow retry: {last_error}") from last_error

    @staticmethod
    def _parse_adobe_oauth_forms(html: str) -> list[dict[str, Any]]:
        parser = _AdobeOAuthFormParser()
        parser.feed(str(html or ""))
        return parser.forms

    def _adobe_external_request(
        self,
        session: requests.Session,
        method: str,
        url: str,
        *,
        context: str,
        **kwargs: Any,
    ) -> requests.Response:
        retryable_errors = (
            requests.exceptions.SSLError,
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.Timeout,
        )
        last_error: Exception | None = None
        for attempt in range(1, ADOBE_NETWORK_RETRY_ATTEMPTS + 1):
            try:
                response = session.request(method, url, **kwargs)
                if response.status_code < 500 or attempt >= ADOBE_NETWORK_RETRY_ATTEMPTS:
                    return response
                last_error = RuntimeError(f"{context} returned HTTP {response.status_code}")
            except retryable_errors as exc:
                last_error = exc
            if attempt < ADOBE_NETWORK_RETRY_ATTEMPTS:
                delay = ADOBE_NETWORK_RETRY_BASE_DELAY_SECS * attempt
                print(
                    f"[chatgpt-pool] transient Adobe OAuth error during {context}; "
                    f"retrying {attempt}/{ADOBE_NETWORK_RETRY_ATTEMPTS - 1}: {last_error}",
                    flush=True,
                )
                time.sleep(delay)
        if last_error:
            raise last_error
        raise RuntimeError(f"{context} failed without a response")

    def _complete_adobe_guest_oauth(self, redirect_url: str) -> str:
        common_headers = {
            "User-Agent": self.user_agent,
            "Accept-Language": "en-US,en;q=0.9",
        }
        external = requests.Session()
        response = self._adobe_external_request(
            external,
            "GET",
            redirect_url,
            context="authorization page",
            headers={
                **common_headers,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": self.base_url + "/",
            },
            timeout=30,
            allow_redirects=True,
        )
        ensure_ok(response, "Adobe OAuth authorization page")
        auth_page_url = response.url
        query = {
            key: values[-1]
            for key, values in parse_qs(urlparse(auth_page_url).query, keep_blank_values=True).items()
        }
        client_id = str(query.get("client_id") or ADOBE_GUEST_DEFAULT_CLIENT_ID)
        guest_response = self._adobe_external_request(
            external,
            "POST",
            ADOBE_GUEST_TOKEN_URL,
            context="guest token",
            headers={
                **common_headers,
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "Origin": "https://auth.services.adobe.com",
                "Referer": auth_page_url,
                "X-IMS-CLIENTID": client_id,
            },
            json={},
            timeout=30,
        )
        ensure_ok(guest_response, "Adobe guest token")
        guest_payload = guest_response.json() if guest_response.text else {}
        guest_token = str(guest_payload.get("token") or "")
        if not guest_token:
            raise RuntimeError("Adobe guest token response was empty")
        form_payload = dict(query)
        form_payload.update(
            {
                "token": guest_token,
                "redirect_uri": str(query.get("redirect_uri") or ADOBE_CONNECTOR_CALLBACK_URL),
                "response_type": str(query.get("response_type") or query.get("flow_type") or "code"),
                "flow": "unmapped",
            }
        )
        response = self._adobe_external_request(
            external,
            "POST",
            ADOBE_GUEST_EXCHANGE_URL,
            context="guest OAuth exchange",
            headers={
                **common_headers,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://auth.services.adobe.com",
                "Referer": auth_page_url,
            },
            data=form_payload,
            timeout=30,
            allow_redirects=True,
        )
        ensure_ok(response, "Adobe guest OAuth exchange")
        for _ in range(12):
            auto_form = next(
                (item for item in self._parse_adobe_oauth_forms(response.text) if item.get("id") == "auto_submit_form"),
                None,
            )
            if not auto_form:
                break
            target_url = urljoin(response.url, str(auto_form.get("action") or ""))
            fields = {str(key): str(value) for key, value in auto_form.get("fields") or []}
            origin = f"{urlparse(response.url).scheme}://{urlparse(response.url).netloc}"
            method = str(auto_form.get("method") or "post").lower()
            request_kwargs = {
                "headers": {
                    **common_headers,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Origin": origin,
                    "Referer": response.url,
                },
                "timeout": 30,
                "allow_redirects": True,
            }
            if method == "get":
                response = self._adobe_external_request(
                    external,
                    "GET",
                    target_url,
                    context="OAuth redirect",
                    params=fields,
                    **request_kwargs,
                )
            else:
                request_kwargs["headers"]["Content-Type"] = "application/x-www-form-urlencoded"
                response = self._adobe_external_request(
                    external,
                    "POST",
                    target_url,
                    context="OAuth redirect",
                    data=fields,
                    **request_kwargs,
                )
            ensure_ok(response, "Adobe OAuth redirect")
        final_url = str(response.url or "")
        if "chatgpt.com/connector_platform_oauth_redirect" not in final_url:
            raise RuntimeError(f"Adobe guest OAuth did not reach ChatGPT callback: {urlparse(final_url).netloc}{urlparse(final_url).path}")
        return final_url

    def _wait_adobe_mask_outputs(
        self,
        conversation_id: str,
        *,
        timeout_secs: float,
        poll_interval_secs: float,
    ) -> list[AdobeMaskArtifact]:
        deadline = time.time() + max(60.0, float(timeout_secs or EDITABLE_FILE_TIMEOUT_SECS))
        approved_targets: set[str] = set()
        last_mask_count = 0
        last_mask_change_at = 0.0
        last_log_at = 0.0
        terminal_without_masks_at = 0.0
        while time.time() < deadline:
            conversation = self._get_editable_conversation_detail(conversation_id)
            confirmations = self._pending_adobe_confirmations(conversation)
            submitted_approval = False
            for confirmation, target_message_id in confirmations:
                if target_message_id in approved_targets:
                    continue
                self._submit_adobe_always_allow(conversation_id, conversation, confirmation, target_message_id)
                approved_targets.add(target_message_id)
                submitted_approval = True
            if submitted_approval:
                time.sleep(1)
                continue

            masks = self._extract_adobe_masks(conversation)
            if len(masks) != last_mask_count:
                last_mask_count = len(masks)
                last_mask_change_at = time.time()
                print(
                    f"[chatgpt-pool] Adobe masks ready: conversation_id={conversation_id}; masks={last_mask_count}",
                    flush=True,
                )
            terminal = self._editable_conversation_terminal(conversation)
            if terminal:
                if masks:
                    return masks[:ADOBE_MAX_MASKS]
                if not terminal_without_masks_at:
                    terminal_without_masks_at = time.time()
                if time.time() - terminal_without_masks_at >= 20:
                    raise RuntimeError(
                        "Adobe connector turn finished without a valid mask: "
                        + self._editable_failure_summary(conversation)
                    )
            else:
                terminal_without_masks_at = 0.0
            current_status = self._editable_current_status(conversation)
            if (
                masks
                and last_mask_change_at
                and time.time() - last_mask_change_at >= ADOBE_MASK_SETTLE_SECS
                and current_status not in IMAGE_ACTIVE_STATUS_MARKERS
            ):
                return masks[:ADOBE_MAX_MASKS]
            now = time.time()
            if now - last_log_at >= 60:
                print(
                    "[chatgpt-pool] waiting for Adobe masks: "
                    f"conversation_id={conversation_id}; masks={len(masks)}; status={current_status or '-'}",
                    flush=True,
                )
                last_log_at = now
            time.sleep(max(1.0, float(poll_interval_secs or EDITABLE_FILE_POLL_INTERVAL_SECS)))
        raise RuntimeError(f"timed out waiting for Adobe mask outputs: conversation_id={conversation_id}")

    def _collect_additional_adobe_masks(
        self,
        conversation_id: str,
        masks: list[AdobeMaskArtifact],
        *,
        max_additional: int,
        poll_interval_secs: float,
    ) -> list[AdobeMaskArtifact]:
        collected = list(masks)
        for _ in range(max(0, int(max_additional or 0))):
            before_urls = {item.output_url for item in collected}
            before_count = len(before_urls)
            conversation = self._get_editable_conversation_detail(conversation_id)
            parent_message_id = str(conversation.get("current_node") or "")
            selected_descriptions = [item.description for item in collected if item.description]
            self._submit_adobe_additional_mask_request(
                conversation_id,
                parent_message_id,
                selected_descriptions,
            )
            deadline = time.time() + ADOBE_ADDITIONAL_MASK_TIMEOUT_SECS
            terminal_seen_at = 0.0
            added = False
            while time.time() < deadline:
                conversation = self._get_editable_conversation_detail(conversation_id)
                latest = self._extract_adobe_masks(conversation)
                latest_urls = {item.output_url for item in latest}
                if len(latest_urls - before_urls) > 0:
                    collected = latest[:ADOBE_MAX_MASKS]
                    added = True
                    print(
                        "[chatgpt-pool] additional Adobe mask ready: "
                        f"conversation_id={conversation_id}; masks={len(collected)}",
                        flush=True,
                    )
                    break
                current_message = self._editable_current_message(conversation)
                current_role = str(((current_message.get("author") or {}).get("role") or ""))
                current_status = str(current_message.get("status") or "").strip().lower()
                current_node = str(conversation.get("current_node") or "")
                terminal = (
                    current_node != parent_message_id
                    and current_role == "assistant"
                    and current_status in IMAGE_TERMINAL_STATUS_MARKERS
                )
                if terminal:
                    if not terminal_seen_at:
                        terminal_seen_at = time.time()
                    if time.time() - terminal_seen_at >= 15:
                        break
                time.sleep(max(1.0, float(poll_interval_secs or EDITABLE_FILE_POLL_INTERVAL_SECS)))
            if not added:
                print(
                    "[chatgpt-pool] no additional Adobe mask returned; using existing masks: "
                    f"conversation_id={conversation_id}; masks={before_count}",
                    flush=True,
                )
                break
            if len(collected) >= ADOBE_MAX_MASKS:
                break
        return collected

    def _submit_adobe_additional_mask_request(
        self,
        conversation_id: str,
        parent_message_id: str,
        selected_descriptions: list[str],
    ) -> None:
        selected_text = "；".join(selected_descriptions[-ADOBE_MAX_MASKS:]) or "主主体"
        prompt = (
            "继续处理同一张已经上传到 Adobe 的图片。不要再次调用 adobe_mandatory_init，"
            "不要重新上传，不要解释能力。请直接调用一次 image_select_by_prompt，"
            "选择一个尚未分层、边界清晰、最值得独立编辑的主要可见区域。"
            f"已经生成的蒙版包括：{selected_text}。不要重复这些区域。"
            "每次只调用一个 Adobe 工具；完成后简短确认。如果没有新的有效区域，只回复 NO_MORE_MASKS。"
        )
        message = {
            "id": new_uuid(),
            "author": {"role": "user"},
            "create_time": time.time(),
            "content": {"content_type": "text", "parts": [prompt]},
            "metadata": {
                "developer_mode_connector_ids": [ADOBE_CONNECTOR_ID],
                "selected_sources": [],
                "selected_github_repos": [],
                "selected_all_github_repos": False,
                "serialization_metadata": {"custom_symbol_offsets": []},
            },
        }
        self._bootstrap()
        requirements = self._requirements()
        path = "/backend-api/f/conversation"
        response = self.session.post(
            self.base_url + path,
            headers=self._image_headers(path, requirements, "", "text/event-stream"),
            json={
                "action": "next",
                "messages": [message],
                "conversation_id": conversation_id,
                "parent_message_id": parent_message_id,
                "model": EDITABLE_FILE_MODEL,
                "client_prepare_state": "success",
                "timezone_offset_min": self._timezone_offset_min(),
                "timezone": self._timezone(),
                "conversation_mode": {"kind": "primary_assistant"},
                "enable_message_followups": True,
                "system_hints": [],
                "supports_buffering": True,
                "supported_encodings": ["v1"],
                "client_contextual_info": self._client_contextual_info(time_since_loaded=500),
                "paragen_cot_summary_display_override": "allow",
                "force_parallel_switch": "auto",
                "thinking_effort": EDITABLE_FILE_THINKING_EFFORT,
            },
            timeout=(30, 180),
            stream=True,
        )
        ensure_ok(response, "Adobe additional mask request")
        try:
            for payload in iter_sse_payloads(response):
                if payload == "[DONE]":
                    break
        except requests.exceptions.RequestException as exc:
            print(
                f"[chatgpt-pool] Adobe additional-mask stream interrupted; continuing by polling: {exc}",
                flush=True,
            )
        finally:
            response.close()

    def _pending_adobe_confirmations(self, conversation: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
        values: list[tuple[dict[str, Any], str]] = []
        mapping = conversation.get("mapping") if isinstance(conversation, dict) else {}
        for node in (mapping or {}).values():
            message = (node or {}).get("message") or {}
            metadata = message.get("metadata") if isinstance(message, dict) else {}
            jit_data = metadata.get("jit_plugin_data") if isinstance(metadata, dict) else {}
            from_server = jit_data.get("from_server") if isinstance(jit_data, dict) else {}
            if not isinstance(from_server, dict) or from_server.get("type") != "confirm_action":
                continue
            body = from_server.get("body") if isinstance(from_server.get("body"), dict) else {}
            for action in body.get("actions") or []:
                always_allow = action.get("always_allow") if isinstance(action, dict) else {}
                target_message_id = str((always_allow or {}).get("target_message_id") or "")
                if target_message_id:
                    values.append((message, target_message_id))
                    break
        return values

    def _submit_adobe_always_allow(
        self,
        conversation_id: str,
        conversation: dict[str, Any],
        confirmation: dict[str, Any],
        target_message_id: str,
    ) -> None:
        metadata = confirmation.get("metadata") if isinstance(confirmation, dict) else {}
        message = {
            "id": new_uuid(),
            "author": {"role": "tool", "name": "api_tool.call_tool"},
            "create_time": time.time(),
            "content": {"content_type": "text", "parts": [""]},
            "recipient": "all",
            "metadata": {
                "jit_plugin_data": {
                    "from_client": {
                        "type": "always_allow",
                        "target_message_id": target_message_id,
                    }
                },
                "gizmo_id": str((metadata or {}).get("gizmo_id") or "FAKE_CONNECTOR_GIZMO"),
                "working_turn_id": str((metadata or {}).get("working_turn_id") or ""),
            },
        }
        self._bootstrap()
        requirements = self._requirements()
        path = "/backend-api/f/conversation"
        response = self.session.post(
            self.base_url + path,
            headers=self._image_headers(path, requirements, "", "text/event-stream"),
            json={
                "action": "next",
                "messages": [message],
                "conversation_id": conversation_id,
                "parent_message_id": str(conversation.get("current_node") or ""),
                "model": EDITABLE_FILE_MODEL,
                "client_prepare_state": "success",
                "timezone_offset_min": self._timezone_offset_min(),
                "timezone": self._timezone(),
                "conversation_mode": {"kind": "primary_assistant"},
                "enable_message_followups": True,
                "system_hints": [],
                "supports_buffering": True,
                "supported_encodings": ["v1"],
                "client_contextual_info": self._client_contextual_info(time_since_loaded=500),
                "paragen_cot_summary_display_override": "allow",
                "force_parallel_switch": "auto",
                "thinking_effort": EDITABLE_FILE_THINKING_EFFORT,
            },
            timeout=(30, 180),
            stream=True,
        )
        ensure_ok(response, "Adobe connector confirmation")
        try:
            for payload in iter_sse_payloads(response):
                if payload == "[DONE]":
                    break
        except requests.exceptions.RequestException as exc:
            print(
                f"[chatgpt-pool] Adobe confirmation stream interrupted; continuing by polling: {exc}",
                flush=True,
            )
        finally:
            response.close()

    def _extract_adobe_masks(self, conversation: dict[str, Any]) -> list[AdobeMaskArtifact]:
        masks: list[AdobeMaskArtifact] = []
        seen_urls: set[str] = set()
        mapping = conversation.get("mapping") if isinstance(conversation, dict) else {}
        nodes = sorted(
            (mapping or {}).values(),
            key=lambda item: float(((item or {}).get("message") or {}).get("create_time") or 0.0),
        )
        for node in nodes:
            message = (node or {}).get("message") or {}
            payloads: list[Any] = [message]
            content = message.get("content") if isinstance(message, dict) else {}
            candidates: list[str] = []
            if isinstance(content, dict):
                if isinstance(content.get("text"), str):
                    candidates.append(content["text"])
                candidates.extend(item for item in content.get("parts") or [] if isinstance(item, str))
            for candidate in candidates:
                text = candidate.strip()
                if text.startswith("```") and text.endswith("```"):
                    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL)
                try:
                    payloads.append(json.loads(text))
                except (json.JSONDecodeError, TypeError):
                    continue
            for payload in payloads:
                for item in self._walk_dicts(payload):
                    output_url = str(item.get("outputUrl") or item.get("output_url") or "").strip()
                    if not output_url or output_url in seen_urls or item.get("success") is False:
                        continue
                    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                    masks.append(
                        AdobeMaskArtifact(
                            output_url=output_url,
                            description=str(item.get("maskDescription") or item.get("mask_description") or "Selected region").strip(),
                            width=int(metadata.get("mask_width") or metadata.get("source_width") or 0),
                            height=int(metadata.get("mask_height") or metadata.get("source_height") or 0),
                            request_id=str(item.get("requestId") or item.get("request_id") or ""),
                        )
                    )
                    seen_urls.add(output_url)
        return masks

    def _editable_current_message(self, conversation: dict[str, Any]) -> dict[str, Any]:
        mapping = conversation.get("mapping") if isinstance(conversation, dict) else {}
        current = (mapping or {}).get(str(conversation.get("current_node") or "")) or {}
        message = current.get("message") if isinstance(current, dict) else {}
        return message if isinstance(message, dict) else {}

    def _editable_current_status(self, conversation: dict[str, Any]) -> str:
        return str(self._editable_current_message(conversation).get("status") or "").strip().lower()

    def _editable_conversation_terminal(self, conversation: dict[str, Any]) -> bool:
        message = self._editable_current_message(conversation)
        author = message.get("author") if isinstance(message.get("author"), dict) else {}
        content = message.get("content") if isinstance(message.get("content"), dict) else {}
        status = str(message.get("status") or "").strip().lower()
        if str(content.get("content_type") or "") == "system_error":
            return True
        return str(author.get("role") or "") == "assistant" and status in IMAGE_TERMINAL_STATUS_MARKERS

    def _editable_failure_summary(self, conversation: dict[str, Any]) -> str:
        system_error = self._image_poll_system_error_details(conversation)
        if system_error:
            return system_error
        mapping = conversation.get("mapping") if isinstance(conversation, dict) else {}
        messages = [
            (node or {}).get("message") or {}
            for node in (mapping or {}).values()
            if isinstance((node or {}).get("message"), dict)
        ]
        messages.sort(key=lambda item: float(item.get("create_time") or 0.0), reverse=True)
        for message in messages:
            author = message.get("author") if isinstance(message.get("author"), dict) else {}
            if str(author.get("role") or "") != "assistant":
                continue
            text = self._editable_message_text(message)
            if text:
                return text[:600]
        return "upstream returned a terminal state without mask output"

    def _download_adobe_mask(self, artifact: AdobeMaskArtifact, size: tuple[int, int]) -> Image.Image:
        response = self._request("GET", artifact.output_url, timeout=120)
        ensure_ok(response, "Adobe mask download")
        image = Image.open(BytesIO(response.content))
        image.load()
        mask = image.convert("L")
        if mask.size != size:
            mask = mask.resize(size, Image.Resampling.LANCZOS)
        return mask

    @staticmethod
    def _psd_layer_slug(value: str, fallback: str) -> str:
        text = re.sub(r"[^\w\u4e00-\u9fff]+", "_", str(value or "").strip(), flags=re.UNICODE)
        text = re.sub(r"_+", "_", text).strip("_")
        return (text[:48] or fallback).upper()

    def _psd_semantic_label(self, description: str, index: int) -> str:
        lower = str(description or "").lower()
        if index == 0 or "subject" in lower or "主体" in lower or "人物" in lower:
            return "MAIN_SUBJECT"
        return self._psd_layer_slug(description, f"REGION_{index + 1:02d}")

    @staticmethod
    def _find_image_magick() -> str:
        for candidate in ("magick", "/opt/homebrew/bin/magick", "/usr/local/bin/magick", "convert"):
            found = shutil.which(candidate)
            if found:
                return found
            path = Path(candidate)
            if path.exists():
                return str(path)
        return ""

    @staticmethod
    def _image_magick_identify_command(magick: str, path: Path) -> list[str]:
        if Path(magick).name.lower().startswith("magick"):
            return [magick, "identify", str(path)]
        for candidate in ("identify", "/opt/homebrew/bin/identify", "/usr/local/bin/identify"):
            found = shutil.which(candidate)
            if found:
                return [found, str(path)]
            candidate_path = Path(candidate)
            if candidate_path.exists():
                return [str(candidate_path), str(path)]
        raise RuntimeError("ImageMagick identify is required to validate layered PSD output")

    def _build_adobe_psd_bundle(
        self,
        source_data: bytes,
        mask_artifacts: list[AdobeMaskArtifact],
        output_dir: Path,
        *,
        conversation_id: str,
    ) -> EditableFileExportResult:
        source = Image.open(BytesIO(source_data)).convert("RGBA")
        width, height = source.size
        source = Image.alpha_composite(Image.new("RGBA", source.size, (0, 0, 0, 0)), source)
        original_alpha = source.getchannel("A")
        usable_masks: list[tuple[AdobeMaskArtifact, Image.Image, float]] = []
        seen_hashes: set[str] = set()
        for artifact in mask_artifacts[:ADOBE_MAX_MASKS]:
            mask = self._download_adobe_mask(artifact, source.size)
            mask = mask.point(lambda value: 255 if value >= 128 else 0)
            digest = hashlib.sha256(mask.tobytes()).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            coverage = float(ImageStat.Stat(mask).mean[0]) / 255.0
            if coverage < PSD_MIN_LAYER_COVERAGE or coverage > PSD_MAX_LAYER_COVERAGE:
                continue
            usable_masks.append((artifact, mask, coverage))
        if not usable_masks:
            raise RuntimeError("Adobe connector returned masks, but none contained a usable selected region")

        assigned = Image.new("L", source.size, 0)
        semantic_regions_reversed: list[tuple[AdobeMaskArtifact, Image.Image, float]] = []
        for artifact, mask, _ in reversed(usable_masks):
            exclusive = ImageChops.subtract(mask, assigned)
            assigned = ImageChops.lighter(assigned, mask)
            coverage = float(ImageStat.Stat(exclusive).mean[0]) / 255.0
            if coverage >= PSD_MIN_LAYER_COVERAGE:
                semantic_regions_reversed.append((artifact, exclusive, coverage))
        semantic_regions = list(reversed(semantic_regions_reversed))
        if not semantic_regions:
            raise RuntimeError("Adobe masks completely overlapped and did not produce an editable semantic layer")

        layers_dir = output_dir / "layers"
        layers_dir.mkdir(parents=True, exist_ok=True)
        composite_path = output_dir / "composite_preview.png"
        original_path = output_dir / "original_reference.png"
        source.save(composite_path, "PNG")
        source.save(original_path, "PNG")

        layer_records: list[dict[str, Any]] = []

        def save_layer(label: str, region_alpha: Image.Image, description: str, coverage: float) -> Path:
            index = len(layer_records) + 1
            file_name = f"{index:02d}_{self._psd_layer_slug(label, f'LAYER_{index:02d}')}.png"
            path = layers_dir / file_name
            layer_image = source.copy()
            layer_image.putalpha(ImageChops.multiply(original_alpha, region_alpha))
            layer_image.save(path, "PNG")
            layer_records.append(
                {
                    "index": index,
                    "name": label,
                    "description": description,
                    "file": f"layers/{file_name}",
                    "coverage": round(float(coverage), 6),
                }
            )
            return path

        background_alpha = ImageChops.invert(assigned)
        background_coverage = float(ImageStat.Stat(background_alpha).mean[0]) / 255.0
        layer_paths: list[tuple[Path, str]] = [
            (
                save_layer("BACKGROUND", background_alpha, "All visible pixels outside Adobe semantic selections", background_coverage),
                "01_BACKGROUND",
            )
        ]
        for semantic_index, (artifact, region_alpha, coverage) in enumerate(semantic_regions):
            semantic_label = self._psd_semantic_label(artifact.description, semantic_index)
            path = save_layer(semantic_label, region_alpha, artifact.description, coverage)
            layer_paths.append((path, f"{len(layer_paths) + 1:02d}_{semantic_label}"))
        if len(layer_paths) < 2:
            raise RuntimeError("PSD assembly requires at least background and one semantic layer")
        reconstructed = Image.new("RGBA", source.size, (0, 0, 0, 0))
        for path, _ in layer_paths:
            with Image.open(path) as layer_image:
                reconstructed = Image.alpha_composite(reconstructed, layer_image.convert("RGBA"))
        if ImageChops.difference(reconstructed, source).getbbox() is not None:
            raise RuntimeError("assembled PNG layers do not reconstruct the source image exactly")

        manifest = {
            "version": 1,
            "generator": "adobe-semantic-masks+imagemagick",
            "connector_id": ADOBE_CONNECTOR_ID,
            "conversation_id": conversation_id,
            "canvas": {"width": width, "height": height},
            "layer_count": len(layer_records),
            "reconstruction_exact": True,
            "layers": layer_records,
            "composite_preview": composite_path.name,
            "original_reference": original_path.name,
        }
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        readme_path = output_dir / "README.txt"
        readme_path.write_text(
            "Editable PSD layers generated from Adobe semantic selection masks.\n"
            "Every PNG uses the original full canvas size and can be aligned at coordinates 0,0.\n",
            encoding="utf-8",
        )

        magick = self._find_image_magick()
        if not magick:
            raise RuntimeError("ImageMagick is required to assemble a layered PSD")
        psd_path = output_dir / "layered_output.psd"
        command = [magick]
        for path, label in [(composite_path, "Composite"), *layer_paths]:
            command.extend(["(", str(path), "-type", "TrueColorAlpha", "-set", "label", label, ")"])
        command.extend(["-define", "psd:preserve-opacity-mask=true", str(psd_path)])
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=180,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", "replace")[-1200:]
            raise RuntimeError(f"ImageMagick layered PSD assembly failed: {detail}")

        zip_path = output_dir / "layered_layers.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(composite_path, composite_path.name)
            archive.write(original_path, original_path.name)
            archive.write(manifest_path, manifest_path.name)
            archive.write(readme_path, readme_path.name)
            for path, _ in layer_paths:
                archive.write(path, f"layers/{path.name}")
        self._validate_psd_bundle(psd_path, zip_path)
        return EditableFileExportResult(
            conversation_id=conversation_id,
            primary_path=psd_path,
            zip_path=zip_path,
        )

    def _validate_psd_bundle(self, psd_path: Path, zip_path: Path) -> None:
        if not psd_path.exists() or psd_path.stat().st_size < PSD_MIN_FILE_SIZE:
            raise RuntimeError("generated PSD is missing or abnormally small")
        if psd_path.read_bytes()[:4] != b"8BPS":
            raise RuntimeError("generated PSD does not have a valid 8BPS header")
        magick = self._find_image_magick()
        if not magick:
            raise RuntimeError("ImageMagick is required to validate layered PSD output")
        identified = subprocess.run(
            self._image_magick_identify_command(magick, psd_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
        scenes = [line for line in identified.stdout.decode("utf-8", "replace").splitlines() if line.strip()]
        if identified.returncode != 0 or len(scenes) < 3:
            detail = identified.stderr.decode("utf-8", "replace")[-800:]
            raise RuntimeError(f"generated PSD does not contain at least two editable layers: {detail}")
        if not zip_path.exists() or not zipfile.is_zipfile(zip_path):
            raise RuntimeError("generated layer ZIP is invalid")
        bad_markers = ("fallback", "placeholder", "automatic extraction unavailable")
        with zipfile.ZipFile(zip_path) as archive:
            names = [name.replace("\\", "/") for name in archive.namelist()]
            layer_names = [
                name
                for name in names
                if name.startswith("layers/")
                and not name.endswith("/")
                and Path(name).suffix.lower() == ".png"
            ]
            layer_names.sort()
            if len(layer_names) < 2:
                raise RuntimeError("generated layer ZIP contains fewer than two PNG layers")
            canvas_size: tuple[int, int] | None = None
            has_transparency = False
            layer_images: list[Image.Image] = []
            for name in layer_names:
                with archive.open(name) as source_file:
                    image = Image.open(BytesIO(source_file.read())).convert("RGBA")
                    image.load()
                layer_images.append(image)
                if canvas_size is None:
                    canvas_size = image.size
                elif image.size != canvas_size:
                    raise RuntimeError("generated PNG layers do not use a consistent canvas size")
                alpha_min, alpha_max = image.getchannel("A").getextrema()
                has_transparency = has_transparency or alpha_min < alpha_max or alpha_min < 255
            if not has_transparency:
                raise RuntimeError("generated PNG layers do not contain real transparency")
            if "composite_preview.png" not in names:
                raise RuntimeError("generated layer ZIP is missing composite_preview.png")
            with archive.open("composite_preview.png") as source_file:
                preview = Image.open(BytesIO(source_file.read())).convert("RGBA")
                preview.load()
            if canvas_size and preview.size != canvas_size:
                raise RuntimeError("composite preview size does not match layer canvas")
            reconstructed = Image.new("RGBA", preview.size, (0, 0, 0, 0))
            for layer_image in layer_images:
                reconstructed = Image.alpha_composite(reconstructed, layer_image)
            expected = Image.alpha_composite(Image.new("RGBA", preview.size, (0, 0, 0, 0)), preview)
            if ImageChops.difference(reconstructed, expected).getbbox() is not None:
                raise RuntimeError("generated PNG layers do not reconstruct composite_preview.png exactly")
            for name in names:
                if Path(name).suffix.lower() not in {".txt", ".json", ".md"}:
                    continue
                text = archive.read(name).decode("utf-8", "replace").lower()
                if any(marker in text for marker in bad_markers):
                    raise RuntimeError(f"generated layer ZIP contains invalid marker text in {name}")

    def _export_editable_file_zip(
        self,
        base64_images: list[str],
        prompt: str,
        output_dir: str | Path,
        *,
        primary_label: str,
        primary_suffixes: tuple[str, ...],
        primary_mime_types: set[str],
        primary_mime_keywords: tuple[str, ...],
        primary_default_extension: str,
        export_file_re: re.Pattern[str],
        timeout_secs: float,
        poll_interval_secs: float,
    ) -> EditableFileExportResult:
        self.session.headers["OAI-Client-Version"] = EDITABLE_FILE_CLIENT_VERSION
        self.session.headers["OAI-Client-Build-Number"] = EDITABLE_FILE_CLIENT_BUILD_NUMBER
        output_path = Path(output_dir).expanduser().resolve()
        output_path.mkdir(parents=True, exist_ok=True)
        uploaded = [self._upload_editable_base64_image(item, index) for index, item in enumerate(base64_images, start=1)]
        conduit_token = self._prepare_editable_conversation(prompt, [item["mime_type"] for item in uploaded])
        conversation_id = self._run_editable_conversation(prompt, uploaded, conduit_token)
        artifacts = self._wait_editable_output_artifacts(
            conversation_id,
            primary_label,
            primary_suffixes,
            primary_mime_types,
            primary_mime_keywords,
            export_file_re,
            timeout_secs,
            poll_interval_secs,
        )
        downloaded = [
            self._download_editable_artifact(
                conversation_id,
                item,
                output_path,
                primary_mime_types,
                primary_mime_keywords,
                primary_default_extension,
            )
            for item in artifacts
        ]
        primary_path = next((item for item in downloaded if item.suffix.lower() in primary_suffixes), None)
        zip_path = next((item for item in downloaded if item.suffix.lower() == ".zip"), None)
        if not primary_path or not zip_path:
            raise RuntimeError(f"download finished but did not get both {primary_label} and zip files: {downloaded}")
        return EditableFileExportResult(conversation_id=conversation_id, primary_path=primary_path, zip_path=zip_path)

    def _decode_editable_base64_image(self, base64_image: str, index: int) -> tuple[bytes, str, str, int, int]:
        raw = str(base64_image or "").strip()
        if not raw:
            raise ValueError("base64 image is empty")
        mime_type = ""
        payload = raw
        match = re.match(r"^data:([^;]+);base64,(.*)$", raw, re.IGNORECASE | re.DOTALL)
        if match:
            mime_type = str(match.group(1) or "").strip().lower()
            payload = str(match.group(2) or "").strip()
        data = base64.b64decode(payload)
        image = Image.open(BytesIO(data))
        image.load()
        width, height = image.size
        mime_type = Image.MIME.get(image.format, mime_type or "image/png")
        extension = mimetypes.guess_extension(mime_type) or ".png"
        return data, f"image_{index}{extension}", mime_type, width, height

    def _upload_editable_base64_image(self, base64_image: str, index: int) -> dict[str, Any]:
        data, file_name, mime_type, width, height = self._decode_editable_base64_image(base64_image, index)
        path = "/backend-api/files"
        response = self.session.post(
            self.base_url + path,
            headers=self._headers(path, {"Accept": "*/*", "Content-Type": "application/json"}),
            json={
                "file_name": file_name,
                "file_size": len(data),
                "use_case": "multimodal",
                "timezone_offset_min": self._timezone_offset_min(),
                "reset_rate_limits": False,
                "store_in_library": True,
                "library_persistence_mode": "opportunistic",
            },
            timeout=60,
        )
        ensure_ok(response, path)
        payload = response.json()
        upload_url = str(payload.get("upload_url") or "")
        file_id = str(payload.get("file_id") or "")
        if not upload_url or not file_id:
            raise RuntimeError(f"invalid upload response: {payload}")
        response = self.session.put(
            upload_url,
            headers={
                "Content-Type": mime_type,
                "x-ms-blob-type": "BlockBlob",
                "x-ms-version": "2020-04-08",
                "Origin": self.base_url,
                "Referer": self.base_url + "/",
                "User-Agent": self.user_agent,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": str(self.session.headers.get("Accept-Language") or "zh-CN,zh;q=0.9,en;q=0.8"),
            },
            data=data,
            timeout=120,
        )
        ensure_ok(response, "image_upload")
        path = f"/backend-api/files/{file_id}/uploaded"
        response = self.session.post(
            self.base_url + path,
            headers=self._headers(path, {"Accept": "*/*", "Content-Type": "application/json"}),
            data="{}",
            timeout=60,
        )
        ensure_ok(response, path)
        return {
            "file_id": file_id,
            "library_file_id": str(payload.get("library_file_id") or ""),
            "file_name": file_name,
            "file_size": len(data),
            "mime_type": mime_type,
            "width": width,
            "height": height,
        }

    def _prepare_editable_conversation(self, prompt: str, attachment_mime_types: list[str]) -> str:
        path = "/backend-api/f/conversation/prepare"
        payload: dict[str, Any] = {
            "action": "next",
            "fork_from_shared_post": False,
            "parent_message_id": "client-created-root",
            "model": EDITABLE_FILE_MODEL,
            "client_prepare_state": "success",
            "timezone_offset_min": self._timezone_offset_min(),
            "timezone": self._timezone(),
            "conversation_mode": {"kind": "primary_assistant"},
            "system_hints": [],
            "partial_query": {"id": new_uuid(), "author": {"role": "user"}, "content": {"content_type": "text", "parts": [prompt]}},
            "supports_buffering": True,
            "supported_encodings": ["v1"],
            "client_contextual_info": self._client_contextual_info(time_since_loaded=120),
            "thinking_effort": EDITABLE_FILE_THINKING_EFFORT,
        }
        if attachment_mime_types:
            payload["attachment_mime_types"] = attachment_mime_types
        response = self.session.post(
            self.base_url + path,
            headers=self._headers(path, {"Accept": "*/*", "Content-Type": "application/json", "X-Conduit-Token": "no-token"}),
            json=payload,
            timeout=60,
        )
        ensure_ok(response, path)
        conduit_token = str(response.json().get("conduit_token") or "")
        if not conduit_token:
            raise RuntimeError(f"missing conduit_token: {response.text}")
        return conduit_token

    def _run_editable_conversation(
        self,
        prompt: str,
        uploaded: list[dict[str, Any]],
        conduit_token: str,
        connector_ids: list[str] | None = None,
    ) -> str:
        self._bootstrap()
        requirements = self._requirements()
        selected_connector_ids = [
            str(item or "").strip()
            for item in (connector_ids or [])
            if str(item or "").strip()
        ]
        message: dict[str, Any] = {"id": new_uuid(), "author": {"role": "user"}, "create_time": time.time()}
        if uploaded:
            parts = [
                {
                    "content_type": "image_asset_pointer",
                    "asset_pointer": f"sediment://{item['file_id']}",
                    "size_bytes": item["file_size"],
                    "width": item["width"],
                    "height": item["height"],
                }
                for item in uploaded
            ]
            parts.append(prompt)
            message["content"] = {"content_type": "multimodal_text", "parts": parts}
            message["metadata"] = {
                "attachments": [
                    {
                        "id": item["file_id"],
                        "size": item["file_size"],
                        "name": item["file_name"],
                        "mime_type": item["mime_type"],
                        "width": item["width"],
                        "height": item["height"],
                        "source": "library",
                        "library_file_id": item["library_file_id"],
                        "is_big_paste": False,
                    }
                    for item in uploaded
                ],
                "developer_mode_connector_ids": selected_connector_ids,
                "selected_sources": [],
                "selected_github_repos": [],
                "selected_all_github_repos": False,
                "serialization_metadata": {"custom_symbol_offsets": []},
            }
        else:
            message["content"] = {"content_type": "text", "parts": [prompt]}
        path = "/backend-api/f/conversation"
        response = self.session.post(
            self.base_url + path,
            headers=self._image_headers(path, requirements, conduit_token, "text/event-stream"),
            json={
                "action": "next",
                "messages": [message],
                "parent_message_id": "client-created-root",
                "model": EDITABLE_FILE_MODEL,
                "client_prepare_state": "sent",
                "timezone_offset_min": self._timezone_offset_min(),
                "timezone": self._timezone(),
                "conversation_mode": {"kind": "primary_assistant"},
                "enable_message_followups": True,
                "system_hints": [],
                "supports_buffering": True,
                "supported_encodings": ["v1"],
                "client_contextual_info": self._client_contextual_info(time_since_loaded=401),
                "paragen_cot_summary_display_override": "allow",
                "force_parallel_switch": "auto",
                "thinking_effort": EDITABLE_FILE_THINKING_EFFORT,
            },
            timeout=300,
            stream=True,
        )
        ensure_ok(response, path)
        conversation_id = ""
        try:
            try:
                for payload in iter_sse_payloads(response):
                    if payload == "[DONE]":
                        break
                    conversation_id = conversation_id or self._find_editable_value(payload, "conversation_id")
            except requests.exceptions.RequestException as exc:
                if not conversation_id:
                    raise
                print(
                    "[chatgpt-pool] editable stream interrupted; continuing by polling: "
                    f"conversation_id={conversation_id}; error={exc}",
                    flush=True,
                )
        finally:
            response.close()
        if not conversation_id:
            raise RuntimeError("conversation_id not found in stream")
        return conversation_id

    def _wait_editable_output_artifacts(
        self,
        conversation_id: str,
        primary_label: str,
        primary_suffixes: tuple[str, ...],
        primary_mime_types: set[str],
        primary_mime_keywords: tuple[str, ...],
        export_file_re: re.Pattern[str],
        timeout_secs: float,
        poll_interval_secs: float,
    ) -> list[EditableFileArtifact]:
        deadline = time.time() + timeout_secs
        while time.time() < deadline:
            try:
                conversation = self._get_editable_conversation_detail(conversation_id)
                targeted = self._pick_editable_target_artifacts(
                    self._extract_editable_artifacts(conversation, export_file_re),
                    primary_suffixes,
                    primary_mime_types,
                    primary_mime_keywords,
                )
                if targeted:
                    return targeted
                if self._editable_conversation_terminal(conversation):
                    raise RuntimeError(
                        f"ChatGPT conversation finished without {primary_label}/zip outputs: "
                        + self._editable_failure_summary(conversation)
                    )
            except Exception as exc:
                if isinstance(exc, RuntimeError) and "conversation finished without" in str(exc):
                    raise
                print(f"[chatgpt-pool] editable poll failed: {exc}", flush=True)
            time.sleep(poll_interval_secs)
        raise RuntimeError(f"timed out waiting for {primary_label}/zip outputs")

    def _get_editable_conversation_detail(self, conversation_id: str) -> dict[str, Any]:
        path = f"/backend-api/conversation/{conversation_id}"
        deadline = time.time() + 30
        while True:
            response = self._request(
                "GET",
                self.base_url + path,
                headers=self._editable_conversation_document_headers(path, conversation_id),
                timeout=60,
            )
            if 200 <= response.status_code < 300:
                return response.json()
            inaccessible = response.status_code == 404 and "conversation_inaccessible" in response.text
            if not inaccessible or time.time() >= deadline:
                ensure_ok(response, path)
            time.sleep(2)

    def _editable_browser_headers(self, path: str, conversation_id: str) -> dict[str, str]:
        headers = self._headers(path, {"Accept": "*/*"})
        headers["Referer"] = f"{self.base_url}/c/{conversation_id}"
        return headers

    def _editable_conversation_document_headers(self, path: str, conversation_id: str) -> dict[str, str]:
        headers = self._editable_browser_headers(path, conversation_id)
        headers["X-OpenAI-Target-Route"] = "/backend-api/conversation/{conversation_id}"
        return headers

    def _extract_editable_artifacts(self, conversation: dict[str, Any], export_file_re: re.Pattern[str]) -> list[EditableFileArtifact]:
        artifacts: dict[str, EditableFileArtifact] = {}
        mapping = conversation.get("mapping") if isinstance(conversation, dict) else {}
        for node in sorted((mapping or {}).values(), key=lambda item: float(((item or {}).get("message") or {}).get("create_time") or 0.0)):
            message = (node or {}).get("message") or {}
            message_id = str(message.get("id") or "")
            author_role = str(((message.get("author") or {}).get("role") or "")).strip()
            if author_role not in {"assistant", "tool"}:
                continue
            create_time = float(message.get("create_time") or 0.0)
            message_text = self._editable_message_text(message)
            for artifact in self._extract_editable_message_artifacts(message, message_id, author_role, create_time, export_file_re):
                key = artifact.attachment_id or artifact.file_id or artifact.name or artifact.sandbox_path
                if key:
                    artifacts[key] = self._merge_editable_artifact(artifacts.get(key), artifact)
            for export_path in self._extract_editable_export_paths(message_text, export_file_re):
                inferred = EditableFileArtifact(name=Path(export_path).name, create_time=create_time, author_role=author_role, sandbox_path=export_path, message_id=message_id)
                existing_key = next(
                    (
                        key
                        for key, artifact in artifacts.items()
                        if artifact.name == inferred.name or (artifact.sandbox_path and Path(artifact.sandbox_path).name == inferred.name)
                    ),
                    export_path,
                )
                artifacts[existing_key] = self._merge_editable_artifact(artifacts.get(existing_key), inferred)
        return sorted(artifacts.values(), key=lambda item: item.create_time)

    def _extract_editable_message_artifacts(self, message: dict[str, Any], message_id: str, author_role: str, create_time: float, export_file_re: re.Pattern[str]) -> list[EditableFileArtifact]:
        artifacts: list[EditableFileArtifact] = []
        for item in (message.get("metadata") or {}).get("attachments") or []:
            artifact = self._editable_artifact_from_dict(item, message_id, author_role, create_time, export_file_re)
            if artifact:
                artifacts.append(artifact)
        for obj in self._walk_dicts(message):
            artifact = self._editable_artifact_from_dict(obj, message_id, author_role, create_time, export_file_re)
            if artifact:
                artifacts.append(artifact)
        return artifacts

    def _editable_artifact_from_dict(self, payload: dict[str, Any], message_id: str, author_role: str, create_time: float, export_file_re: re.Pattern[str]) -> EditableFileArtifact | None:
        if not ({"id", "file_id", "asset_pointer", "name", "file_name", "filename", "mime_type", "mimeType"} & set(payload.keys())):
            return None
        attachment_id = self._match_editable_file_id(str(payload.get("id") or ""))
        file_id = self._match_editable_file_id(str(payload.get("file_id") or ""))
        name = self._sanitize_editable_filename(str(payload.get("name") or payload.get("file_name") or payload.get("filename") or payload.get("title") or "").strip())
        mime_type = self._clean_editable_mime_type(payload.get("mime_type") or payload.get("mimeType") or "")
        for asset_id in EDITABLE_ASSET_POINTER_RE.findall(str(payload.get("asset_pointer") or "")):
            attachment_id = attachment_id or asset_id
            file_id = file_id or asset_id
        if not attachment_id or not file_id:
            ids = self._extract_editable_file_ids(json.dumps(payload, ensure_ascii=False))
            attachment_id = attachment_id or (ids[0] if ids else "")
            file_id = file_id or (ids[0] if ids else "")
        if not attachment_id and not file_id:
            return None
        return EditableFileArtifact(
            attachment_id=attachment_id,
            file_id=file_id,
            name=name,
            mime_type=mime_type,
            create_time=create_time,
            author_role=author_role,
            sandbox_path=(self._extract_editable_export_paths(payload, export_file_re) or [""])[0],
            message_id=message_id,
        )

    def _pick_editable_target_artifacts(self, artifacts: list[EditableFileArtifact], primary_suffixes: tuple[str, ...], primary_mime_types: set[str], primary_mime_keywords: tuple[str, ...]) -> list[EditableFileArtifact]:
        primary = self._best_editable_artifact(
            [item for item in artifacts if self._looks_like_editable_primary(item, primary_suffixes, primary_mime_types, primary_mime_keywords)]
        )
        zip_item = self._best_editable_artifact([item for item in artifacts if self._looks_like_editable_zip(item)])
        return [primary, zip_item] if primary and zip_item else []

    @staticmethod
    def _best_editable_artifact(artifacts: list[EditableFileArtifact]) -> EditableFileArtifact | None:
        if not artifacts:
            return None
        return max(
            artifacts,
            key=lambda item: (
                1 if (item.attachment_id or item.file_id) else 0,
                1 if item.sandbox_path else 0,
                item.create_time,
            ),
        )

    def _download_editable_artifact(
        self,
        conversation_id: str,
        artifact: EditableFileArtifact,
        output_dir: Path,
        primary_mime_types: set[str],
        primary_mime_keywords: tuple[str, ...],
        primary_default_extension: str,
    ) -> Path:
        download_url = self._resolve_editable_download_url_with_retry(conversation_id, artifact)
        if not download_url:
            raise RuntimeError(f"download url not found for artifact: {artifact}")
        response = self._request("GET", download_url, timeout=300)
        ensure_ok(response, "artifact_download")
        content_type = self._clean_editable_mime_type(response.headers.get("Content-Type") or artifact.mime_type)
        file_name = self._resolve_editable_output_name(artifact, response.url, response.headers.get("Content-Disposition"), content_type, primary_mime_types, primary_mime_keywords, primary_default_extension)
        target_path = self._unique_editable_path(output_dir / file_name)
        target_path.write_bytes(response.content)
        return target_path

    def _resolve_editable_download_url_with_retry(self, conversation_id: str, artifact: EditableFileArtifact) -> str:
        deadline = time.time() + EDITABLE_FILE_DOWNLOAD_TIMEOUT_SECS
        last_error = ""
        while True:
            try:
                url = self._resolve_editable_download_url(conversation_id, artifact)
                if url:
                    return url
            except Exception as exc:
                last_error = str(exc)
            if time.time() >= deadline:
                if last_error:
                    print(f"[chatgpt-pool] editable download url failed: {last_error}", flush=True)
                return ""
            time.sleep(EDITABLE_FILE_DOWNLOAD_POLL_INTERVAL_SECS)

    def _resolve_editable_download_url(self, conversation_id: str, artifact: EditableFileArtifact) -> str:
        ids: list[str] = []
        for item in (artifact.attachment_id, artifact.file_id):
            if item and item not in ids:
                ids.append(item)
        if artifact.sandbox_path and artifact.message_id:
            path = f"/backend-api/conversation/{conversation_id}/interpreter/download"
            response = self._request(
                "GET",
                self.base_url + path,
                headers=self._editable_download_headers(path, conversation_id, "/backend-api/conversation/{conversation_id}/interpreter/download"),
                params={"message_id": artifact.message_id, "sandbox_path": artifact.sandbox_path},
                timeout=60,
            )
            if 200 <= response.status_code < 300:
                url = self._download_url_from_response(response)
                if url:
                    return url
        for attachment_id in ids:
            path = f"/backend-api/conversation/{conversation_id}/attachment/{attachment_id}/download"
            response = self._request(
                "GET",
                self.base_url + path,
                headers=self._editable_download_headers(path, conversation_id, "/backend-api/conversation/{conversation_id}/attachment/{attachment_id}/download"),
                timeout=60,
            )
            if 200 <= response.status_code < 300:
                url = self._download_url_from_response(response)
                if url:
                    return url
        for file_id in ids:
            path = f"/backend-api/files/download/{file_id}"
            response = self._request(
                "GET",
                self.base_url + path,
                headers=self._editable_download_headers(path, conversation_id, "/backend-api/files/download/{file_id}"),
                params={"post_id": "", "inline": "false"},
                timeout=60,
            )
            if 200 <= response.status_code < 300:
                url = self._download_url_from_response(response)
                if url:
                    return url
        for file_id in ids:
            path = f"/backend-api/files/{file_id}/download"
            response = self._request(
                "GET",
                self.base_url + path,
                headers=self._editable_download_headers(path, conversation_id, "/backend-api/files/download/{file_id}"),
                timeout=60,
            )
            if 200 <= response.status_code < 300:
                url = self._download_url_from_response(response)
                if url:
                    return url
        return ""

    def _editable_download_headers(self, path: str, conversation_id: str, route: str) -> dict[str, str]:
        headers = self._editable_browser_headers(path, conversation_id)
        headers["X-OpenAI-Target-Route"] = route
        return headers

    @staticmethod
    def _download_url_from_response(response: Any) -> str:
        try:
            payload = response.json()
        except Exception:
            payload = {}
        return str(payload.get("download_url") or payload.get("url") or "")

    def _resolve_editable_output_name(
        self,
        artifact: EditableFileArtifact,
        final_url: str,
        content_disposition: str | None,
        content_type: str,
        primary_mime_types: set[str],
        primary_mime_keywords: tuple[str, ...],
        primary_default_extension: str,
    ) -> str:
        file_name = self._sanitize_editable_filename(artifact.name)
        if not file_name and artifact.sandbox_path:
            file_name = self._sanitize_editable_filename(Path(artifact.sandbox_path).name)
        if not file_name:
            file_name = self._sanitize_editable_filename(self._editable_filename_from_content_disposition(content_disposition or ""))
        if not file_name:
            file_name = self._sanitize_editable_filename(Path(urlparse(final_url).path).name)
        extension = self._editable_extension_from_mime_type(content_type, primary_mime_types, primary_mime_keywords, primary_default_extension)
        return f"artifact{extension}" if not file_name else (file_name if Path(file_name).suffix else file_name + extension)

    def _find_editable_value(self, payload: Any, key: str) -> str:
        if isinstance(payload, str):
            match = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]+)"', payload)
            if match:
                return match.group(1)
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return ""
        if isinstance(payload, dict):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
            return next((found for item in payload.values() if (found := self._find_editable_value(item, key))), "")
        if isinstance(payload, list):
            return next((found for item in payload if (found := self._find_editable_value(item, key))), "")
        return ""

    def _extract_editable_file_ids(self, text: str) -> list[str]:
        values: list[str] = []
        for item in EDITABLE_ASSET_POINTER_RE.findall(text):
            if item not in values:
                values.append(item)
        for item in FILE_ID_RE.findall(text):
            if item not in values:
                values.append(item)
        return values

    @staticmethod
    def _match_editable_file_id(value: str) -> str:
        match = FILE_ID_RE.search(value)
        return match.group(1) if match else ""

    @staticmethod
    def _clean_editable_mime_type(value: Any) -> str:
        text = str(value or "").strip().lower()
        return text.split(";", 1)[0] if "/" in text else ""

    def _looks_like_editable_primary(self, artifact: EditableFileArtifact, primary_suffixes: tuple[str, ...], primary_mime_types: set[str], primary_mime_keywords: tuple[str, ...]) -> bool:
        path, name, mime = artifact.sandbox_path.lower(), artifact.name.lower(), artifact.mime_type
        return name.endswith(primary_suffixes) or path.endswith(primary_suffixes) or mime in primary_mime_types or any(keyword in mime for keyword in primary_mime_keywords)

    @staticmethod
    def _looks_like_editable_zip(artifact: EditableFileArtifact) -> bool:
        path, name, mime = artifact.sandbox_path.lower(), artifact.name.lower(), artifact.mime_type
        return name.endswith(".zip") or path.endswith(".zip") or mime in EDITABLE_ZIP_MIME_TYPES or mime.endswith("/zip")

    @staticmethod
    def _editable_extension_from_mime_type(mime_type: str, primary_mime_types: set[str], primary_mime_keywords: tuple[str, ...], primary_default_extension: str) -> str:
        if mime_type in primary_mime_types or any(keyword in mime_type for keyword in primary_mime_keywords):
            return primary_default_extension
        if mime_type in EDITABLE_ZIP_MIME_TYPES or mime_type.endswith("/zip"):
            return ".zip"
        return mimetypes.guess_extension(mime_type) or ""

    @staticmethod
    def _editable_filename_from_content_disposition(content_disposition: str) -> str:
        extended_match = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition, re.IGNORECASE)
        if extended_match:
            return unquote(extended_match.group(1)).strip()
        plain_match = re.search(r'filename="([^"]+)"', content_disposition, re.IGNORECASE)
        return plain_match.group(1).strip() if plain_match else ""

    @staticmethod
    def _sanitize_editable_filename(value: str) -> str:
        return Path(str(value or "").strip()).name.replace("\x00", "").strip()

    @staticmethod
    def _unique_editable_path(path: Path) -> Path:
        if not path.exists():
            return path
        for index in range(1, 1000):
            candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
            if not candidate.exists():
                return candidate
        raise RuntimeError(f"failed to allocate output path for {path}")

    @staticmethod
    def _merge_editable_artifact(current: EditableFileArtifact | None, latest: EditableFileArtifact) -> EditableFileArtifact:
        if current is None:
            return latest
        return EditableFileArtifact(
            attachment_id=latest.attachment_id or current.attachment_id,
            file_id=latest.file_id or current.file_id,
            name=latest.name or current.name,
            mime_type=latest.mime_type or current.mime_type,
            create_time=max(current.create_time, latest.create_time),
            author_role=latest.author_role or current.author_role,
            sandbox_path=latest.sandbox_path or current.sandbox_path,
            message_id=latest.message_id or current.message_id,
        )

    @staticmethod
    def _editable_message_text(message: Any) -> str:
        if not isinstance(message, dict):
            return ""
        content = message.get("content") or {}
        parts: list[str] = []
        if isinstance(content, dict):
            if isinstance(content.get("text"), str):
                parts.append(content["text"])
            for part in content.get("parts") or []:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict):
                    parts.extend(str(part.get(key) or "") for key in ("text", "asset_pointer", "model_set_context") if part.get(key))
        if isinstance(message.get("content"), str):
            parts.append(str(message["content"]))
        return "\n".join(part for part in parts if part).strip()

    @staticmethod
    def _extract_editable_export_paths(payload: Any, export_file_re: re.Pattern[str]) -> list[str]:
        if isinstance(payload, str):
            text = payload
        else:
            try:
                text = json.dumps(payload, ensure_ascii=False)
            except Exception:
                text = str(payload)
        values: list[str] = []
        for item in export_file_re.findall(text):
            path = str(item or "").strip()
            if path and path not in values:
                values.append(path)
        return values

    def _walk_dicts(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            return [payload, *(item for value in payload.values() for item in self._walk_dicts(value))]
        if isinstance(payload, list):
            return [item for value in payload for item in self._walk_dicts(value)]
        return []

    def _result_from_image_response(self, response: requests.Response, revised_prompt: str) -> dict[str, str]:
        request_started_at = time.time()
        result_timeout = (
            self._image_remaining_seconds()
            if self._image_deadline_monotonic is not None
            else max(60, self.timeout_seconds)
        )
        deadline = time.time() + result_timeout
        conversation_id = ""
        file_ids: list[str] = []
        sediment_ids: list[str] = []
        library_urls: list[str] = []
        message = ""
        try:
            try:
                for payload in self._iter_image_sse_payloads(response):
                    if payload == "[DONE]":
                        break
                    self._raise_if_image_limit_message(payload)
                    if self._image_deadline_monotonic is not None:
                        self._image_remaining_seconds()
                    if time.time() >= deadline:
                        raise UpstreamError(
                            "ChatGPT image generation timed out while reading stream: "
                            f"conversation_id={conversation_id or 'unknown'}"
                        )
                    conv, files, sediments = extract_ids(payload)
                    conversation_id = conv or conversation_id
                    add_unique(file_ids, [item for item in files if item != "file_upload"])
                    add_unique(sediment_ids, sediments)
                    try:
                        event = json.loads(payload)
                        self._raise_if_image_limit_message(event)
                        if isinstance(event, dict) and event.get("type") == "moderation":
                            moderation = event.get("moderation_response") or {}
                            if isinstance(moderation, dict) and moderation.get("blocked"):
                                message = "Image request was blocked by upstream moderation."
                    except Exception:
                        pass
            except requests.exceptions.RequestException as exc:
                if not conversation_id:
                    raise UpstreamError(
                        "ChatGPT image generation timed out before the stream produced a conversation id"
                    ) from exc
                print(
                    "[chatgpt-pool] image stream interrupted; falling back to conversation polling: "
                    f"conversation_id={conversation_id}; error={exc}",
                    flush=True,
                )
        finally:
            response.close()
        if message and not file_ids and not sediment_ids:
            raise UpstreamError(message)
        if conversation_id and not file_ids and not sediment_ids:
            settle_seconds = IMAGE_POLL_SETTLE_SECS
            if self._image_deadline_monotonic is not None:
                settle_seconds = min(settle_seconds, self._image_remaining_seconds())
            if settle_seconds > 0:
                time.sleep(settle_seconds)
        if conversation_id and not file_ids and not sediment_ids:
            try:
                file_ids, sediment_ids = self._poll_image_results(conversation_id, deadline=deadline)
            except UpstreamError as exc:
                if "finished without image output" not in str(exc).lower():
                    raise
                try:
                    library_urls = self._recent_image_library_urls_for_conversation(
                        conversation_id,
                        started_at=request_started_at,
                    )
                except Exception as library_exc:
                    print(
                        "[chatgpt-pool] image library fallback failed: "
                        f"conversation_id={conversation_id}; error={library_exc}",
                        flush=True,
                    )
                    library_urls = []
                if not library_urls:
                    raise
        if self._image_deadline_monotonic is not None:
            self._image_remaining_seconds()
        urls = library_urls or self._resolve_image_urls(conversation_id, file_ids, sediment_ids)
        if not urls:
            raise UpstreamError(message or "upstream did not return image output")
        image_bytes = self._download_image(urls[0])
        if self._image_deadline_monotonic is not None:
            self._image_remaining_seconds()
        return {
            "b64_json": base64.b64encode(image_bytes).decode("ascii"),
            "revised_prompt": revised_prompt,
        }

    def generate_image(self, prompt: str, model: str = "gpt-image-2", size: str | None = None, quality: str = "auto") -> dict[str, str]:
        final_prompt = build_image_prompt(prompt, size, quality)
        if self._image_deadline_monotonic is not None:
            self._image_remaining_seconds()
        self._bootstrap()
        if self._image_deadline_monotonic is not None:
            self._image_remaining_seconds()
        requirements = self._requirements()
        if self._image_deadline_monotonic is not None:
            self._image_remaining_seconds()
        conduit = self._prepare_image_conversation(final_prompt, requirements, model)
        if self._image_deadline_monotonic is not None:
            self._image_remaining_seconds()
        response = self._start_image_generation(final_prompt, requirements, conduit, model)
        return self._result_from_image_response(response, prompt)

    def edit_image(
        self,
        prompt: str,
        base64_images: list[str],
        model: str = "gpt-image-2",
        size: str | None = None,
        quality: str = "auto",
        mask: str | None = None,
    ) -> dict[str, str]:
        images = [str(item or "").strip() for item in (base64_images or []) if str(item or "").strip()]
        if not images:
            raise ValueError("base64_images is empty")
        final_prompt = build_image_edit_prompt(prompt, size, quality, has_mask=bool(mask))
        uploaded = [self._upload_editable_base64_image(item, index) for index, item in enumerate(images, start=1)]
        if mask:
            uploaded.append(self._upload_editable_base64_image(mask, len(uploaded) + 1))
        self._bootstrap()
        requirements = self._requirements()
        conduit = self._prepare_image_conversation(
            final_prompt,
            requirements,
            model,
            [str(item.get("mime_type") or "image/png") for item in uploaded],
        )
        response = self._start_image_generation(final_prompt, requirements, conduit, model, uploaded)
        return self._result_from_image_response(response, prompt)
