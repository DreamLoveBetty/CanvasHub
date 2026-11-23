"""EasyColab MiniMax-H3 HTTP client and static model catalog.

No Canvas, database, or local storage dependency belongs in this module.
"""
from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import requests


H3_FRAME_PRESETS = (
    {"value": 56, "label": "56 帧 · ~2.3 秒"},
    {"value": 73, "label": "73 帧 · ~3.0 秒"},
    {"value": 90, "label": "90 帧 · ~3.8 秒 (4s)"},
    {"value": 124, "label": "124 帧 · ~5.2 秒 (5s)"},
    {"value": 192, "label": "192 帧 · ~8.0 秒 (8s)"},
    {"value": 243, "label": "243 帧 · ~10.1 秒 (10s)"},
    {"value": 294, "label": "294 帧 · ~12.3 秒 (12s)"},
    {"value": 362, "label": "362 帧 · ~15.1 秒 (15s)"},
)

VIDEO_SIZE_PRESETS = (
    {"value": "1056x608", "label": "1056×608 · 16:9 H3 黄金画幅", "width": 1056, "height": 608},
    {"value": "832x480", "label": "832×480 · 16:9 横屏标准", "width": 832, "height": 480},
    {"value": "1280x720", "label": "1280×720 · 16:9 720P 高清", "width": 1280, "height": 720},
    {"value": "1344x768", "label": "1344×768 · 16:9 电影宽屏", "width": 1344, "height": 768},
    {"value": "480x832", "label": "480×832 · 9:16 竖屏标准", "width": 480, "height": 832},
    {"value": "608x1056", "label": "608×1056 · 9:16 H3 竖屏", "width": 608, "height": 1056},
    {"value": "720x1280", "label": "720×1280 · 9:16 720P 竖屏", "width": 720, "height": 1280},
    {"value": "640x640", "label": "640×640 · 1:1 方形", "width": 640, "height": 640},
)

IMAGE_SIZE_PRESETS = (
    {"value": "2048x2048", "label": "2048×2048 · 1:1 4MP 超清推荐", "width": 2048, "height": 2048},
    {"value": "4096x4096", "label": "4096×4096 · 1:1 16MP 原生 4K", "width": 4096, "height": 4096},
    {"value": "5472x3072", "label": "5472×3072 · 16:9 16MP 电影 4K", "width": 5472, "height": 3072},
    {"value": "3072x5472", "label": "3072×5472 · 9:16 16MP 竖版 4K", "width": 3072, "height": 5472},
    {"value": "4736x3552", "label": "4736×3552 · 4:3 16MP 商业 4K", "width": 4736, "height": 3552},
    {"value": "3552x4736", "label": "3552×4736 · 3:4 16MP 人像 4K", "width": 3552, "height": 4736},
    {"value": "1344x768", "label": "1344×768 · 16:9 快速预览", "width": 1344, "height": 768},
    {"value": "1024x1024", "label": "1024×1024 · 1:1 快速预览", "width": 1024, "height": 1024},
)

