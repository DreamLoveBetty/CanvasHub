from __future__ import annotations

import base64
import json
import mimetypes
import re
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urljoin, urlparse

import requests
from PIL import Image

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
EDITABLE_FILE_PPT_PROMPT = """我需要你根据用户的需求，来制作一个可以编辑的PPT，你可以使用Agent来做，你不要再继续询问用户问题，内容风格、版式、配色、内容结构和页面信息你可以自行补充并直接执行。整体的流程如下：
1. 用生图的方式，帮我生成一个精美的产品介绍ppt，5-6个页面
2. 帮我把以上涉及到的所有图像和形状素材拆分成单独png，每个素材单独一张图片，不要有遗漏，让我可以直接在ppt里拼接素材还原，不要文字
3. 利用以上所有图片和形状素材，帮我还原你第一次生成的展示ppt，我需要是可编辑的ppt格式，主要部分需要你单独还原插入，文字需要可以编辑
最后只需要给我生成一个PPT文件，以及生成中遇到的各种素材压缩包zip文件就行。"""
EDITABLE_FILE_PSD_PROMPT = "帮我生成这个图像，把这张海报分成若干图像，包括背景图，每个元素不要改位置，这样子我可以直接在 平时里无需拖动，底色为白色，不要伪透明底。再帮我将以上拆分的图像拼合成一个psd文件，去除白色底，不要改变每个图层的相应位置，保留每个元素所在图层的相应位置，保留每个元素的图层，最后只需要给我输出psd文件，以及每个图层的zip文件"
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
    def __init__(self, access_token: str, timeout_seconds: int = 420):
        # Lightweight legacy account-pool transport: keep the Web request surface
        # small and stable. Do not mix browser cookies, sec-ch hints, proxy/TLS
        # impersonation, or per-account browser profile data into this HTTP path.
        self.base_url = "https://chatgpt.com"
        self.access_token = access_token
        self.timeout_seconds = max(60, int(timeout_seconds or 420))
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
        for attempt in range(1, NETWORK_RETRY_ATTEMPTS + 1):
            try:
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
                time.sleep(delay)
        if last_error:
            raise last_error
        raise RuntimeError("request failed without response")

    def _bootstrap(self) -> None:
        response = self._request("GET", self.base_url + "/", timeout=30)
        ensure_ok(response, "bootstrap")
        self.pow_script_sources, self.pow_data_build = parse_pow_resources(response.text)

    def _requirements(self) -> Requirements:
        path = "/backend-api/sentinel/chat-requirements"
        body = {"p": build_legacy_requirements_token(USER_AGENT, self.pow_script_sources, self.pow_data_build)}
        response = self.session.post(
            self.base_url + path,
            headers=self._headers(path, {"Content-Type": "application/json"}),
            json=body,
            timeout=30,
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
        return "gpt-5-3" if str(model or "gpt-image-2") == "gpt-image-2" else "auto"

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
        response = self.session.post(self.base_url + path, headers=self._image_headers(path, requirements), json=payload, timeout=60)
        ensure_ok(response, path)
        return str(response.json().get("conduit_token") or "")

    def _start_image_generation(
        self,
        prompt: str,
        requirements: Requirements,
        conduit_token: str,
        model: str,
        uploaded: list[dict[str, Any]] | None = None,
    ) -> requests.Response:
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
        return response

    def _image_stream_timeout(self) -> tuple[float, float]:
        return (
            IMAGE_STREAM_CONNECT_TIMEOUT_SECS,
            max(30.0, min(float(self.timeout_seconds), IMAGE_STREAM_READ_TIMEOUT_SECS)),
        )

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
        local_deadline = time.time() + max(60, self.timeout_seconds)
        deadline_at = min(float(deadline), local_deadline) if deadline is not None else local_deadline
        file_ids: list[str] = []
        sediment_ids: list[str] = []
        poll_count = 0
        last_summary = "not-polled"
        last_log_at = 0.0
        while time.time() < deadline_at:
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
            time.sleep(5)
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
            try:
                url = self._download_url_for_file(file_id)
            except Exception:
                continue
            if url:
                urls.append(url)
        if urls:
            return urls
        for sediment_id in sediment_ids:
            try:
                url = self._download_url_for_attachment(conversation_id, sediment_id)
            except Exception:
                continue
            if url:
                urls.append(url)
        if urls:
            return urls
        for sediment_id in sediment_ids:
            try:
                url = self._download_url_for_file(sediment_id)
            except Exception:
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
        response = self._request("GET", url, timeout=120)
        ensure_ok(response, "image_download")
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
        return self._export_editable_file_zip(
            base64_images,
            self._editable_prompt(EDITABLE_FILE_PSD_PROMPT, prompt),
            output_dir,
            primary_label="psd",
            primary_suffixes=(".psd",),
            primary_mime_types=EDITABLE_PSD_MIME_TYPES,
            primary_mime_keywords=("photoshop",),
            primary_default_extension=".psd",
            export_file_re=EDITABLE_PSD_EXPORT_FILE_RE,
            timeout_secs=timeout_secs,
            poll_interval_secs=poll_interval_secs,
        )

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

    def _run_editable_conversation(self, prompt: str, uploaded: list[dict[str, Any]], conduit_token: str) -> str:
        self._bootstrap()
        requirements = self._requirements()
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
                "developer_mode_connector_ids": [],
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
            for payload in iter_sse_payloads(response):
                if payload == "[DONE]":
                    break
                conversation_id = conversation_id or self._find_editable_value(payload, "conversation_id")
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
            except Exception as exc:
                print(f"[chatgpt-pool] editable poll failed: {exc}", flush=True)
            time.sleep(poll_interval_secs)
        raise RuntimeError(f"timed out waiting for {primary_label}/zip outputs")

    def _get_editable_conversation_detail(self, conversation_id: str) -> dict[str, Any]:
        path = f"/backend-api/conversation/{conversation_id}"
        response = self._request("GET", self.base_url + path, headers=self._editable_conversation_document_headers(path, conversation_id), timeout=60)
        ensure_ok(response, path)
        return response.json()

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
        deadline = time.time() + max(60, self.timeout_seconds)
        conversation_id = ""
        file_ids: list[str] = []
        sediment_ids: list[str] = []
        library_urls: list[str] = []
        message = ""
        try:
            try:
                for payload in iter_sse_payloads(response):
                    if payload == "[DONE]":
                        break
                    self._raise_if_image_limit_message(payload)
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
        if conversation_id and not file_ids and not sediment_ids:
            time.sleep(IMAGE_POLL_SETTLE_SECS)
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
        urls = library_urls or self._resolve_image_urls(conversation_id, file_ids, sediment_ids)
        if not urls:
            raise UpstreamError(message or "upstream did not return image output")
        image_bytes = self._download_image(urls[0])
        return {
            "b64_json": base64.b64encode(image_bytes).decode("ascii"),
            "revised_prompt": revised_prompt,
        }

    def generate_image(self, prompt: str, model: str = "gpt-image-2", size: str | None = None, quality: str = "auto") -> dict[str, str]:
        final_prompt = build_image_prompt(prompt, size, quality)
        self._bootstrap()
        requirements = self._requirements()
        conduit = self._prepare_image_conversation(final_prompt, requirements, model)
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
