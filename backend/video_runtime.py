#!/usr/bin/env python3
"""MiniMax H3 Runtime discovery and connection helpers.

The main application only owns routing and health checks here. Model loading and
inference stay inside the independently deployed H3_Runtime_Server process.
"""

from __future__ import annotations

import copy
import ipaddress
import json
import os
import re
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import Any

import requests

from .app_config import get_video_inference_config, get_video_inference_public_config


FALLBACK_MAX_PIXELS = 1344 * 768
RUNTIME_JOB_ID_RE = re.compile(r"^h3_[A-Za-z0-9_-]{8,96}$")
FALLBACK_CAPABILITIES: dict[str, Any] = {
    "service": "minimax-h3-runtime",
    "version": "",
    "modes": {
        "image_to_video": {"files": ["first_frame?"], "model": "fl2va"},
        "reference_to_video": {
            "files": ["reference_images[]?", "reference_videos[]?", "reference_audios[]?"],
            "model": "ref2va",
        },
    },
    "constraints": {
        "fps": 24,
        "dimension_multiple": 32,
        "max_pixels": FALLBACK_MAX_PIXELS,
        "duration_seconds": {"min": 1, "max": 15},
        "frame_grid": "17k+5",
        "single_gpu_concurrency": 1,
    },
    "acceleration": {
        "default_mode": "first_block_cache",
        "modes": {
            "off": {"approximate": False, "experimental": False},
            "first_block_cache": {"approximate": True, "experimental": False},
            "sol_attn": {"approximate": True, "experimental": True},
            "combined": {"approximate": True, "experimental": True},
        },
        "parameters": {
            "first_block_cache_threshold": {
                "type": "number",
                "default": 0.08,
                "exclusive_minimum": 0,
                "maximum": 1,
            }
        },
    },
}


def _clean_error(error: Exception, maximum: int = 320) -> str:
    text = str(error or "").replace("\r", " ").replace("\n", " ").strip()
    return text[:maximum] or type(error).__name__


def _private_hostname(hostname: str) -> bool:
    host = str(hostname or "").strip().lower().rstrip(".")
    if not host:
        return False
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # Windows host names and private DNS labels commonly contain no dot.
        return "." not in host and all(part for part in host.split("-"))
    carrier_grade_nat = ipaddress.ip_network("100.64.0.0/10")
    return bool(address.is_loopback or address.is_private or address.is_link_local or address in carrier_grade_nat)


def _normalize_private_base_url(value: Any, service_name: str, *, allow_empty: bool = False) -> str:
    base_url = str(value or "").strip().rstrip("/")
    if not base_url and allow_empty:
        return ""
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{service_name}地址必须是完整的 http:// 或 https:// 地址")
    if parsed.username or parsed.password:
        raise ValueError(f"{service_name}地址不能包含用户名或密码")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise ValueError(f"{service_name}地址只能填写协议、主机和端口")
    if not _private_hostname(parsed.hostname):
        raise ValueError(f"{service_name}仅允许本机或局域网地址")
    return base_url


def normalize_runtime_base_url(value: Any, *, allow_empty: bool = False) -> str:
    return _normalize_private_base_url(value, "H3 Runtime ", allow_empty=allow_empty)


def normalize_supervisor_base_url(value: Any, *, allow_empty: bool = False) -> str:
    return _normalize_private_base_url(value, "H3 Supervisor ", allow_empty=allow_empty)


def _merged_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    config = copy.deepcopy(get_video_inference_config())
    data = overrides if isinstance(overrides, dict) else {}
    mode = str(data.get("runtime_mode") or "").strip().lower()
    if mode in {"auto", "local", "lan"}:
        config["runtime_mode"] = mode
    for section_name in ("local", "lan"):
        incoming = data.get(section_name) if isinstance(data.get(section_name), dict) else {}
        if incoming:
            config[section_name] = {**(config.get(section_name) or {}), **incoming}
    if "base_url" in data:
        target_section = "lan" if config.get("runtime_mode") == "lan" else "local"
        config[target_section]["base_url"] = data.get("base_url")
    if "timeout_seconds" in data:
        config["lan"]["connect_timeout_seconds"] = data.get("timeout_seconds")
    return config