MODEL_CATALOG: dict[str, dict[str, Any]] = {
    "minimax_h3_10eros_max": {
        "id": "minimax_h3_10eros_max",
        "kind": "video",
        "label": "10Eros-Max (H3 无限制 · 8 步)",
        "short_label": "10Eros-Max",
        "repo_id": "TenStrip/10Eros-Max",
        "summary": "8 步极速无限制音视频，支持 1~9 张参考图 (<Picture 1..9>) 与声纹克隆 (<Audio 1>)",
        "default_mode": "multiref",
        "modes": [
            {"id": "multiref", "label": "多图 + 声纹参考", "max_images": 9, "max_audios": 1, "requires_media": True},
            {"id": "fl2va", "label": "首尾帧生视频", "max_images": 2, "max_audios": 0, "requires_media": True},
            {"id": "t2va", "label": "文生音视频", "max_images": 0, "max_audios": 0, "requires_media": False},
        ],
        "defaults": {
            "width": 1056,
            "height": 608,
            "num_frames": 124,
            "num_inference_steps": 8,
            "fps": 24,
            "ref_image_size": "match",
            "seed": -1,
            "batch_count": 1,
        },
        "steps_range": {"min": 4, "max": 20, "step": 1, "fixed": False},
        "supports_audio_ref": True,
        "supports_ref_image_size": True,
        "supports_corrector": False,
        "supports_negative": True,
        "supports_soundscape": True,
        "size_presets": list(VIDEO_SIZE_PRESETS),
        "frame_presets": list(H3_FRAME_PRESETS),
    },
    "minimax_h3_sulphur3": {
        "id": "minimax_h3_sulphur3",
        "kind": "video",
        "label": "Sulphur-3 (H3 无限制 · 修正器)",
        "short_label": "Sulphur-3",
        "repo_id": "SulphurAI/Sulphur-3",
        "summary": "20 步满血无限制主干 + s3_corrector 速度残差修正器，强化动作张力与画质",
        "default_mode": "t2va",
        "modes": [
            {"id": "t2va", "label": "文生有声视频", "max_images": 0, "max_audios": 0, "requires_media": False},
            {"id": "fl2va", "label": "首尾帧生视频", "max_images": 2, "max_audios": 0, "requires_media": True},
        ],
        "defaults": {
            "width": 1056,
            "height": 608,
            "num_frames": 124,
            "num_inference_steps": 20,
            "fps": 24,
            "corrector_enabled": True,
            "corrector_strength": 1.0,
            "corrector_budget_fraction": 0.5,
            "corrector_start_step": 0,
            "corrector_end_step": -1,
            "seed": -1,
            "batch_count": 1,
        },
        "steps_range": {"min": 8, "max": 40, "step": 1, "fixed": False},
        "supports_audio_ref": False,
        "supports_ref_image_size": False,
        "supports_corrector": True,
        "supports_negative": True,
        "supports_soundscape": True,
        "size_presets": list(VIDEO_SIZE_PRESETS),
        "frame_presets": list(H3_FRAME_PRESETS),
    },
    "minimax_h3": {
        "id": "minimax_h3",
        "kind": "video",
        "label": "MiniMax-H3 (33B BF16 原生)",
        "short_label": "MiniMax-H3",
        "repo_id": "MiniMaxAI/MiniMax-H3",
        "summary": "官方 33B BF16 原生满血音视频模型，支持文生音视频与首尾帧过渡",
        "default_mode": "t2va",
        "modes": [
            {"id": "t2va", "label": "文生音视频", "max_images": 0, "max_audios": 0, "requires_media": False},
            {"id": "fl2va", "label": "首尾帧生视频", "max_images": 2, "max_audios": 0, "requires_media": True},
        ],
        "defaults": {
            "width": 832,
            "height": 480,
            "num_frames": 124,
            "num_inference_steps": 35,
            "fps": 24,
            "seed": -1,
            "batch_count": 1,
        },
        "steps_range": {"min": 10, "max": 60, "step": 1, "fixed": False},
        "supports_audio_ref": False,
        "supports_ref_image_size": False,
        "supports_corrector": False,
        "supports_negative": True,
        "supports_soundscape": True,
        "size_presets": list(VIDEO_SIZE_PRESETS),
        "frame_presets": list(H3_FRAME_PRESETS),
    },
    "minimax_h3_image": {
        "id": "minimax_h3_image",
        "kind": "image",
        "label": "MiniMax-H3-Image (33B · 4K)",
        "short_label": "H3-Image 4K",
        "repo_id": "MiniMaxAI/MiniMax-H3-Image",
        "summary": "6 步 PDD 蒸馏原生 4K 文生图与 1~2 张参考图指令修图 (<Picture 1>/<Picture 2>)",
        "default_mode": "t2i",
        "modes": [
            {"id": "t2i", "label": "6 步原生 4K 文生图", "max_images": 0, "max_audios": 0, "requires_media": False},
            {"id": "i2i_edit", "label": "多参考图指令修图", "max_images": 2, "max_audios": 0, "requires_media": True},
        ],
        "defaults": {
            "width": 2048,
            "height": 2048,
            "num_inference_steps": 6,
            "seed": -1,
            "batch_count": 1,
        },
        "steps_range": {"min": 6, "max": 6, "step": 1, "fixed": True},
        "supports_audio_ref": False,
        "supports_ref_image_size": False,
        "supports_corrector": False,
        "supports_negative": False,
        "supports_soundscape": False,
        "size_presets": list(IMAGE_SIZE_PRESETS),
        "frame_presets": [],
    },
}


def static_catalog_models() -> dict[str, list[dict[str, Any]]]:
    models: dict[str, list[dict[str, Any]]] = {"image": [], "video": []}
    for spec in MODEL_CATALOG.values():
        models[spec["kind"]].append(json.loads(json.dumps(spec)))
    return models


def snap_h3_frames(num_frames: Any) -> int:
    """Snap MiniMax-H3 frame count to the valid 17k + 5 grid (22..362)."""
    try:
        n = int(num_frames)
    except (TypeError, ValueError):
        n = 124
    n = max(22, min(362, n))
    k = max(1, min(21, round((n - 5) / 17.0)))
    return 17 * k + 5


