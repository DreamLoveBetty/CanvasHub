"""EasyColab MiniMax-H3 task orchestration: validation, upload staging, polling and archiving."""
from __future__ import annotations

import base64
import json
import mimetypes
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from ..provider_easycolab_h3 import (
    MODEL_CATALOG,
    EasyColabH3Client,
    snap_h3_frames,
    snap_multiple_of_32,
    static_catalog_models,
)


TASK_TYPES = {"image": "easycolab-h3-image", "video": "easycolab-h3-video"}
TERMINAL = {"succeeded", "succeeded_no_telegram", "failed", "telegram_failed", "canceled"}
MAX_UPLOAD = 200 * 1024 * 1024
MAX_STAGED_TOTAL_BYTES = 450 * 1024 * 1024
MAX_OUTPUT = {"image": 64 * 1024 * 1024, "video": 512 * 1024 * 1024}


class EasyColabH3Service:
    def __init__(
        self,
        *,
        get_config,
        create_task,
        get_task,
        get_all_tasks,
        update_task,
        update_task_status,
        update_task_fields,
        daily_output_dir,
        send_document,
        probe_video_metadata=None,
    ):
        self.get_config = get_config
        self.create_task = create_task
        self.get_task = get_task
        self.get_all_tasks = get_all_tasks
        self.update_task = update_task
        self.update_task_status = update_task_status
        self.update_task_fields = update_task_fields
        self.daily_output_dir = daily_output_dir
        self.send_document = send_document
        self.probe_video_metadata = probe_video_metadata
        self._uploads: dict[str, tuple[bytes, str, str, float]] = {}
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(4)

    def _client(self, config: dict[str, Any] | None = None) -> EasyColabH3Client:
        cfg = config if config is not None else self.get_config()
        base_url = str(cfg.get("effective_base_url") or cfg.get("base_url") or "").strip()
        if not base_url:
            raise ValueError("请先在设置中填写 EasyColab 服务地址，或先在本地唤醒 EasyColab 会话")
        password = str(cfg.get("effective_password") or cfg.get("password") or "").strip()
        return EasyColabH3Client(base_url, password)

    def _prune_uploads_locked(self) -> None:
        now = time.time()
        self._uploads = {k: v for k, v in self._uploads.items() if v[3] > now}
        total = sum(len(item[0]) for item in self._uploads.values())
        if total <= MAX_STAGED_TOTAL_BYTES:
            return
        for key, _ in sorted(self._uploads.items(), key=lambda pair: pair[1][3]):
            removed = self._uploads.pop(key, None)
            if removed:
                total -= len(removed[0])
            if total <= MAX_STAGED_TOTAL_BYTES:
                break

    def catalog(self) -> dict[str, Any]:
        cfg = self.get_config()
        effective_url = str(cfg.get("effective_base_url") or cfg.get("base_url") or "").strip()
        configured = bool(effective_url)
        result: dict[str, Any] = {
            "ok": True,
            "configured": configured,
            "connected": False,
            "base_url": effective_url,
            "session_detected": bool(cfg.get("session_detected")),
            "auto_load_model": bool(cfg.get("auto_load_model", True)),
            "loaded_model_ids": [],
            "gpu": {},
            "connection_error": "",
            "models": static_catalog_models(),
        }
        if not configured:
            return result
        try:
            status = self._client(cfg).status()
            result["connected"] = True
            result["loaded_model_ids"] = list(status.get("loaded_model_ids") or [])
            result["gpu"] = {
                "gpu_name": str(status.get("gpu_name") or ""),
                "cuda_available": bool(status.get("cuda_available")),
                "vram_free_gb": float(status.get("vram_free_gb") or 0.0),
                "vram_total_gb": float(status.get("vram_total_gb") or 0.0),
                "vram_used_gb": float(status.get("vram_used_gb") or 0.0),
                "is_loading_vram": bool(status.get("is_loading_vram")),
                "is_downloading": bool(status.get("is_downloading")),
                "task_message": str(status.get("task_message") or "")[:200],
                "current_model": str(status.get("current_model") or ""),
            }
        except Exception as exc:
            result["connection_error"] = str(exc)[:300]
        return result

    def load_model(self, model_id: str) -> dict[str, Any]:
        mid = str(model_id or "").strip()
        if mid not in MODEL_CATALOG:
            raise ValueError("不支持的 EasyColab MiniMax H3 模型")
        cfg = self.get_config()
        status = self._client(cfg).load_model(mid)
        return {
            "ok": True,
            "model_id": mid,
            "model_loaded": bool(status.get("model_loaded")),
            "is_loading_vram": bool(status.get("is_loading_vram")),
            "loaded_model_ids": list(status.get("loaded_model_ids") or []),
            "message": str(status.get("task_message") or "已请求 EasyColab 加载模型到显存")[:200],
        }

    def upload(self, content: bytes, filename: str, mime: str) -> dict[str, Any]:
        if not content or len(content) > MAX_UPLOAD:
            raise ValueError("素材为空或超过 200 MB")
        kind = str(mime or "").split("/", 1)[0].lower()
        if kind not in {"image", "audio"}:
            raise ValueError("EasyColab H3 仅支持图像和音频素材")
        suffix = Path(filename or "").suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
            suffix = mimetypes.guess_extension(str(mime or "").split(";", 1)[0].strip()) or (
                ".png" if kind == "image" else ".wav"
            )
        clean_name = f"easycolab-h3-input-{uuid.uuid4().hex[:12]}{suffix}"
        token = uuid.uuid4().hex
        with self._lock:
            self._prune_uploads_locked()
            self._uploads[token] = (bytes(content), kind, clean_name, time.time() + 3600)
        return {"ok": True, "upload_token": token}

    def _consume_upload(self, token: str, kind: str) -> tuple[bytes, str]:
        with self._lock:
            self._prune_uploads_locked()
            record = self._uploads.get(str(token or ""))
        if not record or record[1] != kind or record[3] < time.time():
            raise ValueError(f"{kind} 素材已过期，请重新上传")
        return record[0], record[2]

    @staticmethod
    def _parse_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    @staticmethod
    def _parse_float(value: Any, default: float, minimum: float, maximum: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    def _prepare(self, data: dict[str, Any]) -> tuple[str, str, dict[str, Any], dict[str, Any], dict[str, Any]]:
        if not isinstance(data, dict):
            raise ValueError("请求必须为对象")
        model_id = str(data.get("model_id") or "").strip()
        spec = MODEL_CATALOG.get(model_id)
        if not spec:
            raise ValueError("请选择有效的 EasyColab MiniMax H3 模型")
        kind = str(spec["kind"])
        req_kind = str(data.get("kind") or "").strip()
        if req_kind and req_kind not in TASK_TYPES:
            raise ValueError("仅支持 EasyColab H3 图像或视频任务")
        prompt = str(data.get("prompt") or "").strip()
        if not prompt or len(prompt) > 12000:
            raise ValueError("请输入有效的提示词（不超过 12000 字）")

        incoming = data.get("parameters") if isinstance(data.get("parameters"), dict) else {}
        mode_map = {m["id"]: m for m in spec["modes"]}
        task_mode = str(incoming.get("task_mode") or data.get("task_mode") or spec["default_mode"]).strip()
        if task_mode not in mode_map:
            raise ValueError(f"当前模型不支持任务模式：{task_mode}")
        mode_spec = mode_map[task_mode]

        image_tokens = data.get("image_upload_tokens") or []
        audio_tokens = data.get("audio_upload_tokens") or []
        if not isinstance(image_tokens, list) or not isinstance(audio_tokens, list):
            raise ValueError("素材列表格式无效")

        max_images = int(mode_spec.get("max_images") or 0)
        max_audios = int(mode_spec.get("max_audios") or 0)
        if max_images > 0 and len(image_tokens) > max_images:
            raise ValueError(f"当前模式最多支持 {max_images} 张参考图")
        if max_audios > 0 and len(audio_tokens) > max_audios:
            raise ValueError(f"当前模式最多支持 {max_audios} 段参考音频")

        images_b64: list[str] = []
        for token in image_tokens[:max_images]:
            raw, _ = self._consume_upload(token, "image")
            images_b64.append(base64.b64encode(raw).decode("ascii"))

        audio_b64: str | None = None
        audio_name: str | None = None
        if max_audios > 0 and audio_tokens:
            raw_audio, clean_audio_name = self._consume_upload(audio_tokens[0], "audio")
            audio_b64 = base64.b64encode(raw_audio).decode("ascii")
            audio_name = clean_audio_name

        if task_mode == "fl2va" and not images_b64:
            raise ValueError("首尾帧模式需要至少连接 1 张参考图")
        if task_mode == "multiref" and not images_b64 and not audio_b64:
            raise ValueError("多图参考模式需要至少连接 1 张参考图或 1 段声纹音频")
        if task_mode == "i2i_edit" and not images_b64:
            raise ValueError("指令修图模式需要至少连接 1 张参考图")

        defaults = spec["defaults"]
        max_dim = 5472 if kind == "image" else 1920
        min_dim = 512 if kind == "image" else 256
        width = snap_multiple_of_32(
            incoming.get("width", defaults["width"]), default=defaults["width"], minimum=min_dim, maximum=max_dim
        )
        height = snap_multiple_of_32(
            incoming.get("height", defaults["height"]), default=defaults["height"], minimum=min_dim, maximum=max_dim
        )
        batch_count = self._parse_int(incoming.get("batch_count", defaults.get("batch_count", 1)), 1, 1, 4)

        raw_seed = incoming.get("seed", defaults.get("seed", -1))
        try:
            seed = int(raw_seed)
        except (TypeError, ValueError):
            seed = -1
        randomize_seed = seed < 0

        payload: dict[str, Any] = {
            "model_id": model_id,
            "task_mode": task_mode,
            "visual_prompt": prompt,
            "width": width,
            "height": height,
            "seed": 42 if randomize_seed else max(0, min(2**31 - 1, seed)),
            "randomize_seed": randomize_seed,
            "batch_count": batch_count,
        }

        public_params: dict[str, Any] = {
            "task_mode": task_mode,
            "width": width,
            "height": height,
            "seed": seed,
            "batch_count": batch_count,
        }

        if kind == "video":
            num_frames = snap_h3_frames(incoming.get("num_frames", defaults.get("num_frames", 124)))
            steps_cfg = spec.get("steps_range") or {"min": 4, "max": 60}
            steps = self._parse_int(
                incoming.get("num_inference_steps", defaults["num_inference_steps"]),
                defaults["num_inference_steps"],
                int(steps_cfg.get("min", 4)),
                int(steps_cfg.get("max", 60)),
            )
            fps = self._parse_int(incoming.get("fps", defaults.get("fps", 24)), 24, 12, 60)
            soundscape = str(incoming.get("soundscape_prompt") or "").strip()[:2000]
            music = str(incoming.get("music_prompt") or "").strip()[:2000]
            payload.update({
                "num_frames": num_frames,
                "num_inference_steps": steps,
                "fps": fps,
                "soundscape_prompt": soundscape,
                "music_prompt": music,
            })
            public_params.update({
                "num_frames": num_frames,
                "frame_count": num_frames,
                "num_inference_steps": steps,
                "fps": fps,
            })
            if soundscape:
                public_params["soundscape_prompt"] = soundscape
            if music:
                public_params["music_prompt"] = music

            if spec.get("supports_negative"):
                negative = str(data.get("negative_prompt") or incoming.get("negative_prompt") or "").strip()[:4000]
                if negative:
                    payload["negative_prompt"] = negative
                    public_params["negative_prompt"] = negative

            if spec.get("supports_ref_image_size"):
                ref_size = str(incoming.get("ref_image_size") or defaults.get("ref_image_size", "match")).strip()
                if ref_size not in {"match", "max"}:
                    ref_size = "match"
                payload["ref_image_size"] = ref_size
                public_params["ref_image_size"] = ref_size

            if spec.get("supports_corrector"):
                corr_enabled = bool(incoming.get("corrector_enabled", defaults.get("corrector_enabled", True)))
                corr_strength = self._parse_float(
                    incoming.get("corrector_strength", defaults.get("corrector_strength", 1.0)), 1.0, 0.0, 2.0
                )
                corr_budget = self._parse_float(
                    incoming.get("corrector_budget_fraction", defaults.get("corrector_budget_fraction", 0.5)),
                    0.5,
                    0.0,
                    1.0,
                )
                corr_start = self._parse_int(
                    incoming.get("corrector_start_step", defaults.get("corrector_start_step", 0)), 0, 0, steps
                )
                raw_end = incoming.get("corrector_end_step", defaults.get("corrector_end_step", -1))
                try:
                    corr_end = int(raw_end)
                except (TypeError, ValueError):
                    corr_end = -1
                if corr_end < -1:
                    corr_end = -1
                elif corr_end > steps:
                    corr_end = steps
                payload.update({
                    "corrector_enabled": corr_enabled,
                    "corrector_strength": corr_strength,
                    "corrector_budget_fraction": corr_budget,
                    "corrector_start_step": corr_start,
                    "corrector_end_step": corr_end,
                })
                public_params.update({
                    "corrector_enabled": corr_enabled,
                    "corrector_strength": corr_strength,
                    "corrector_budget_fraction": corr_budget,
                    "corrector_start_step": corr_start,
                    "corrector_end_step": corr_end,
                })
        else:
            payload["num_inference_steps"] = 6
            public_params["num_inference_steps"] = 6

        if task_mode == "multiref":
            if images_b64:
                payload["ref_images_base64"] = images_b64
                public_params["reference_image_count"] = len(images_b64)
            if audio_b64:
                payload["ref_audio_base64"] = audio_b64
                payload["ref_audio_filename"] = audio_name or "voice_seed.wav"
                public_params["reference_audio_attached"] = True
        elif task_mode in {"fl2va", "i2i_edit"}:
            if len(images_b64) >= 1:
                payload["first_frame_base64"] = images_b64[0]
            if len(images_b64) >= 2:
                payload["last_frame_base64"] = images_b64[1]
            if images_b64:
                public_params["reference_image_count"] = len(images_b64)

        return kind, prompt, spec, payload, public_params

    def _spawn(self, task_id: str, body: dict[str, Any] | None) -> None:
        def work() -> None:
            try:
                self.run(task_id, body)
            finally:
                self._slots.release()

        threading.Thread(target=work, name=f"easycolab-h3-{task_id[-8:]}", daemon=True).start()

    def submit(self, data: dict[str, Any]) -> dict[str, Any]:
        cfg = self.get_config()
        if not str(cfg.get("effective_base_url") or cfg.get("base_url") or "").strip():
            raise ValueError("请先在设置中填写 EasyColab 服务地址，或先唤醒 EasyColab 会话")
        kind, prompt, spec, body, public_params = self._prepare(data)
        if not self._slots.acquire(blocking=False):
            raise RuntimeError("EasyColab H3 并发任务已满，请稍后再试")
        local_id = "easycolab_h3_" + uuid.uuid4().hex
        params: dict[str, Any] = {
            "provider": "easycolab_h3",
            "kind": kind,
            "model_id": spec["id"],
            "model_label": spec["label"],
            "parameters": public_params,
            "width": public_params.get("width"),
            "height": public_params.get("height"),
            "fps": public_params.get("fps"),
            "frame_count": public_params.get("frame_count"),
            "telegram_enabled": data.get("telegram_enabled") is True,
        }
        if public_params.get("negative_prompt"):
            params["negative_prompt"] = public_params["negative_prompt"]
        if data.get("auto_sleep") is True or (isinstance(data.get("parameters"), dict) and data["parameters"].get("auto_sleep") is True):
            params["auto_sleep"] = True
        try:
            self.create_task(local_id, prompt, params, status="queued", task_type=TASK_TYPES[kind])
            self._spawn(local_id, body)
        except Exception:
            self._slots.release()
            raise
        return {"ok": True, "task_id": local_id, "status": "queued", "type": TASK_TYPES[kind]}

    def _store_remote_job(self, task_id: str, remote_job_id: str) -> None:
        task = self.get_task(task_id) or {}
        params = dict(task.get("params") or {})
        params["remote_job_id"] = remote_job_id
        self.update_task_fields(task_id, params=json.dumps(params, ensure_ascii=False))

    def _ensure_model_loaded(
        self,
        task_id: str,
        client: EasyColabH3Client,
        model_id: str,
        *,
        auto_load: bool,
        deadline: float,
    ) -> None:
        status = client.status(model_id=model_id, touch=True)
        loaded_ids = list(status.get("loaded_model_ids") or [])
        if model_id in loaded_ids or bool(status.get("model_loaded")):
            return
        if not auto_load:
            raise RuntimeError(f"EasyColab 尚未加载模型 {model_id} 到显存，请先点击「加载模型」或开启自动加载")
        total_count = int(status.get("total_count") or 0)
        downloaded_count = int(status.get("downloaded_count") or 0)
        if total_count > 0 and downloaded_count < total_count:
            raise RuntimeError(
                f"EasyColab 尚未完成 {model_id} 权重下载（已就绪 {downloaded_count}/{total_count}），请先在 EasyColab 下载权重"
            )
        if not status.get("is_loading_vram"):
            self.update_task_status(
                task_id, "queued", f"正在请求 EasyColab 加载 {model_id} 到显存", stage="loading_model", progress=5
            )
            client.load_model(model_id)
        while time.monotonic() < deadline:
            if (self.get_task(task_id) or {}).get("status") == "canceled":
                return
            current = client.status(model_id=model_id, touch=True)
            if model_id in list(current.get("loaded_model_ids") or []) or bool(current.get("model_loaded")):
                return
            msg = str(current.get("task_message") or "正在加载模型到 EasyColab 显存")[:200]
            prog = int(max(5, min(20, round(float(current.get("task_progress") or 0.1) * 20))))
            self.update_task_status(task_id, "queued", msg, stage="loading_model", progress=prog)
            if not current.get("is_loading_vram"):
                raise RuntimeError(msg or f"EasyColab 未能将 {model_id} 加载到显存")
            time.sleep(3)
        raise RuntimeError("等待 EasyColab 加载模型到显存超时")

    @staticmethod
    def _result_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
        items = []
        for entry in payload.get("completed_videos") or []:
            if isinstance(entry, dict) and (entry.get("video_url") or entry.get("filename")):
                items.append(entry)
        if not items and (payload.get("video_url") or payload.get("filename")):
            items.append({
                "filename": payload.get("filename"),
                "video_url": payload.get("video_url") or f"/minimax_api/media/{payload.get('filename')}",
                "seed": payload.get("seed"),
            })
        return items

    @staticmethod
    def _extension(kind: str, content_type: str, url: str) -> str:
        clean_type = str(content_type or "").split(";", 1)[0].strip().lower()
        allowed = {
            "image": {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/avif": ".avif"},
            "video": {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm"},
        }[kind]
        if clean_type in allowed:
            return allowed[clean_type]
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix in allowed.values():
            return suffix
        return ".png" if kind == "image" else ".mp4"

    @staticmethod
    def _sidecar_text(task: dict[str, Any]) -> str:
        lines = [str(task.get("prompt") or "").strip()]
        params = task.get("params") if isinstance(task.get("params"), dict) else {}
        inner = params.get("parameters") if isinstance(params.get("parameters"), dict) else {}
        if inner.get("soundscape_prompt"):
            lines.append(f"Soundscape: {inner['soundscape_prompt']}")
        if inner.get("music_prompt"):
            lines.append(f"Music: {inner['music_prompt']}")
        if params.get("negative_prompt"):
            lines.append(f"Negative: {params['negative_prompt']}")
        return "\n".join(part for part in lines if part) + "\n"

    def _archive(
        self,
        task_id: str,
        task: dict[str, Any],
        payload: dict[str, Any],
        client: EasyColabH3Client,
    ) -> list[Path]:
        kind = str((task.get("params") or {}).get("kind") or "video")
        items = self._result_items(payload)
        if not items:
            raise RuntimeError("EasyColab 任务已完成但未返回输出文件")
        folder = self.daily_output_dir()
        folder.mkdir(parents=True, exist_ok=True)
        sidecar = self._sidecar_text(task)
        paths: list[Path] = []
        for index, item in enumerate(items[:8], 1):
            media_ref = str(item.get("video_url") or item.get("filename") or "").strip()
            content, mime, resolved = client.download_media(media_ref, MAX_OUTPUT[kind])
            ext = self._extension(kind, mime, resolved)
            path = folder / f"easycolab_h3_{task_id}_{index}{ext}"
            temp = path.with_suffix(path.suffix + ".part")
            temp.write_bytes(content)
            temp.replace(path)
            path.with_suffix(".txt").write_text(sidecar, encoding="utf-8")
            paths.append(path)
        return paths

    def _update_video_metadata(self, task_id: str, primary_path: Path, payload: dict[str, Any]) -> None:
        task = self.get_task(task_id) or {}
        params = dict(task.get("params") or {})
        if payload.get("seed") is not None:
            params["seed"] = payload.get("seed")
        if payload.get("elapsed") is not None:
            params["elapsed_seconds"] = payload.get("elapsed")
        if callable(self.probe_video_metadata):
            try:
                meta = self.probe_video_metadata(primary_path) or {}
                for key in ("width", "height", "fps", "duration_seconds", "video_size_bytes"):
                    if meta.get(key) not in (None, "", 0):
                        params[key] = meta[key]
            except Exception:
                pass
        self.update_task_fields(task_id, params=json.dumps(params, ensure_ascii=False))

    def run(self, task_id: str, body: dict[str, Any] | None = None) -> None:
        try:
            task = self.get_task(task_id)
            if not task or task.get("status") in TERMINAL:
                return
            cfg = self.get_config()
            client = self._client(cfg)
            timeout_seconds = int(cfg.get("task_timeout_seconds") or 3600)
            deadline = time.monotonic() + timeout_seconds
            remote_job_id = str((task.get("params") or {}).get("remote_job_id") or "").strip()

            if not remote_job_id:
                if body is None:
                    raise RuntimeError("服务重启时 EasyColab 提交结果未确认，请重新提交任务")
                model_id = str(body.get("model_id") or "")
                self._ensure_model_loaded(
                    task_id,
                    client,
                    model_id,
                    auto_load=bool(cfg.get("auto_load_model", True)),
                    deadline=deadline,
                )
                if (self.get_task(task_id) or {}).get("status") == "canceled":
                    return
                self.update_task_status(task_id, "queued", "正在提交到 EasyColab", stage="submitting", progress=22)
                submitted = client.generate(body)
                remote_job_id = str(submitted["job_id"]).strip()
                self._store_remote_job(task_id, remote_job_id)

            failures = 0
            while time.monotonic() < deadline:
                if (self.get_task(task_id) or {}).get("status") == "canceled":
                    try:
                        client.cancel()
                    except Exception:
                        pass
                    return
                try:
                    result = client.job_status(remote_job_id)
                    failures = 0
                except (requests.RequestException, RuntimeError):
                    failures += 1
                    if failures >= 6:
                        raise RuntimeError("EasyColab 任务状态连续查询失败，请检查 Colab 连接")
                    time.sleep(3)
                    continue

                state = str(result.get("status") or "").lower()
                if state in {"failed", "error", "canceled", "cancelled"}:
                    raise RuntimeError(str(result.get("message") or "EasyColab 生成失败")[:300])

                if state == "completed":
                    self.update_task_status(
                        task_id, "queued", "正在下载并归档 EasyColab 原始结果", stage="archiving", progress=94
                    )
                    task = self.get_task(task_id) or task
                    paths = self._archive(task_id, task, result, client)
                    if (self.get_task(task_id) or {}).get("status") == "canceled":
                        return
                    if (task.get("params") or {}).get("kind") == "video":
                        self._update_video_metadata(task_id, paths[0], result)
                    names = [p.name for p in paths]
                    self.update_task(
                        task_id,
                        "succeeded_no_telegram",
                        result_file=names[0],
                        result_files=json.dumps(names, ensure_ascii=False),
                        stage="done",
                        progress=100,
                        progress_text="EasyColab MiniMax H3 生成完成，原始文件已归档",
                    )
                    if (task.get("params") or {}).get("telegram_enabled"):
                        try:
                            label = (task.get("params") or {}).get("model_label", "MiniMax H3")
                            for path in paths:
                                self.send_document(path, f"EasyColab · {label}"[:100])
                            self.update_task(
                                task_id,
                                "succeeded",
                                result_file=names[0],
                                stage="done",
                                progress_text="EasyColab MiniMax H3 生成完成，已发送 Telegram",
                            )
                        except Exception as exc:
                            self.update_task(
                                task_id,
                                "telegram_failed",
                                result_file=names[0],
                                error=f"结果已归档，Telegram 发送失败：{exc}",
                                stage="telegram",
                            )
                    if (task.get("params") or {}).get("auto_sleep"):
                        try:
                            client.disconnect()
                        except Exception:
                            pass
                    return

                raw_progress = float(result.get("progress") or 0.0)
                pct = int(max(10, min(92, round(raw_progress * 90 if raw_progress <= 1.0 else raw_progress))))
                msg = str(result.get("message") or "EasyColab MiniMax H3 生成中")[:200]
                self.update_task_status(task_id, "queued", msg, stage=state or "running", progress=pct)
                time.sleep(2.5)

            raise RuntimeError("EasyColab 任务等待超时，请检查 Colab 运行状态")
        except Exception as exc:
            if (self.get_task(task_id) or {}).get("status") != "canceled":
                message = str(exc)[:400] or "EasyColab MiniMax H3 任务失败"
                self.update_task(
                    task_id, "failed", error=message, stage="failed", progress_text=message, progress=100
                )

    def recover(self) -> None:
        """Resume known EasyColab remote jobs; never replay unconfirmed submissions."""
        pending: list[str] = []
        for task in self.get_all_tasks(limit=5000):
            if task.get("type") not in TASK_TYPES.values() or task.get("status") in TERMINAL:
                continue
            remote_job_id = str((task.get("params") or {}).get("remote_job_id") or "").strip()
            if not remote_job_id:
                self.update_task(
                    task["task_id"], "failed", error="服务重启前未确认 EasyColab 任务 ID，请重新提交"
                )
            else:
                pending.append(task["task_id"])
        for index in range(min(4, len(pending))):
            batch = pending[index::4]
            threading.Thread(
                target=lambda ids=batch: [self.run(tid) for tid in ids],
                name=f"easycolab-h3-recover-{index}",
                daemon=True,
            ).start()