def _runtime_candidates(config: dict[str, Any]) -> list[dict[str, Any]]:
    mode = str(config.get("runtime_mode") or "auto")
    local = config.get("local") if isinstance(config.get("local"), dict) else {}
    lan = config.get("lan") if isinstance(config.get("lan"), dict) else {}
    timeout = max(0.5, min(30.0, float(lan.get("connect_timeout_seconds") or 5)))
    candidates: list[dict[str, Any]] = []
    if mode in {"auto", "local"}:
        candidates.append({
            "mode": "local",
            "base_url": normalize_runtime_base_url(local.get("base_url")),
            "timeout_seconds": timeout,
        })
    if mode in {"auto", "lan"} and str(lan.get("base_url") or "").strip():
        candidates.append({
            "mode": "lan",
            "base_url": normalize_runtime_base_url(lan.get("base_url")),
            "timeout_seconds": timeout,
        })
    return candidates


def _new_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def collect_component_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or get_video_inference_config()
    local = cfg.get("local") if isinstance(cfg.get("local"), dict) else {}
    raw_path = str(local.get("component_dir") or "").strip()
    component_dir = Path(raw_path).expanduser() if raw_path else None
    exists = bool(component_dir and component_dir.is_dir())
    start_script = ""
    if exists:
        for name in ("start_server_hidden.ps1", "start_server.ps1", "run_server.cmd"):
            if (component_dir / name).is_file():
                start_script = name
                break
    return {
        "platform": "windows" if os.name == "nt" else ("macos" if os.sys.platform == "darwin" else os.sys.platform),
        "supported": os.name == "nt",
        "configured": bool(raw_path),
        "component_dir": raw_path,
        "exists": exists,
        "start_script": start_script,
        "startable": bool(os.name == "nt" and exists and start_script),
    }


def _probe_candidate(candidate: dict[str, Any], include_capabilities: bool = False) -> dict[str, Any]:
    started = time.perf_counter()
    timeout = min(float(candidate.get("timeout_seconds") or 5), 10.0)
    with _new_session() as session:
        health_response = session.get(f"{candidate['base_url']}/health", timeout=timeout)
        health_response.raise_for_status()
        health = health_response.json() if health_response.content else {}
        capability_data = None
        if include_capabilities:
            capability_response = session.get(f"{candidate['base_url']}/v1/capabilities", timeout=timeout)
            capability_response.raise_for_status()
            capability_data = capability_response.json() if capability_response.content else {}
    capability_service = capability_data.get("service", "") if isinstance(capability_data, dict) else ""
    capability_version = capability_data.get("version", "") if isinstance(capability_data, dict) else ""
    return {
        "mode": candidate["mode"],
        "base_url": candidate["base_url"],
        "online": True,
        "checked": True,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "service": str(health.get("service") or capability_service),
        "version": str(health.get("version") or capability_version),
        "models_ready": bool(health.get("models_ready")),
        "worker": health.get("worker") if isinstance(health.get("worker"), dict) else {},
        "capabilities": capability_data if isinstance(capability_data, dict) else None,
    }