def snap_multiple_of_32(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        raw = int(value)
    except (TypeError, ValueError):
        raw = default
    clamped = max(minimum, min(maximum, raw))
    snapped = (clamped // 32) * 32
    return max(minimum, min(maximum, snapped))


def _validate_base_url(base_url: str) -> str:
    cleaned = str(base_url or "").strip().rstrip("/")
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("EasyColab 服务地址必须是有效的 http:// 或 https:// 地址")
    return cleaned


class EasyColabH3Client:
    """Thin HTTP client for EasyColab /minimax_api/* endpoints."""

    def __init__(self, base_url: str, password: str = "", *, timeout: int = 30):
        self.base_url = _validate_base_url(base_url)
        self.password = str(password or "").strip()
        self.timeout = max(5, int(timeout or 30))

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": "CanvasHub-EasyColab-H3/1.0"}
        if self.password:
            token = base64.b64encode(f"easycolab:{self.password}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        return headers

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = self._headers()
        kwargs: dict[str, Any] = {"headers": headers, "timeout": timeout or self.timeout}
        if payload is not None:
            headers["Content-Type"] = "application/json"
            kwargs["json"] = payload
        response = requests.request(method, url, **kwargs)
        try:
            body = response.json()
        except (ValueError, requests.exceptions.JSONDecodeError) as exc:
            if response.status_code == 401:
                raise RuntimeError("EasyColab 鉴权失败，请检查管理密码") from exc
            raise RuntimeError(f"EasyColab 返回了非 JSON 响应（HTTP {response.status_code}）") from exc
        if response.status_code == 401:
            raise RuntimeError("EasyColab 鉴权失败，请检查管理密码")
        if not response.ok:
            detail = ""
            if isinstance(body, dict):
                detail = str(body.get("detail") or body.get("message") or body.get("error") or "")[:300]
            raise RuntimeError(detail or f"EasyColab 请求失败（HTTP {response.status_code}）")
        if not isinstance(body, dict):
            raise RuntimeError("EasyColab 响应格式无效")
        return body

    def status(self, model_id: str | None = None, *, touch: bool = False) -> dict[str, Any]:
        params = []
        if model_id:
            params.append(f"model_id={quote(str(model_id), safe='')}")
        if touch:
            params.append("touch=1")
        query = f"?{'&'.join(params)}" if params else ""
        return self._request_json("GET", f"/minimax_api/status{query}", timeout=15)

    def load_model(
        self,
        model_id: str,
        *,
        precision_mode: str = "bf16",
        offload_mode: str = "disk",
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/minimax_api/load_model",
            payload={
                "model_id": model_id,
                "precision_mode": precision_mode,
                "offload_mode": offload_mode,
            },
            timeout=30,
        )

    def download_model(self, model_id: str) -> dict[str, Any]:
        return self._request_json(
            "POST",
            "/minimax_api/download_model",
            payload={"model_id": model_id},
            timeout=30,
        )

    def generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._request_json("POST", "/minimax_api/generate", payload=payload, timeout=120)
        if result.get("status") == "failed" or not result.get("job_id") or result.get("job_id") == "none":
            raise RuntimeError(str(result.get("message") or "EasyColab 拒绝了生成请求")[:300])
        return result

    def job_status(self, job_id: str) -> dict[str, Any]:
        safe_id = quote(str(job_id or "").strip(), safe="")
        if not safe_id:
            raise ValueError("缺少 EasyColab 任务 ID")
        return self._request_json("GET", f"/minimax_api/job/{safe_id}", timeout=20)

    def cancel(self) -> dict[str, Any]:
        return self._request_json("POST", "/minimax_api/cancel", payload={}, timeout=20)

    def disconnect(self) -> dict[str, Any]:
        return self._request_json("POST", "/minimax_api/disconnect", payload={}, timeout=30)

    def _resolve_media_url(self, media_path_or_url: str) -> str:
        raw = str(media_path_or_url or "").strip()
        if not raw:
            raise ValueError("缺少 EasyColab 输出媒体路径")
        base_parsed = urlparse(self.base_url)
        if raw.startswith(("http://", "https://")):
            target = urlparse(raw)
            if target.scheme != base_parsed.scheme or target.netloc != base_parsed.netloc:
                raise RuntimeError("拒绝下载非当前 EasyColab 服务来源的媒体文件")
            return raw
        if not raw.startswith("/"):
            raw = f"/minimax_api/media/{quote(raw, safe='')}"
        return urljoin(self.base_url + "/", raw.lstrip("/"))

    def download_media(self, media_path_or_url: str, max_bytes: int) -> tuple[bytes, str, str]:
        url = self._resolve_media_url(media_path_or_url)
        with requests.get(
            url,
            headers=self._headers(),
            stream=True,
            allow_redirects=False,
            timeout=(15, 300),
        ) as response:
            if response.status_code == 401:
                raise RuntimeError("EasyColab 鉴权失败，无法下载生成结果")
            if not response.ok:
                raise RuntimeError(f"EasyColab 媒体下载失败（HTTP {response.status_code}）")
            content_type = str(response.headers.get("Content-Type") or "application/octet-stream")
            chunks = []
            total = 0
            for chunk in response.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise RuntimeError("EasyColab 返回的媒体文件超过允许大小上限")
                chunks.append(chunk)
        content = b"".join(chunks)
        if not content:
            raise RuntimeError("EasyColab 返回了空的媒体文件")
        return content, content_type, url