def collect_runtime_status(*, probe: bool = True, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    config = _merged_config(overrides)
    public_config = get_video_inference_public_config() if not overrides else {
        **config,
        "lan": {
            **(config.get("lan") or {}),
            "api_key_configured": bool((config.get("lan") or {}).get("api_key")),
        },
    }
    if isinstance(public_config.get("lan"), dict):
        public_config["lan"].pop("api_key", None)
    component = collect_component_status(config)
    try:
        candidates = _runtime_candidates(config)
    except Exception as exc:
        return {
            "ok": True,
            "online": False,
            "checked": True,
            "runtime_mode": config.get("runtime_mode", "auto"),
            "component": component,
            "config": public_config,
            "error": _clean_error(exc),
            "message": _clean_error(exc),
        }
    if not candidates:
        return {
            "ok": True,
            "online": False,
            "checked": True,
            "runtime_mode": config.get("runtime_mode", "auto"),
            "component": component,
            "config": public_config,
            "message": "尚未配置可用的 H3 Runtime 地址",
        }
    if not probe:
        selected = candidates[0]
        return {
            "ok": True,
            "online": False,
            "checked": False,
            "runtime_mode": config.get("runtime_mode", "auto"),
            "selected_mode": selected["mode"],
            "base_url": selected["base_url"],
            "component": component,
            "config": public_config,
            "message": "尚未检测连接",
        }

    attempts: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            result = _probe_candidate(candidate)
            result.update({
                "ok": True,
                "runtime_mode": config.get("runtime_mode", "auto"),
                "selected_mode": candidate["mode"],
                "component": component,
                "config": public_config,
                "attempts": attempts,
                "message": "H3 Runtime 在线",
            })
            result.pop("capabilities", None)
            return result
        except Exception as exc:
            attempts.append({
                "mode": candidate["mode"],
                "base_url": candidate["base_url"],
                "error": _clean_error(exc),
            })
    return {
        "ok": True,
        "online": False,
        "checked": True,
        "runtime_mode": config.get("runtime_mode", "auto"),
        "selected_mode": candidates[0]["mode"],
        "base_url": candidates[0]["base_url"],
        "component": component,
        "config": public_config,
        "attempts": attempts,
        "error": attempts[-1]["error"] if attempts else "连接失败",
        "message": "H3 Runtime 离线",
    }


def collect_supervisor_status(*, probe: bool = True, base_url: Any = None) -> dict[str, Any]:
    config = get_video_inference_config()
    configured_url = config.get("manager_base_url") if base_url is None else base_url
    try:
        manager_base_url = normalize_supervisor_base_url(configured_url, allow_empty=True)
    except Exception as exc:
        return {
            "ok": True,
            "online": False,
            "checked": True,
            "configured": bool(str(configured_url or "").strip()),
            "base_url": "",
            "error": _clean_error(exc),
            "message": _clean_error(exc),
        }

    base_result = {
        "ok": True,
        "online": False,
        "checked": False,
        "configured": bool(manager_base_url),
        "base_url": manager_base_url,
        "manager_url": manager_base_url,
    }
    if not manager_base_url:
        return {**base_result, "message": "尚未配置 H3 Supervisor 管理台地址"}
    if not probe:
        return {**base_result, "message": "尚未检测管理台"}

    started = time.perf_counter()
    timeout = min(float((config.get("lan") or {}).get("connect_timeout_seconds") or 5), 10.0)
    try:
        with _new_session() as session:
            response = session.get(
                f"{manager_base_url}/api/supervisor/health",
                timeout=timeout,
                allow_redirects=False,
                headers={"Accept": "application/json"},
            )
            if response.status_code != 200:
                raise RuntimeError(f"Supervisor health 返回 HTTP {response.status_code}")
            if len(response.content) > 64 * 1024:
                raise RuntimeError("Supervisor health 响应过大")
            health = response.json() if response.content else {}
        if not isinstance(health, dict) or health.get("service") != "h3-runtime-supervisor" or health.get("ok") is not True:
            raise RuntimeError("目标地址未返回有效的 H3 Supervisor 健康信息")
        return {
            **base_result,
            "online": True,
            "checked": True,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "service": "h3-runtime-supervisor",
            "version": str(health.get("version") or "")[:64],
            "status": str(health.get("status") or "ok")[:32],
            "uptime_seconds": max(0.0, float(health.get("uptime_seconds") or 0)),
            "admin_initialized": health.get("admin_initialized") is True,
            "checked_at": str(health.get("checked_at") or "")[:64],
            "message": "H3 Supervisor 在线",
        }
    except Exception as exc:
        if isinstance(exc, requests.Timeout):
            error = "连接 H3 Supervisor 超时"
        elif isinstance(exc, requests.ConnectionError):
            error = "无法连接 H3 Supervisor"
        else:
            error = _clean_error(exc)
        return {
            **base_result,
            "checked": True,
            "error": error,
            "message": "H3 Supervisor 离线",
        }


def collect_runtime_capabilities() -> dict[str, Any]:
    config = get_video_inference_config()
    try:
        candidates = _runtime_candidates(config)
    except Exception as exc:
        candidates = []
        error = _clean_error(exc)
    else:
        error = ""
    attempts: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            result = _probe_candidate(candidate, include_capabilities=True)
            capabilities = result.get("capabilities") or copy.deepcopy(FALLBACK_CAPABILITIES)
            return {
                "ok": True,
                "runtime_online": True,
                "source": "runtime",
                "selected_mode": candidate["mode"],
                "base_url": candidate["base_url"],
                "latency_ms": result.get("latency_ms", 0),
                "capabilities": capabilities,
            }
        except Exception as exc:
            attempts.append({"mode": candidate["mode"], "error": _clean_error(exc)})
    return {
        "ok": True,
        "runtime_online": False,
        "source": "fallback",
        "capabilities": copy.deepcopy(FALLBACK_CAPABILITIES),
        "attempts": attempts,
        "error": error or (attempts[-1]["error"] if attempts else ""),
    }


def _runtime_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("error") or payload.get("message") or payload.get("detail")
        if detail:
            return str(detail)[:500]
    return str(response.text or response.reason or f"HTTP {response.status_code}").strip()[:500]


def _raise_runtime_response(response: requests.Response, action: str) -> None:
    if response.ok:
        return
    message = _runtime_error_message(response)
    raise RuntimeError(f"{action}失败（HTTP {response.status_code}）：{message}")


def _validated_runtime_job_id(job_id: Any) -> str:
    value = str(job_id or "").strip()
    if not RUNTIME_JOB_ID_RE.fullmatch(value):
        raise ValueError("H3 Runtime job_id 无效")
    return value


def _runtime_auth_key(config: dict[str, Any], mode: str) -> str:
    if mode == "lan":
        lan = config.get("lan") if isinstance(config.get("lan"), dict) else {}
        return str(lan.get("api_key") or "").strip()
    return read_local_runtime_api_key()


def _runtime_headers(target: dict[str, Any]) -> dict[str, str]:
    api_key = str(target.get("api_key") or "").strip()
    return {"X-H3-API-Key": api_key} if api_key else {}


def resolve_runtime_target() -> dict[str, Any]:
    """Resolve the configured live Runtime target for a generation request.

    The returned dictionary is server-private because it may contain an API key.
    """
    config = get_video_inference_config()
    candidates = _runtime_candidates(config)
    if not candidates:
        raise RuntimeError("尚未配置可用的 H3 Runtime 地址")
    attempts: list[str] = []
    for candidate in candidates:
        try:
            probe = _probe_candidate(candidate)
            return {
                **candidate,
                "api_key": _runtime_auth_key(config, candidate["mode"]),
                "service": probe.get("service", ""),
                "version": probe.get("version", ""),
            }
        except Exception as exc:
            attempts.append(f"{candidate['mode']}: {_clean_error(exc, 180)}")
    raise RuntimeError("H3 Runtime 离线：" + "；".join(attempts))


def submit_runtime_job(
    params: dict[str, Any],
    uploads: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Submit one job and return ``(safe_target, runtime_job)``.

    ``uploads`` values may be a single ``{filename, content, content_type}``
    dictionary or a list of those dictionaries. Duplicate multipart field names
    are intentionally preserved for reference inputs.
    """
    target = resolve_runtime_target()
    upload_map = uploads if isinstance(uploads, dict) else {}
    multipart: list[tuple[str, tuple[str, bytes, str]]] = []
    for field_name, raw_items in upload_map.items():
        items = raw_items if isinstance(raw_items, list) else [raw_items]
        for item in items:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, (bytes, bytearray)):
                continue
            filename = Path(str(item.get("filename") or "upload.bin")).name[:180] or "upload.bin"
            content_type = str(item.get("content_type") or "application/octet-stream")[:120]
            multipart.append((str(field_name), (filename, bytes(content), content_type)))

    data: dict[str, str] = {}
    for key, value in (params or {}).items():
        if value is None:
            continue
        if isinstance(value, bool):
            data[str(key)] = "true" if value else "false"
        elif isinstance(value, (dict, list)):
            data[str(key)] = json.dumps(value, ensure_ascii=False)
        else:
            data[str(key)] = str(value)

    timeout = max(10.0, min(600.0, float(target.get("timeout_seconds") or 5) * 20))
    try:
        with _new_session() as session:
            if multipart:
                response = session.post(
                    f"{target['base_url']}/v1/jobs",
                    data=data,
                    files=multipart,
                    headers=_runtime_headers(target),
                    timeout=(float(target.get("timeout_seconds") or 5), timeout),
                )
            else:
                response = session.post(
                    f"{target['base_url']}/v1/jobs",
                    json=params or {},
                    headers=_runtime_headers(target),
                    timeout=(float(target.get("timeout_seconds") or 5), timeout),
                )
        _raise_runtime_response(response, "提交 H3 任务")
        job = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"提交 H3 任务失败：{_clean_error(exc)}") from exc
    if not isinstance(job, dict) or not job.get("id"):
        raise RuntimeError("H3 Runtime 未返回有效 job_id")
    _validated_runtime_job_id(job.get("id"))
    safe_target = {key: value for key, value in target.items() if key != "api_key"}
    return safe_target, job


def get_runtime_job(target: dict[str, Any], job_id: Any) -> dict[str, Any]:
    runtime_job_id = _validated_runtime_job_id(job_id)
    timeout = max(2.0, min(30.0, float(target.get("timeout_seconds") or 5)))
    private_target = dict(target or {})
    if "api_key" not in private_target:
        config = get_video_inference_config()
        private_target["api_key"] = _runtime_auth_key(config, str(target.get("mode") or "local"))
    try:
        with _new_session() as session:
            response = session.get(
                f"{target['base_url']}/v1/jobs/{urllib.parse.quote(runtime_job_id)}",
                headers=_runtime_headers(private_target),
                timeout=timeout,
            )
        _raise_runtime_response(response, "查询 H3 任务")
        payload = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"查询 H3 任务失败：{_clean_error(exc)}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("H3 Runtime 返回了无效任务状态")
    return payload


def cancel_runtime_job(target: dict[str, Any], job_id: Any) -> dict[str, Any]:
    runtime_job_id = _validated_runtime_job_id(job_id)
    timeout = max(2.0, min(30.0, float(target.get("timeout_seconds") or 5)))
    private_target = dict(target or {})
    if "api_key" not in private_target:
        config = get_video_inference_config()
        private_target["api_key"] = _runtime_auth_key(config, str(target.get("mode") or "local"))
    try:
        with _new_session() as session:
            response = session.post(
                f"{target['base_url']}/v1/jobs/{urllib.parse.quote(runtime_job_id)}/cancel",
                headers=_runtime_headers(private_target),
                timeout=timeout,
            )
        _raise_runtime_response(response, "取消 H3 任务")
        payload = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"取消 H3 任务失败：{_clean_error(exc)}") from exc
    return payload if isinstance(payload, dict) else {"id": runtime_job_id, "status": "cancelled"}


def download_runtime_result(
    target: dict[str, Any],
    job_id: Any,
    destination: Path,
    *,
    maximum_bytes: int = 8 * 1024 * 1024 * 1024,
) -> dict[str, Any]:
    runtime_job_id = _validated_runtime_job_id(job_id)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    private_target = dict(target or {})
    if "api_key" not in private_target:
        config = get_video_inference_config()
        private_target["api_key"] = _runtime_auth_key(config, str(target.get("mode") or "local"))
    connect_timeout = max(2.0, min(30.0, float(target.get("timeout_seconds") or 5)))
    written = 0
    try:
        with _new_session() as session:
            with session.get(
                f"{target['base_url']}/v1/jobs/{urllib.parse.quote(runtime_job_id)}/result",
                headers=_runtime_headers(private_target),
                timeout=(connect_timeout, 600),
                stream=True,
            ) as response:
                _raise_runtime_response(response, "下载 H3 视频")
                with partial.open("wb") as stream:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        written += len(chunk)
                        if written > maximum_bytes:
                            raise RuntimeError("H3 视频超过允许的最大文件大小")
                        stream.write(chunk)
        partial.replace(destination)
    except requests.RequestException as exc:
        raise RuntimeError(f"下载 H3 视频失败：{_clean_error(exc)}") from exc
    except Exception:
        try:
            partial.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return {"path": str(destination), "bytes": written, "content_type": "video/mp4"}


def start_local_runtime() -> dict[str, Any]:
    config = get_video_inference_config()
    component = collect_component_status(config)
    if not component["supported"]:
        return {"ok": False, "started": False, "component": component, "error": "当前系统不是 Windows，不能启动本机 H3 Runtime"}
    if not component["startable"]:
        return {"ok": False, "started": False, "component": component, "error": "H3 Runtime 组件目录或启动脚本不存在"}
    component_dir = Path(component["component_dir"])
    script = component_dir / component["start_script"]
    if script.suffix.lower() == ".ps1":
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    else:
        command = ["cmd.exe", "/c", str(script)]
    creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) | int(getattr(subprocess, "DETACHED_PROCESS", 0))
    subprocess.Popen(
        command,
        cwd=str(component_dir),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creation_flags,
    )
    return {"ok": True, "started": True, "component": component, "message": "H3 Runtime 启动命令已发送"}


def read_local_runtime_api_key() -> str:
    """Read a local component key server-side without ever returning it to UI."""
    config = get_video_inference_config()
    component_dir = str((config.get("local") or {}).get("component_dir") or "").strip()
    if not component_dir:
        return ""
    path = Path(component_dir).expanduser() / "config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    return str(data.get("api_key") or "").strip() if isinstance(data, dict) else ""
