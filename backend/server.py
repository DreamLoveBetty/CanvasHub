#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web App 图片生成服务器 - 重构版（简化架构）

功能:
- POST /generate - 提交生成任务（默认 webapp）
- POST /api/skill/generate - 提交技能生成任务（启用托底策略）
- POST /edit - 提交编辑任务（默认 webapp）
- POST /api/skill/edit - 提交技能编辑任务（启用托底策略）
- GET /status/<task_id> - 查询任务状态
- GET /history - 获取任务历史
- GET /image/<filename> - 获取图片文件
- GET / - 静态文件服务（Web App 前端）
- POST /api/spell/generate-prompt - 生成结构化图像提示词
"""
# 清除代理环境变量（避免影响 requests）
import os
os.environ["http_proxy"] = ""
os.environ["https_proxy"] = ""
os.environ["all_proxy"] = ""
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""
os.environ["ALL_PROXY"] = ""


import http.server
import socketserver
import socket
import os
import posixpath
import json
import time
import random
import threading
import urllib.parse
import tempfile
import uuid
import base64
import mimetypes
import shutil
import subprocess
import sys
import hmac
import hashlib
import re
import copy
import queue
from datetime import datetime
from pathlib import Path
from http.cookies import SimpleCookie
from PIL import Image
import requests
from .app_config import (
    APP_DATA_DIR,
    BASE_DIR,
    DEFAULT_GPT_IMAGE_MAIN_MODEL,
    DEFAULT_GPT_PROVIDER_TOTAL_TIMEOUT_SECONDS,
    DEFAULT_GPT_REASONING_EFFORT,
    DEFAULT_GPT_TRANSPORT_MODE,
    GPT_IMAGE_MAIN_MODELS,
    GPT_REASONING_EFFORTS,
    GPT_TRANSPORT_MODES,
    get_chatgpt_pool_config,
    get_chatgpt_pool_public_config,
    get_managed_codex_oauth_public_config,
    get_allowed_cors_origins,
    get_max_concurrent_tasks,
    get_proxy_config,
    get_prompt_skill_config,
    get_database_path,
    get_gpt_provider_config,
    get_miniapp_access_password,
    get_nano_banana_api_base_url,
    get_nano_banana_api_key,
    get_server_config,
    get_storage_config,
    get_telegram_auth_config,
    get_telegram_config,
    get_third_party_image_config,
    get_yunwu_api_base_url,
    get_yunwu_api_key,
    load_app_settings,
    save_app_settings,
    update_app_settings_section,
)
from .database import init_db, create_task, update_task, update_task_status, update_task_fields, get_task, get_all_tasks, delete_task, restore_task_snapshot, fail_stale_processing_tasks
from .generation_tracking import (
    finish_generation_run,
    get_generation_events,
    get_generation_run,
    get_generation_runs,
    record_generation_event,
    start_generation_run,
    translate_generation_error,
)
from .api_client import generate_image, edit_image, save_image, send_telegram
from .api_client_gpt import send_telegram_result, send_tg_document
from .provider_gpt_codex import generate_image_gpt_codex, edit_image_gpt_codex, get_gpt_provider_auth_status
from .provider_chatgpt_pool import chat_chatgpt_pool, edit_image_gpt_pool, generate_editable_file_gpt_pool, generate_image_gpt_pool, search_chatgpt_pool
from .provider_third_party_image import generate_image_third_party, edit_image_third_party
from .gpt_model_catalog import DEFAULT_POOL_MODEL, get_gpt_model_catalog, normalize_model_id, resolve_route_model
from .image_resolution import build_resolution_metadata, normalize_actual_sizes
from .managed_codex_oauth import (
    delete_managed_auth,
    finish_oauth_callback as finish_managed_codex_oauth_callback,
    get_auth_status as get_managed_codex_oauth_status,
    get_provider_env as get_managed_codex_provider_env,
    import_managed_auth_accounts,
    refresh_managed_auth,
    start_oauth_login as start_managed_codex_oauth_login,
    update_managed_auth_account,
)
from .editable_file_service import delete_editable_item, list_editable_files, resolve_editable_file, save_editable_artifacts
from .spell_client import generate_structured_spell_prompt
from .prompt_skill_client import (
    analyze_prompt_image,
    assistant_chat,
    assistant_chat_stream,
    discover_prompt_models,
    extract_reusable_prompt_blocks,
    extract_reusable_prompt_blocks_from_image,
    extract_style_preset,
    list_prompt_providers,
    polish_prompt,
    safe_rewrite_prompt,
)
from .storage_paths import IMAGE_ARCHIVE_DIR, SOURCE_IMAGE_DIR, archive_scan_roots, daily_output_dir, image_lookup_roots, source_image_roots, write_obsidian_prompt_sidecar
from .upscale_runtime import (
    UPSCALE_MODELS,
    UpscaleRuntimeError,
    available_upscale_models,
    default_upscale_model_dir,
    normalize_upscale_model,
    upscale_image_file,
)
from .optional_components import (
    get_upscale_component_status,
    remove_upscale_component,
    start_upscale_component_install,
)
from .asset_index import (
    create_asset_set,
    cleanup_asset_sets,
    delete_asset_set,
    get_asset as get_gallery_asset,
    get_delete_batch,
    init_asset_store,
    list_asset_sets,
    list_assets as list_gallery_assets,
    mark_delete_batch_restored,
    record_delete_batch,
    remove_asset_from_sets,
    restore_asset_set_snapshots,
    snapshot_sets_for_asset,
    update_asset_meta,
    update_asset_set,
)
from .layout_drafts import (
    create_draft as create_layout_draft,
    get_file as get_layout_draft_file,
    init_layout_draft_store,
    list_drafts as list_layout_drafts,
    load_draft as load_layout_draft,
    save_asset as save_layout_draft_asset,
    update_draft as update_layout_draft,
)
from .prompt_source_sync import (
    cancel_orphan_prompt_source_runs,
    get_prompt_source_run,
    init_prompt_source_store,
    list_prompt_source_items,
    list_prompt_sources,
    resolve_source_image,
    start_prompt_source_sync,
    stop_prompt_source_sync,
)
from .prompt_library import (
    delete_prompt_block,
    delete_prompt_template,
    init_prompt_library_store,
    list_prompt_blocks,
    list_prompt_templates,
    mark_prompt_block_used,
    resolve_prompt_template,
    save_prompt_block,
    save_prompt_template,
)
from .thumb_cache import ensure_webp_thumbnail, parse_thumb_request, resolve_media_path
from .pose_service import pose_assets_status
from .app_updates import get_app_update_status

SERVER_CONFIG = get_server_config()
SERVER_HOST = SERVER_CONFIG["host"]
PORT = SERVER_CONFIG["port"]
PROJECT_ROOT = BASE_DIR
BACKEND_ROOT = Path(__file__).resolve().parent
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
DIRECTORY = str(APP_DATA_DIR)
PROMPT_DATA_DIR = APP_DATA_DIR / 'data'
STYLE_PRESETS_FILE = PROMPT_DATA_DIR / 'style_presets.json'
PROMPT_VERSIONS_FILE = PROMPT_DATA_DIR / 'prompt_versions.json'
COMFY_BASE_URL = os.environ.get('COMFY_BASE_URL', 'http://192.168.179.111:28188').rstrip('/')
COMFY_TIMEOUT_SECONDS = int(os.environ.get('COMFY_TIMEOUT_SECONDS', '120'))
MAX_GPT_IMAGE_COUNT = 8


def _coerce_gpt_image_count(data, prompt=''):
    """Accept frontend count aliases, with a light prompt fallback."""
    aliases = ('image_count', 'imageCount', 'count', 'n', 'num_images', 'numImages')
    raw = None
    for key in aliases:
        if key in data:
            raw = data.get(key)
            break

    if raw is None and prompt:
        text = str(prompt)
        match = re.search(r'(?:生成|出|做|来)?\s*([1-8])\s*(?:张|幅|个|images?|pics?)', text, re.I)
        if not match:
            cn_digits = {
                '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
                '六': 6, '七': 7, '八': 8,
            }
            match = re.search(r'(?:生成|出|做|来)?\s*([一二两三四五六七八])\s*(?:张|幅|个)', text)
            raw = cn_digits.get(match.group(1)) if match else None
        else:
            raw = match.group(1)

    try:
        count = int(raw or 1)
    except (TypeError, ValueError):
        count = 1
    return max(1, min(MAX_GPT_IMAGE_COUNT, count))


def _coerce_gpt_quality(value):
    quality = str(value or 'auto').strip().lower()
    return quality if quality in ('low', 'medium', 'high', 'auto') else 'auto'


def _coerce_gpt_moderation(value):
    moderation = str(value or 'auto').strip().lower()
    return moderation if moderation in ('auto', 'low') else 'auto'


def _coerce_prompt_mode(value):
    mode = str(value or 'smart').strip().lower()
    if mode in ('faithful', 'literal', '忠实原文'):
        return 'faithful'
    if mode in ('web_search', 'search', 'research', '联网检索', '联网搜索'):
        return 'web_search'
    return 'smart'


def _coerce_gpt_task_type(value):
    task_type = str(value or 'image').strip().lower()
    if task_type in ('ppt', 'powerpoint', 'presentation'):
        return 'ppt'
    if task_type in ('psd', 'photoshop'):
        return 'psd'
    return 'image'


def _coerce_bool(value, default=True):
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    raw = str(value).strip().lower()
    if raw in {'1', 'true', 'yes', 'on', 'enabled', '开启'}:
        return True
    if raw in {'0', 'false', 'no', 'off', 'disabled', '关闭'}:
        return False
    return bool(default)


def _coerce_use_third_party_api(*values):
    for value in values:
        if value is not None:
            return _coerce_bool(value, False)
    return False


def _coerce_gpt_provider_route(value):
    route = str(value or 'codex').strip().lower()
    if route in ('managed_codex_oauth', 'managed_codex', 'managed_oauth', 'codex_oauth', 'oauth_codex'):
        return 'codex'
    if route in ('chatgpt_pool', 'pool', 'sidecar', 'web_api', 'account_pool'):
        return 'chatgpt_pool'
    if route in ('third_party_image_api', 'third_party_api', 'third_party', 'external_api', 'yunwu'):
        return 'third_party_image_api'
    if route in ('codex', 'local', 'local_codex'):
        return 'codex'
    return 'codex'


def _gpt_route_uses_third_party(route):
    return _coerce_gpt_provider_route(route) == 'third_party_image_api'


def _resolve_codex_provider_env() -> tuple[dict | None, str]:
    """Prefer project-managed Codex OAuth, then fall back to local Codex auth."""
    try:
        managed_status = get_managed_codex_oauth_status()
    except Exception as exc:
        print(f"⚠️ managed Codex status unavailable: {exc}")
        managed_status = {}

    if managed_status.get("enabled") and managed_status.get("configured"):
        try:
            return get_managed_codex_provider_env(), "managed_codex_oauth"
        except Exception as exc:
            print(f"⚠️ managed Codex auth unavailable; falling back to local Codex: {exc}")

    return None, "codex"


VALID_GPT_MAIN_MODELS = set(GPT_IMAGE_MAIN_MODELS)
VALID_GPT_REASONING_EFFORTS = set(GPT_REASONING_EFFORTS)
VALID_GPT_TRANSPORT_MODES = set(GPT_TRANSPORT_MODES)


def _coerce_gpt_main_model(value):
    if value in (None, ''):
        value = get_gpt_provider_config().get('image_main_model')
    return normalize_model_id(value, DEFAULT_GPT_IMAGE_MAIN_MODEL)


def _coerce_gpt_reasoning_effort(value):
    if value in (None, ''):
        value = get_gpt_provider_config().get('reasoning_effort')
    effort = str(value or DEFAULT_GPT_REASONING_EFFORT).strip().lower()
    return effort if effort in VALID_GPT_REASONING_EFFORTS else DEFAULT_GPT_REASONING_EFFORT


def _coerce_gpt_transport_mode(value):
    if value in (None, ''):
        value = get_gpt_provider_config().get('transport_mode')
    mode = str(value or DEFAULT_GPT_TRANSPORT_MODE).strip().lower()
    return mode if mode in VALID_GPT_TRANSPORT_MODES else DEFAULT_GPT_TRANSPORT_MODE


def _coerce_gpt_provider_total_timeout(value):
    if value in (None, ''):
        value = get_gpt_provider_config().get('total_timeout_seconds')
    try:
        timeout = int(value or DEFAULT_GPT_PROVIDER_TOTAL_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        timeout = DEFAULT_GPT_PROVIDER_TOTAL_TIMEOUT_SECONDS
    return max(30, min(1800, timeout))


def _merge_task_params(task_id, patch):
    if not isinstance(patch, dict) or not patch:
        return
    task = get_task(task_id) or {}
    params = task.get('params') if isinstance(task.get('params'), dict) else {}
    params.update({k: v for k, v in patch.items() if v not in (None, '')})
    update_task_fields(task_id, params=json.dumps(params, ensure_ascii=False))


def _append_task_route_trace(task_id, route, status, message='', **extra):
    task = get_task(task_id) or {}
    params = task.get('params') if isinstance(task.get('params'), dict) else {}
    trace = params.get('route_trace')
    if not isinstance(trace, list):
        trace = []
    entry = {
        'route': str(route or '').strip(),
        'status': str(status or '').strip(),
        'at': int(time.time()),
    }
    if message:
        entry['message'] = str(message)[:500]
    if str(status or '').strip() == 'failed':
        entry['error_category'] = _classify_route_error(route, message)
    for key, value in extra.items():
        if value not in (None, ''):
            entry[key] = value
    trace.append(entry)
    params['route_trace'] = trace[-20:]
    update_task_fields(task_id, params=json.dumps(params, ensure_ascii=False))
    if str(status or '').strip() in ('started', 'succeeded', 'failed', 'canceled', 'skipped'):
        payload = {
            'route': str(route or '').strip(),
            'status': str(status or '').strip(),
            'message': str(message or '').strip(),
        }
        if extra:
            payload.update({k: v for k, v in extra.items() if v not in (None, '')})
        _record_generation_event(task_id, f'route_{str(status or "").strip() or "update"}', message, stage=str(status or '').strip(), severity='error' if str(status or '').strip() == 'failed' else 'info', payload=payload)


def _classify_route_error(route, message=''):
    """Coarse failure labels for route trace UI; never include secrets."""
    text = str(message or '').lower()
    route_text = str(route or '').lower()
    if 'browser verification' in text or '需要浏览器验证' in text or 'turnstile' in text or 'arkose' in text:
        return 'verification_required'
    if 'connection refused' in text or 'failed to establish a new connection' in text or 'offline' in text:
        return 'offline'
    if 'unauthorized' in text or 'http 401' in text or 'auth' in text and 'key' in text:
        return 'auth'
    if 'http 429' in text or 'rate limit' in text or '限流' in text:
        return 'rate_limited'
    if 'no available image quota' in text or 'quota' in text or '额度' in text:
        return 'quota'
    if 'timeout' in text or 'timed out' in text or '超时' in text:
        return 'timeout'
    if (
        'sslerror' in text
        or 'ssl eof' in text
        or 'unexpected_eof_while_reading' in text
        or 'remote end closed connection' in text
        or 'connection reset' in text
        or 'connection aborted' in text
    ):
        return 'transport'
    if 'finished without image output' in text or 'did not return any images' in text or 'upstream did not return image output' in text:
        return 'no_image_output'
    if 'download url' in text or 'download_url' in text or 'artifact' in text:
        return 'artifact_download'
    if 'refus' in text or 'violat' in text or '安全策略' in text:
        return 'model_refusal'
    if 'proxyerror' in text or 'unable to connect to proxy' in text or 'remote end closed connection' in text:
        return 'proxy'
    if 'chatgpt_pool' in route_text or 'sidecar' in text:
        return 'sidecar'
    if 'codex' in route_text or 'provider' in text:
        return 'provider'
    return 'unknown'


def _generation_run_task(task_id):
    task = get_task(task_id) or {}
    params = task.get('params') if isinstance(task.get('params'), dict) else {}
    return task, params


def _generation_last_run_id(task_id):
    task, params = _generation_run_task(task_id)
    run_id = str(task.get('last_run_id') or params.get('last_run_id') or '').strip()
    return run_id


def _record_generation_event(task_id, event_type, message='', stage='', severity='info', payload=None):
    run_id = _generation_last_run_id(task_id)
    if not run_id:
        return None
    try:
        return record_generation_event(
            run_id,
            task_id,
            event_type,
            message,
            stage=stage,
            severity=severity,
            payload=payload or {},
        )
    except Exception as exc:
        print(f"⚠️ generation event write failed: {task_id} {run_id} {event_type} - {exc}")
        return None


def _generation_run_route(task_id, fallback=''):
    task, params = _generation_run_task(task_id)
    route = (
        params.get('gpt_provider_route')
        or params.get('provider_route')
        or task.get('type')
        or fallback
    )
    return str(route or fallback or '').strip()


def _start_generation_audit(task_id, task_type, prompt, params, *, provider='', route='', stage='preparing', parent_run_id=''):
    try:
        run = start_generation_run(
            task_id,
            task_type,
            provider=provider,
            route=route,
            prompt=prompt,
            params=params,
            stage=stage,
            parent_run_id=parent_run_id,
        )
        _record_generation_event(
            task_id,
            'run_started',
            f'开始处理 {task_type}',
            stage=stage,
            severity='info',
            payload={
                'provider': provider,
                'route': route,
                'task_type': task_type,
            },
        )
        return run['run_id']
    except Exception as exc:
        print(f"⚠️ generation run start failed: {task_id} - {exc}")
        return ''


def _translate_generation_failure(task_id, raw_error, *, provider='', route='', task_type='', stage='', exception_name=''):
    info = translate_generation_error(
        raw_error,
        provider=provider,
        route=route,
        task_type=task_type,
        stage=stage,
        exception_name=exception_name,
    )
    _record_generation_event(
        task_id,
        'run_failed',
        info.get('display_error') or str(raw_error or ''),
        stage=stage,
        severity='error',
        payload={
            'error_code': info.get('error_code') or '',
            'error_category': info.get('error_category') or '',
            'raw_error': info.get('raw_error') or str(raw_error or ''),
            'provider': provider,
            'route': route,
            'task_type': task_type,
        },
    )
    return info


def _finalize_generation_task(
    task_id,
    status,
    *,
    run_id='',
    stage='done',
    progress_text='',
    result_file=None,
    result_files=None,
    image_count=None,
    error_info=None,
    error_type='',
    provider='',
    route='',
    task_type='',
    extra=None,
):
    result_files_json = None
    if isinstance(result_files, list):
        result_files_json = json.dumps(result_files, ensure_ascii=False)
    elif isinstance(result_files, str):
        result_files_json = result_files
    task_field_names = {
        'status', 'stage', 'progress_text', 'progress', 'result_file', 'result_files', 'error',
        'error_code', 'display_error', 'error_category', 'raw_error',
        'transport_error_type', 'heartbeat_at', 'first_byte_at', 'bytes_received',
        'ttfb_ms', 'started_at', 'finished_at', 'last_run_id', 'run_count', 'params',
        'type', 'updated_at',
    }
    payload = {
        'stage': stage,
        'progress_text': progress_text,
        'result_file': result_file,
        'result_files': result_files_json,
        'error_code': error_info.get('error_code') if isinstance(error_info, dict) else None,
        'display_error': error_info.get('display_error') if isinstance(error_info, dict) else None,
        'error_category': error_info.get('error_category') if isinstance(error_info, dict) else None,
        'raw_error': error_info.get('raw_error') if isinstance(error_info, dict) else None,
        'transport_error_type': error_type or None,
    }
    if extra:
        payload.update(extra)
    if status in ('succeeded', 'succeeded_no_telegram', 'failed', 'telegram_failed', 'canceled'):
        payload.setdefault('progress', 100)
    if status in ('succeeded', 'succeeded_no_telegram'):
        payload['error'] = None
        if not result_files_json and result_files is not None:
            payload['result_files'] = json.dumps(result_files, ensure_ascii=False)
        payload['error_code'] = ''
        payload['display_error'] = ''
        payload['error_category'] = ''
        payload['raw_error'] = ''
    elif isinstance(error_info, dict):
        payload['error'] = error_info.get('display_error') or error_info.get('raw_error') or progress_text
    task_payload = {k: v for k, v in payload.items() if k in task_field_names and k != 'error' and v is not None}
    update_task(task_id, status, error=payload.get('error'), **task_payload)
    if run_id:
        finish_generation_run(
            run_id,
            task_id,
            status=status,
            stage=stage,
            provider=provider,
            route=route,
            result_file=result_file or '',
            result_files=result_files if isinstance(result_files, list) else None,
            image_count=image_count,
            error_info=error_info,
            error_type=error_type,
            meta=extra,
        )


def _status_response_task(task):
    task = dict(task or {})
    params = task.get('params') if isinstance(task.get('params'), dict) else {}
    provider_failure = params.get('provider_failure') if isinstance(params.get('provider_failure'), dict) else {}
    for key in ('timed_out', 'partial_errors', 'completed_image_count', 'requested_image_count'):
        if provider_failure.get(key) is not None:
            task[key] = provider_failure.get(key)
    result_files, primary_output = _history_task_result_files(task)
    if result_files:
        task['result_file'] = primary_output
        task['result_files'] = result_files
        task['output_files'] = result_files
        if task.get('type') == 'gpt-file':
            task['image_paths'] = []
            params = task.get('params') if isinstance(task.get('params'), dict) else {}
            if isinstance(params.get('file_manifest'), dict):
                task['file_manifest'] = params.get('file_manifest')
            task['artifact_type'] = params.get('artifact_type') or params.get('task_type')
        else:
            task['image_paths'] = [f"/gpt_outputs/{name}" for name in result_files] if task.get('type') in ('gpt', 'gpt-edit') else [f"/image/{name}" for name in result_files]
        task['image_count'] = len(result_files)
    else:
        task.setdefault('result_files', [])
        task.setdefault('output_files', [])
        task.setdefault('image_paths', [])
        task.setdefault('image_count', 0)
    task.setdefault('display_error', task.get('error') or '')
    task.setdefault('error_code', '')
    task.setdefault('error_category', '')
    task.setdefault('raw_error', task.get('error') or '')
    task.setdefault('last_run_id', '')
    task.setdefault('run_count', 0)
    task.setdefault('progress', 100 if task.get('status') in ('succeeded', 'success', 'failed', 'telegram_failed', 'canceled') else 0)
    return task


VALID_IMAGE_RATIOS = {
    '1:1', '2:3', '3:2', '3:4', '4:3', '4:5', '5:4',
    '9:16', '16:9', '9:21', '21:9'
}


def _coerce_image_ratio(value, default='1:1'):
    ratio = str(value or '').strip().lower()
    return ratio if ratio in VALID_IMAGE_RATIOS else default


def _coerce_gpt_resolution(value):
    resolution = str(value or '1k').strip().lower()
    return resolution if resolution in ('1k', '2k', '4k') else '1k'


def _result_path_dimensions(path_value):
    path_text = str(path_value or '').strip()
    if not path_text:
        return None
    try:
        path = Path(path_text)
    except Exception:
        return None
    if not path.is_absolute():
        path = PROJECT_ROOT / path_text.lstrip('/\\')
    try:
        with Image.open(path) as img:
            return img.size
    except Exception:
        return None


def _result_actual_sizes(result):
    result = result if isinstance(result, dict) else {}
    sizes = normalize_actual_sizes(result.get('actual_sizes'))
    if sizes:
        return sizes
    paths = []
    for item in result.get('image_paths') or []:
        if item:
            paths.append(item)
    if result.get('image_path'):
        paths.append(result.get('image_path'))
    discovered = []
    seen = set()
    for item in paths:
        key = str(item or '').strip()
        if not key or key in seen:
            continue
        seen.add(key)
        dimensions = _result_path_dimensions(key)
        if dimensions:
            discovered.append({'width': dimensions[0], 'height': dimensions[1]})
    return discovered


def _augment_result_resolution_metadata(result, requested_resolution):
    if not isinstance(result, dict):
        return {}
    metadata = build_resolution_metadata(
        requested_resolution,
        _result_actual_sizes(result),
        result.get('requested_size'),
    )
    for key, value in metadata.items():
        if value not in (None, ''):
            result[key] = value
    return metadata


def _coerce_google_quality(value, default='2k'):
    quality = str(value or default).strip().lower()
    aliases = {
        'standard': '1k',
        'normal': '1k',
        'hd': '4k',
    }
    quality = aliases.get(quality, quality)
    return quality if quality in ('1k', '2k', '4k') else default


def _coerce_google_edit_quality(value):
    quality = str(value or 'hd').strip().lower()
    if quality in ('1k', 'standard', 'normal'):
        return 'standard'
    return 'hd' if quality in ('2k', '4k', 'hd') else 'hd'


DEFAULT_GOOGLE_IMAGE_MODEL = 'gemini-3.1-flash-image'
DEFAULT_GOOGLE_MAX_TOKENS = 4096


def _coerce_model(value, default=DEFAULT_GOOGLE_IMAGE_MODEL):
    model = str(value or '').strip()
    aliases = {
        'gemini-3-pro-image-preview': 'gemini-3-pro-image',
        'gemini-3.1-flash-image-preview': 'gemini-3.1-flash-image',
    }
    return aliases.get(model, model) or default


def _coerce_google_max_tokens(value, default=DEFAULT_GOOGLE_MAX_TOKENS):
    try:
        tokens = int(value)
    except Exception:
        tokens = default
    return tokens if tokens > 0 else default


def _coerce_google_temperature(value):
    if value is None or value == '':
        return None
    try:
        return float(value)
    except Exception:
        return None


def _coerce_google_output_controls(params):
    params = params if isinstance(params, dict) else {}
    archive_enabled = _coerce_bool(params.get('archive_enabled', params.get('archiveEnabled')), True)
    telegram_enabled = _coerce_bool(params.get('telegram_enabled', params.get('telegramEnabled')), True)
    return archive_enabled, telegram_enabled


def _short_text(value, limit=500):
    text = " ".join(str(value or "").split())
    return text[:limit]


def _stable_lineage_url(value):
    url = str(value or "").strip()
    if not url or url.startswith("data:") or url.startswith("blob:"):
        return ""
    return url[:500]


def _normalize_lineage_reference(item, index=0):
    if not isinstance(item, dict):
        return None
    asset_id = _short_text(item.get("asset_id") or item.get("assetId") or item.get("id"), 120)
    task_id = _short_text(item.get("task_id") or item.get("taskId"), 120)
    image_url = _stable_lineage_url(item.get("image_url") or item.get("imageUrl") or item.get("imagePath") or item.get("url"))
    source_node_id = _short_text(item.get("source_node_id") or item.get("sourceNodeId"), 120)
    if not asset_id and not task_id and not image_url and not source_node_id:
        return None
    return {
        "asset_id": asset_id,
        "task_id": task_id,
        "image_url": image_url,
        "title": _short_text(item.get("title") or item.get("name") or item.get("file") or f"参考图 {index + 1}", 160),
        "prompt": _short_text(item.get("prompt"), 500),
        "file": _short_text(item.get("file"), 180),
        "source": _short_text(item.get("source"), 48),
        "source_node_id": source_node_id,
        "index": index,
    }


def _extract_lineage_payload(data):
    if not isinstance(data, dict):
        return {}
    raw = data.get("lineage") if isinstance(data.get("lineage"), dict) else {}
    raw_refs = raw.get("reference_assets") or raw.get("referenceAssets") or data.get("reference_assets") or data.get("referenceAssets") or []
    refs = []
    seen = set()
    if isinstance(raw_refs, list):
        for index, item in enumerate(raw_refs[:16]):
            ref = _normalize_lineage_reference(item, index)
            if not ref:
                continue
            key = ref.get("asset_id") or (f"{ref.get('task_id')}:{ref.get('image_url')}" if ref.get("task_id") or ref.get("image_url") else "") or ref.get("source_node_id")
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    if not refs:
        return {}
    asset_ids = []
    task_ids = []
    for ref in refs:
        if ref.get("asset_id") and ref["asset_id"] not in asset_ids:
            asset_ids.append(ref["asset_id"])
        if ref.get("task_id") and ref["task_id"] not in task_ids:
            task_ids.append(ref["task_id"])
    return {
        "reference_assets": refs,
        "reference_asset_ids": asset_ids,
        "source_task_ids": task_ids,
    }


def _attach_lineage_params(params, data):
    lineage = _extract_lineage_payload(data)
    if lineage:
        params["lineage"] = lineage
    return params


def _format_gpt_provider_error(error):
    """Turn common local provider failures into user-readable status text."""
    text = str(error or '').strip()
    if not text:
        return '本地 provider 失败'

    lower_text = text.lower()

    if 'usage_limit_reached' in text or 'usage limit has been reached' in text.lower():
        reset_text = ''
        match = re.search(r'"resets_at"\s*:\s*(\d+)', text)
        if match:
            try:
                reset_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(match.group(1))))
                reset_text = f'，预计 {reset_time} 恢复'
            except (TypeError, ValueError, OverflowError):
                reset_text = ''
        return f'本地 GPT 授权额度已用完{reset_text}'

    if 'moderation_blocked' in text or 'safety_violations' in text or 'rejected by the safety system' in lower_text:
        request_id = ''
        match = re.search(r'(?:request_id=|request ID\s+)([A-Za-z0-9_-]+)', text, re.I)
        if match:
            request_id = f'（request_id: {match.group(1)}）'
        return f'本地 GPT provider 被安全系统拒绝{request_id}，请降低敏感姿势、暴露、低角度或擦边描述后重试'

    if 'did not return image output' in lower_text and 'output_text=' in lower_text:
        if any(marker in lower_text for marker in ('violate', 'policy', 'safety', 'cannot', 'refuse', 'sorry', '违反', '安全', '抱歉', '拒绝')):
            return '本地 GPT provider 返回了文字而不是图片，可能触发安全/内容边界；请修改提示词后重新生成'
        return '本地 GPT provider 返回了文字而不是图片；请把需求改成明确的图片生成描述后重试'

    if 'did not return image output' in lower_text or 'missing image output' in lower_text:
        return '本地 GPT provider 没有返回图片数据，通常是上游生成失败或返回了非图片结果'

    if 'chunkedencodingerror' in lower_text or 'response ended prematurely' in lower_text:
        if 'last_event=response.image_generation_call.generating' in lower_text:
            return '本地 GPT provider 连接中途断开：已进入图片生成阶段，但上游/网络没有完整返回图片流；可稍后重试，连续发生时检查网络/代理或降低分辨率'
        if 'before first event' in lower_text:
            return '本地 GPT provider 连接在收到模型响应前断开；请优先检查网络、代理或稍后重试'
        return '本地 GPT provider 连接中途断开，通常是上游图片流提前结束或网络/代理中断'

    if 'stream disconnected' in lower_text:
        return '本地 GPT provider 图片流未完整返回，通常是上游连接提前结束或网络/代理中断'

    if 'response.failed' in text or 'server_error' in text:
        request_id = ''
        match = re.search(r'(?:request_id=|request ID\s+)([A-Za-z0-9_-]+)', text, re.I)
        if match:
            request_id = f'（request_id: {match.group(1)}）'
        return f'OpenAI/Codex 上游临时错误{request_id}'

    if 'total timeout after' in text.lower():
        match = re.search(r'total timeout after\s+(\d+)s', text, re.I)
        waited = f"{match.group(1)}s" if match else '超时阈值'
        return f'本地 GPT provider 调用超时（{waited}）'

    if text.startswith('HTTP 429'):
        return '本地 GPT provider 返回 429 限流'

    return f'本地 provider 失败：{text[:120]}'


def _first_user_error_line(error):
    text = str(error or '').strip()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('at ') or line.startswith('File '):
            continue
        if re.match(r'^\^+$', line):
            continue
        line = re.sub(r'^(?:Error|RuntimeError|Exception):\s*', '', line).strip()
        if line:
            return line
    return ''


def _format_gpt_pool_error(error):
    """Turn account-pool sidecar failures into user-readable status text."""
    text = str(error or '').strip()
    if not text:
        return 'ChatGPT 账号池托底失败'
    lower_text = text.lower()
    if 'browser verification' in lower_text or '需要浏览器验证' in text or 'turnstile' in lower_text or 'arkose' in lower_text:
        return 'ChatGPT 账号池需要浏览器验证'
    if (
        'image quota exhausted' in lower_text
        or 'image generation quota reached' in lower_text
        or 'image generations requests' in lower_text
        or 'free plan limit' in lower_text
        or '图片创建上限' in text
        or '图片生成额度' in text
        or '恢复时间' in text
    ):
        reset_text = ''
        match = re.search(r'(?:reset_after=|恢复时间\s*)([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.+-]+)', text)
        if match:
            reset_raw = match.group(1)
            try:
                reset_dt = datetime.fromisoformat(reset_raw.replace('Z', '+00:00'))
                reset_text = f'，预计 {reset_dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")} 恢复'
            except Exception:
                reset_text = f'，恢复时间 {reset_raw}'
        elif 'resets_after_text=' in text:
            match = re.search(r'resets_after_text=([^;|]+)', text)
            if match:
                reset_text = f'，{match.group(1).strip()}后恢复'
        return f'ChatGPT 账号池图片生成额度已用完{reset_text}'
    if 'disabled' in lower_text:
        return 'ChatGPT 账号池未启用'
    if 'connection refused' in lower_text or 'failed to establish a new connection' in lower_text:
        return 'ChatGPT 账号池 sidecar 未在线'
    if 'unauthorized' in lower_text or 'http 401' in lower_text:
        return 'ChatGPT 账号池鉴权失败，请确认 server.py 与 sidecar 使用同一个 auth key'
    if 'no available image quota' in lower_text:
        return 'ChatGPT 账号池没有可用账号或额度'
    if (
        'finished without image output' in lower_text
        or 'did not return any images' in lower_text
        or 'upstream did not return image output' in lower_text
    ):
        return 'ChatGPT 账号池上游会话已结束但没有返回图片，请重试或切换线路'
    if 'timeout' in lower_text or 'timed out' in lower_text:
        return 'ChatGPT 账号池生成等待超时'
    if 'http 429' in lower_text or 'rate limit' in lower_text or '限流' in text:
        return 'ChatGPT 账号池账号被限流'
    summary = _first_user_error_line(text)
    return f'ChatGPT 账号池托底失败：{summary[:120]}' if summary else 'ChatGPT 账号池托底失败'


class ChatgptPoolGenerationError(RuntimeError):
    def __init__(self, message, provider_result):
        super().__init__(message)
        self.provider_result = dict(provider_result) if isinstance(provider_result, dict) else {}


def _chatgpt_pool_failure_metadata(error):
    result = getattr(error, 'provider_result', None)
    if not isinstance(result, dict):
        return {}
    metadata = {}
    for key in ('error_code', 'timed_out', 'partial_errors', 'completed_image_count', 'requested_image_count'):
        if result.get(key) is not None:
            metadata[key] = result.get(key)
    return metadata


def _prepare_chatgpt_pool_generation_prompt(task_id, prompt, prompt_mode):
    """Use the configured prompt skill before Web-conversation image generation."""
    if _coerce_prompt_mode(prompt_mode) != 'smart':
        return str(prompt or ''), {}
    try:
        update_task_status(task_id, 'processing', '正在调用提示词润色模型...', stage='polishing_prompt')
        result = polish_prompt(str(prompt or ''), {})
        cfg = get_prompt_skill_config()
        preferred_key = str(cfg.get('default_output') or 'full_prompt')
        optimized = str(result.get(preferred_key) or result.get('full_prompt') or result.get('compact_prompt') or '').strip()
        if not optimized:
            return str(prompt or ''), {'prompt_polish_error': '润色结果为空'}
        return optimized, {
            'prompt_optimized': True,
            'prompt_optimized_by': 'prompt_skill',
            'prompt_skill_provider': result.get('provider'),
            'prompt_skill_model': result.get('model'),
            'prompt_skill': result.get('skill'),
            'prompt_skill_output': preferred_key,
            'prompt_skill_latency_seconds': result.get('latency_seconds'),
            'original_prompt': str(prompt or ''),
            'optimized_prompt': optimized,
        }
    except Exception as exc:
        error = str(exc)
        print(f"⚠️ ChatGPT 账号池本地提示词润色失败，尝试账号池 chat 兜底：{error}")
        return _prepare_chatgpt_pool_generation_prompt_with_chat(task_id, prompt, error)


def _extract_json_object_from_text(text):
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(text or "").strip(), flags=re.IGNORECASE | re.MULTILINE)
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("模型未返回 JSON 对象")
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(cleaned)):
        ch = cleaned[index]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(cleaned[start:index + 1])
    raise ValueError("模型返回的 JSON 不完整")


def _chatgpt_pool_chat_content(result):
    payload = result.get("result") if isinstance(result, dict) else {}
    choices = payload.get("choices") if isinstance(payload, dict) else []
    first = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    return str(message.get("content") or "").strip(), payload


def _prompt_polish_chat_messages(original):
    system_prompt = (
        "你是图像生成提示词优化助手。只做提示词润色和结构整理，不要联网检索，不要研究资料。"
        "请把用户文本改写为图像模型可直接使用的成片提示词，保留用户语义，不新增无根据的主体。"
        "只返回合法 JSON 对象，不要 markdown，不要解释。JSON 字段必须包含 full_prompt、compact_prompt、warnings。"
    )
    user_prompt = "\n".join([
        "请优化下面的图像提示词。",
        "要求：",
        "- full_prompt 是较完整的成片提示词，包含主体、场景、构图、光影、材质/媒介、负面约束。",
        "- compact_prompt 是更短的可投喂版本。",
        "- warnings 是字符串数组，可为空。",
        "",
        "原始提示词：",
        "<<<",
        original,
        ">>>",
    ])
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _polish_prompt_with_chatgpt_pool_chat(prompt, polish_error):
    original = str(prompt or '').strip()
    if not original:
        raise ValueError("缺少要润色的文本")
    started = time.time()
    result = chat_chatgpt_pool(
        _prompt_polish_chat_messages(original),
        model="auto",
        timeout_seconds=180,
    )
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "账号池 chat 失败")
    content, payload = _chatgpt_pool_chat_content(result)
    data = _extract_json_object_from_text(content)
    full_prompt = str(data.get('full_prompt') or data.get('完整提示词') or '').strip()
    compact_prompt = str(data.get('compact_prompt') or data.get('精简提示词') or data.get('精简可投喂版') or '').strip()
    if not full_prompt and compact_prompt:
        full_prompt = compact_prompt
    if not compact_prompt and full_prompt:
        compact_prompt = full_prompt
    if not full_prompt:
        raise RuntimeError("账号池 chat 润色结果为空")
    warnings = data.get('warnings') if isinstance(data.get('warnings'), list) else []
    modules = data.get('modules') if isinstance(data.get('modules'), list) else []
    return {
        'ok': True,
        'full_prompt': full_prompt,
        'compact_prompt': compact_prompt,
        'modules': modules,
        'warnings': warnings,
        'router_summary': str(data.get('router_summary') or '').strip(),
        'original_text': original,
        'provider': 'chatgpt_pool',
        'model': payload.get('model') if isinstance(payload, dict) else 'auto',
        'skill': 'chat_fallback',
        'reasoning_effort': '',
        'expanded': False,
        'latency_seconds': round(time.time() - started, 2),
        'fallback': 'chatgpt_pool_chat',
        'prompt_polish_fallback': 'chatgpt_pool_chat',
        'prompt_polish_error': str(polish_error)[:300],
    }


def _prepare_chatgpt_pool_generation_prompt_with_chat(task_id, prompt, polish_error):
    update_task_status(task_id, 'processing', '本地润色失败，正在用账号池 chat 兜底润色...', stage='polishing_prompt')
    original = str(prompt or '').strip()
    if not original:
        return str(prompt or ''), {'prompt_polish_error': str(polish_error)[:300]}
    try:
        result = _polish_prompt_with_chatgpt_pool_chat(original, polish_error)
        cfg = get_prompt_skill_config()
        preferred_key = str(cfg.get('default_output') or 'full_prompt')
        optimized = str(result.get(preferred_key) or result.get('full_prompt') or result.get('compact_prompt') or '').strip()
        if not optimized:
            raise RuntimeError("账号池 chat 润色结果为空")
        return optimized, {
            'prompt_optimized': True,
            'prompt_optimized_by': 'chatgpt_pool_chat',
            'prompt_skill_provider': 'chatgpt_pool',
            'prompt_skill_model': result.get('model') or 'auto',
            'prompt_skill': 'chat_fallback',
            'prompt_skill_output': preferred_key,
            'prompt_polish_fallback': 'chatgpt_pool_chat',
            'prompt_polish_error': str(polish_error)[:300],
            'original_prompt': original,
            'optimized_prompt': optimized,
        }
    except Exception as exc:
        chat_error = str(exc)
        print(f"⚠️ ChatGPT 账号池 chat 润色兜底失败，改用原 prompt：{chat_error}")
        return str(prompt or ''), {
            'prompt_polish_error': str(polish_error)[:300],
            'prompt_pool_chat_error': chat_error[:300],
        }


def _source_summary_list(sources, limit=5):
    items = []
    for source in sources if isinstance(sources, list) else []:
        if not isinstance(source, dict):
            continue
        url = str(source.get('url') or '').strip()
        title = str(source.get('title') or '').strip()
        snippet = str(source.get('snippet') or '').strip()
        if not url and not title and not snippet:
            continue
        items.append({'title': title, 'url': url, 'snippet': snippet[:240], 'source_type': str(source.get('source_type') or '').strip()})
        if len(items) >= limit:
            break
    return items


def _prepare_web_search_generation_prompt(task_id, prompt):
    original = str(prompt or '').strip()
    if not original:
        return str(prompt or ''), {'web_search_error': 'prompt is empty'}
    update_task_status(task_id, 'processing', '正在联网检索并整理提示词...', stage='web_search_prompt')
    _append_task_route_trace(task_id, 'chatgpt_pool_search', 'started', '正在执行联网检索')
    query = "\n".join([
        "围绕下面的图像生成需求做联网检索或研究。",
        "目标是提取可用于图像创作的真实事实、视觉细节、时代/地点/物体特征、风格参考和注意事项。",
        "不要直接生成图片提示词，先给出检索结论和来源。",
        "",
        "图像生成需求：",
        "<<<",
        original,
        ">>>",
    ])
    search_response = search_chatgpt_pool(query, timeout_seconds=300)
    if not search_response.get('ok'):
        error = str(search_response.get('error') or '账号池联网检索失败')
        _append_task_route_trace(task_id, 'chatgpt_pool_search', 'failed', error)
        raise RuntimeError(f"联网检索失败：{error}")
    search_result = search_response.get('result') if isinstance(search_response.get('result'), dict) else {}
    answer = str(search_result.get('answer') or '').strip()
    sources = _source_summary_list(search_result.get('sources') or [])
    if not answer:
        raise RuntimeError("联网检索没有返回可用正文")
    _append_task_route_trace(
        task_id,
        'chatgpt_pool_search',
        'succeeded',
        '联网检索完成',
        conversation_id=str(search_result.get('conversation_id') or ''),
        source_count=len(sources),
    )
    update_task_status(task_id, 'processing', '正在将检索结果整理为图像提示词...', stage='web_search_prompt')
    system_prompt = (
        "你是图像生成提示词整理助手。你会收到用户原始需求、联网检索结论和来源。"
        "请把这些材料整理成图像模型可直接使用的提示词。"
        "只使用检索材料中有依据的信息，不编造事实；来源只用于理解，不要在提示词里写 URL。"
        "只返回合法 JSON 对象，不要 markdown，不要解释。JSON 字段必须包含 full_prompt、compact_prompt、warnings。"
    )
    user_prompt = "\n".join([
        "用户原始需求：",
        "<<<",
        original,
        ">>>",
        "",
        "联网检索结论：",
        "<<<",
        answer,
        ">>>",
        "",
        "来源摘要：",
        json.dumps(sources, ensure_ascii=False),
        "",
        "请输出：",
        "- full_prompt：融合检索结论的完整图像提示词。",
        "- compact_prompt：更短的可投喂版本。",
        "- warnings：不确定、冲突或不适合直接视觉化的点。",
    ])
    chat_response = chat_chatgpt_pool(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        model="auto",
        timeout_seconds=180,
    )
    if not chat_response.get('ok'):
        raise RuntimeError(f"检索结果整理失败：{chat_response.get('error') or '账号池 chat 失败'}")
    content, payload = _chatgpt_pool_chat_content(chat_response)
    data = _extract_json_object_from_text(content)
    full_prompt = str(data.get('full_prompt') or data.get('完整提示词') or '').strip()
    compact_prompt = str(data.get('compact_prompt') or data.get('精简提示词') or data.get('精简可投喂版') or '').strip()
    cfg = get_prompt_skill_config()
    preferred_key = str(cfg.get('default_output') or 'full_prompt')
    optimized = str(data.get(preferred_key) or full_prompt or compact_prompt).strip()
    if not optimized:
        raise RuntimeError("检索结果整理为空")
    return optimized, {
        'prompt_optimized': True,
        'prompt_optimized_by': 'chatgpt_pool_search',
        'prompt_skill_provider': 'chatgpt_pool',
        'prompt_skill_model': payload.get('model') if isinstance(payload, dict) else 'auto',
        'prompt_skill': 'web_search_prompt',
        'prompt_skill_output': preferred_key,
        'original_prompt': original,
        'optimized_prompt': optimized,
        'web_search_answer': answer[:4000],
        'web_search_sources': sources,
        'web_search_conversation_id': str(search_result.get('conversation_id') or ''),
        'web_search_model': search_response.get('model'),
    }


def _format_gpt_failure_error(error):
    """Format final GPT task failures without leaking raw stack traces to users."""
    text = str(error or '').strip()
    if not text:
        return 'GPT 生成失败'

    parts = re.split(r'\s*\|\s*账号池托底失败[:：]\s*', text, maxsplit=1)
    if len(parts) == 2:
        provider_part = re.sub(
            r'^本地\s*(?:GPT\s*)?provider\s*(?:失败|异常)?[:：]\s*',
            '',
            parts[0].strip(),
            flags=re.I,
        )
        return f'{_format_gpt_provider_error(provider_part)}；{_format_gpt_pool_error(parts[1])}'

    if '本地 provider 失败' in text or '本地 GPT provider' in text:
        provider_part = re.sub(
            r'^本地\s*(?:GPT\s*)?provider\s*(?:失败|异常)?[:：]\s*',
            '',
            text,
            flags=re.I,
        )
        return _format_gpt_provider_error(provider_part)

    summary = _first_user_error_line(text)
    return summary[:180] if summary else 'GPT 生成失败'


def _result_image_filenames(result):
    paths = result.get('image_paths') or [result.get('image_path')]
    filenames = []
    for path in paths:
        if not path:
            continue
        filename = os.path.basename(str(path))
        if filename and filename not in filenames:
            filenames.append(filename)
    return filenames


def _missing_task_payload(task_id):
    now = int(time.time())
    return {
        "task_id": task_id,
        "status": "failed",
        "stage": "failed",
        "type": "unknown",
        "prompt": "",
        "params": {},
        "error": "Task not found",
        "message": "任务不存在或已过期，请重新提交。",
        "progress_text": "任务不存在或已过期，请重新提交。",
        "progress": 100,
        "created_at": now,
        "updated_at": now,
        "result_files": [],
        "output_files": [],
        "image_paths": [],
        "image_count": 0,
    }


def _history_task_should_render(status, result_files):
    if result_files:
        return True
    status_key = str(status or '').strip().lower()
    return status_key in {
        'pending',
        'preparing',
        'processing',
        'fallback_running',
        'queued',
        'running',
    }


def _history_page_int(raw_value, default, minimum=0, maximum=500):
    try:
        value = int(raw_value)
    except Exception:
        return default
    return max(minimum, min(value, maximum))


def _history_task_result_files(task):
    result_files = task.get('result_files') or []
    if isinstance(result_files, str):
        try:
            parsed = json.loads(result_files)
            result_files = parsed if isinstance(parsed, list) else []
        except Exception:
            result_files = [result_files]
    if not isinstance(result_files, list):
        result_files = []
    result_files = [str(name or '').strip() for name in result_files if str(name or '').strip()]

    primary_output = str(task.get('result_file') or task.get('output_file') or '').strip()
    if not result_files and primary_output:
        result_files = [primary_output]
    if not primary_output and result_files:
        primary_output = result_files[0]
    return result_files, primary_output


def _history_task_timestamp(task):
    try:
        return int(task.get('created_at') or task.get('timestamp') or 0)
    except Exception:
        return 0


def _history_dedupe_key(task):
    result_files, primary_output = _history_task_result_files(task)
    filename = safe_basename(primary_output or (result_files[0] if result_files else ''))
    if filename:
        return ('file', filename)

    task_id = str(task.get('task_id') or '').strip()
    if task_id:
        return ('task', task_id)

    prompt = str(task.get('prompt') or '')[:120]
    return ('time', _history_task_timestamp(task), prompt)


def _load_database_history_tasks():
    tasks = []
    batch_size = 1000
    offset = 0
    while True:
        batch = get_all_tasks(limit=batch_size, offset=offset)
        if not batch:
            break
        tasks.extend(batch)
        if len(batch) < batch_size:
            break
        offset += len(batch)
    return tasks


def _load_legacy_history_tasks():
    history_path = Path(DIRECTORY) / 'history.jsonl'
    if not history_path.exists():
        return []

    old_tasks = []
    try:
        with open(history_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    task = json.loads(line)
                except Exception:
                    continue
                timestamp = task.get('timestamp', task.get('created_at', 0)) or 0
                output_file = task.get('output_file') or task.get('result_file')
                legacy_key = f"{timestamp}:{safe_basename(output_file)}:{len(old_tasks)}"
                legacy_hash = hashlib.sha1(legacy_key.encode('utf-8')).hexdigest()[:8]
                old_tasks.append({
                    'task_id': f"old_{timestamp}_{legacy_hash}",
                    'status': 'success' if task.get('status') == 'success' else task.get('status', 'failed'),
                    'prompt': task.get('prompt', ''),
                    'params': task.get('params', {}),
                    'output_file': output_file,
                    'result_file': output_file,
                    'error': task.get('error'),
                    'created_at': timestamp,
                    'timestamp': timestamp,
                    'updated_at': int(timestamp or 0) + int(task.get('duration', 0) or 0),
                    'duration': task.get('duration', 0),
                    'type': task.get('type', 'google-gen'),
                    'is_old': True,
                })
    except Exception as e:
        print(f"⚠️ 读取旧 history.jsonl 失败：{e}")
    return old_tasks


def _collect_renderable_history_tasks():
    combined = _load_database_history_tasks() + _load_legacy_history_tasks()
    combined.sort(key=_history_task_timestamp, reverse=True)

    renderable = []
    seen = set()
    for task in combined:
        result_files, _primary_output = _history_task_result_files(task)
        if not _history_task_should_render(task.get('status'), result_files):
            continue
        key = _history_dedupe_key(task)
        if key in seen:
            continue
        seen.add(key)
        renderable.append(task)
    return renderable


def _format_history_task(task):
    result_files, primary_output = _history_task_result_files(task)
    params = task.get('params') if isinstance(task.get('params'), dict) else {}
    image_paths = []
    if task.get('type') == 'gpt-file':
        image_paths = []
    elif task.get('type') in ('gpt', 'gpt-edit'):
        image_paths = [f"/gpt_outputs/{name}" for name in result_files]
    elif result_files:
        image_paths = [f"/image/{name}" for name in result_files]

    return {
        'task_id': task.get('task_id', ''),
        'status': 'success' if task.get('status') == 'succeeded' else task.get('status', 'failed'),
        'prompt': task.get('prompt', ''),
        'params': params,
        'prompt_mode': params.get('prompt_mode'),
        'gpt_provider_route': params.get('gpt_provider_route'),
        'main_model': params.get('main_model'),
        'reasoning_effort': params.get('reasoning_effort'),
        'revised_prompt': params.get('revised_prompt'),
        'revised_prompts': params.get('revised_prompts') if isinstance(params.get('revised_prompts'), list) else [],
        'output_file': primary_output,
        'result_file': primary_output,
        'output_files': result_files,
        'result_files': result_files,
        'image_paths': image_paths,
        'image_count': len(result_files),
        'file_manifest': params.get('file_manifest') if isinstance(params.get('file_manifest'), dict) else None,
        'artifact_type': params.get('artifact_type') or params.get('task_type'),
        'error': task.get('error'),
        'display_error': task.get('display_error') or task.get('error'),
        'error_code': task.get('error_code', ''),
        'error_category': task.get('error_category', ''),
        'raw_error': task.get('raw_error', ''),
        'last_run_id': task.get('last_run_id', ''),
        'run_count': task.get('run_count', 0),
        'created_at': task.get('created_at', task.get('timestamp', 0)),
        'timestamp': task.get('created_at', task.get('timestamp', 0)),
        'updated_at': task.get('updated_at', task.get('created_at', 0)),
        'duration': task.get('duration', 0),
        'type': task.get('type', 'google-gen'),
        'stage': task.get('stage'),
        'progress_text': task.get('progress_text'),
        'progress': task.get('progress', 0),
        'heartbeat_at': task.get('heartbeat_at'),
        'first_byte_at': task.get('first_byte_at'),
        'bytes_received': task.get('bytes_received', 0),
        'transport_error_type': task.get('transport_error_type'),
        'ttfb_ms': task.get('ttfb_ms'),
        'started_at': task.get('started_at'),
        'finished_at': task.get('finished_at'),
        'is_old': task.get('is_old', False),
    }


FAILED_RETRY_STATUSES = {'failed', 'telegram_failed'}
RETRYABLE_TASK_TYPES = {'gpt', 'gpt-file', 'google-gen', 'custom'}
RETRY_PARAM_RESULT_KEYS = {
    'route_trace',
    'revised_prompt',
    'revised_prompts',
    'fallback_source',
    'provider_total_timeout_seconds',
    'prompt_optimized',
    'prompt_optimized_by',
    'prompt_skill_provider',
    'prompt_skill_model',
    'prompt_skill',
    'prompt_skill_output',
    'prompt_skill_latency_seconds',
    'original_prompt',
    'optimized_prompt',
    'prompt_polish_error',
    'web_search_answer',
    'web_search_sources',
    'web_search_conversation_id',
    'web_search_model',
    'file_manifest',
    'file_manifest_url',
    'editable_preview_status',
    'provider_failure',
}


class TaskRetryError(ValueError):
    pass


class GenerationQueueFullError(TaskRetryError):
    pass


def _retry_task_id_prefix(task_type, params=None):
    params = params if isinstance(params, dict) else {}
    if task_type == 'custom':
        return 'custom'
    if task_type == 'gpt-file':
        return 'gpt'
    if task_type == 'google-gen':
        return 'gen'
    if task_type == 'gpt' and not (params.get('prompt_mode') or params.get('gpt_provider_route') or params.get('task_type')):
        return 'gen'
    return 'gpt'


def _make_retry_task_id(task_type, params=None):
    return f"{_retry_task_id_prefix(task_type, params)}_{int(time.time())}_{random.randint(1000, 9999)}"


def _copy_retry_params(original_task, new_task_id):
    params = copy.deepcopy(original_task.get('params') if isinstance(original_task.get('params'), dict) else {})
    for key in RETRY_PARAM_RESULT_KEYS:
        params.pop(key, None)
    previous_attempt = int(params.get('attempt_no') or 1)
    params['retry_of'] = original_task.get('task_id', '')
    params['attempt_no'] = max(2, previous_attempt + 1)
    params['retry_source_status'] = original_task.get('status') or ''
    if original_task.get('error'):
        params['retry_source_error'] = str(original_task.get('error') or '')[:800]
    params['retried_at'] = int(time.time())
    params['retry_task_id'] = new_task_id
    return params


def _is_gpt_image_retry(task_type, params):
    return task_type == 'gpt' and (
        params.get('prompt_mode') or params.get('gpt_provider_route') or params.get('task_type')
    )


def _validate_retry_payload(task_type, params):
    if task_type != 'gpt-file':
        return
    kind = _coerce_gpt_task_type(params.get('task_type') or params.get('artifact_type'))
    if kind not in ('ppt', 'psd'):
        raise TaskRetryError('这个 GPT 文件任务缺少可重跑的文件类型。')
    if kind == 'psd':
        raise TaskRetryError('PSD 任务依赖原始参考图，当前历史记录未保存原图，暂不能直接重跑。')


def _start_retry_thread(task_type, task_id, prompt, params):
    if task_type == 'gpt-file':
        kind = _coerce_gpt_task_type(params.get('task_type') or params.get('artifact_type'))
        target = process_gpt_editable_file_task
        args = (
            task_id,
            kind,
            prompt,
            [],
            _coerce_prompt_mode(params.get('prompt_mode', 'smart')),
            'chatgpt_pool',
            _coerce_bool(params.get('archive_enabled'), True),
            _coerce_bool(params.get('telegram_enabled'), True),
        )
    elif _is_gpt_image_retry(task_type, params):
        target = process_gpt_task
        args = (
            task_id,
            prompt,
            _coerce_image_ratio(params.get('ratio'), '1:1'),
            _coerce_gpt_resolution(params.get('resolution')),
            _coerce_gpt_quality(params.get('quality', 'auto')),
            _coerce_gpt_image_count({'image_count': params.get('image_count')}, prompt),
            _coerce_gpt_moderation(params.get('moderation', 'auto')),
            _coerce_prompt_mode(params.get('prompt_mode', 'smart')),
            _coerce_gpt_main_model(params.get('main_model')),
            _coerce_gpt_reasoning_effort(params.get('reasoning_effort')),
            _coerce_gpt_provider_route(params.get('gpt_provider_route', 'codex')),
            _coerce_use_third_party_api(params.get('use_third_party_api'), params.get('useThirdPartyApi')),
            _coerce_bool(params.get('archive_enabled'), True),
            _coerce_bool(params.get('telegram_enabled'), True),
        )
    elif task_type in ('google-gen', 'gpt'):
        target = process_task
        args = (task_id, prompt, params)
    elif task_type == 'custom':
        target = process_custom_task
        args = (
            task_id,
            prompt,
            _coerce_image_ratio(params.get('ratio'), '1:1'),
            _coerce_gpt_resolution(params.get('resolution')),
            _coerce_gpt_quality(params.get('quality', 'auto')),
            _coerce_gpt_moderation(params.get('moderation', 'auto')),
        )
    else:
        raise TaskRetryError('这个任务类型暂不支持重跑。')
    if not _start_generation_thread(target, args=args):
        message = _generation_busy_message()
        update_task(
            task_id,
            'failed',
            error=message,
            stage='rejected',
            progress_text=message,
            transport_error_type='GenerationQueueFull',
        )
        raise GenerationQueueFullError(message)


def retry_failed_task(original_task):
    if not original_task:
        raise TaskRetryError('找不到要重跑的任务。')
    if original_task.get('is_old'):
        raise TaskRetryError('旧版 history.jsonl 记录不能直接重跑。')
    status = str(original_task.get('status') or '')
    if status not in FAILED_RETRY_STATUSES:
        raise TaskRetryError('只有失败任务可以重跑。')
    task_type = str(original_task.get('type') or 'google-gen')
    if task_type in ('gpt-edit', 'google-edit'):
        raise TaskRetryError('图片编辑任务依赖原始图片/蒙版，当前历史记录未保存完整输入，暂不能直接重跑。')
    if task_type not in RETRYABLE_TASK_TYPES:
        raise TaskRetryError(f'{task_type} 任务暂不支持重跑。')
    prompt = str(original_task.get('prompt') or '').strip()
    if not prompt:
        raise TaskRetryError('这个任务没有可重跑的提示词。')

    task_id = _make_retry_task_id(task_type, original_task.get('params'))
    params = _copy_retry_params(original_task, task_id)
    _validate_retry_payload(task_type, params)
    create_task(task_id, prompt, params, status='queued', task_type=task_type)
    _start_retry_thread(task_type, task_id, prompt, params)
    retry_task = get_task(task_id) or {
        'task_id': task_id,
        'status': 'queued',
        'prompt': prompt,
        'params': params,
        'type': task_type,
    }
    retry_task['ok'] = True
    retry_task['message'] = '已创建重跑任务。'
    retry_task['retry_of'] = original_task.get('task_id', '')
    return retry_task


def _batch_prompt_items(data):
    prompts = data.get('prompts')
    if isinstance(prompts, list):
        items = prompts
    else:
        raw = str(data.get('prompt') or '')
        items = re.split(r'\n\s*\n|\r?\n', raw)
    cleaned = []
    for item in items:
        prompt = str(item or '').strip()
        if prompt:
            cleaned.append(prompt)
    return cleaned


def _batch_task_id(provider, params, index):
    task_type = _batch_task_type(provider, params)
    prefix = _retry_task_id_prefix(task_type, params)
    return f"{prefix}_{int(time.time())}_{random.randint(1000, 9999)}_{index + 1}"


def _batch_task_type(provider, params):
    if provider == 'google':
        return 'google-gen'
    if provider == 'gpt':
        kind = _coerce_gpt_task_type(params.get('gptTaskType') or params.get('task_type'))
        return 'gpt-file' if kind != 'image' else 'gpt'
    return provider


def _make_batch_task_params(provider, incoming_params, prompt, batch_id, index, total, lineage=None):
    incoming_params = incoming_params if isinstance(incoming_params, dict) else {}
    if provider == 'google':
        archive_enabled = _coerce_bool(incoming_params.get('archiveEnabled', incoming_params.get('archive_enabled')), True)
        telegram_enabled = _coerce_bool(incoming_params.get('telegramEnabled', incoming_params.get('telegram_enabled')), True)
        params = {
            'ratio': _coerce_image_ratio(incoming_params.get('ratio'), '1:1'),
            'quality': _coerce_google_quality(incoming_params.get('resolution', incoming_params.get('quality', '2k')), '2k'),
            'model': _coerce_model(incoming_params.get('model', DEFAULT_GOOGLE_IMAGE_MODEL)),
            'max_tokens': _coerce_google_max_tokens(incoming_params.get('maxTokens', incoming_params.get('max_tokens'))),
            'archive_enabled': archive_enabled,
            'telegram_enabled': telegram_enabled,
        }
        temperature = _coerce_google_temperature(incoming_params.get('temperature'))
        if temperature is not None:
            params['temperature'] = temperature
    elif provider == 'gpt':
        task_type = _coerce_gpt_task_type(incoming_params.get('gptTaskType') or incoming_params.get('task_type'))
        gpt_provider_route = 'chatgpt_pool' if task_type != 'image' else _coerce_gpt_provider_route(incoming_params.get('gptProviderRoute', incoming_params.get('gpt_provider_route', 'codex')))
        use_third_party_api = _gpt_route_uses_third_party(gpt_provider_route) or _coerce_use_third_party_api(
            incoming_params.get('useThirdPartyApi'),
            incoming_params.get('use_third_party_api'),
        )
        params = {
            'ratio': _coerce_image_ratio(incoming_params.get('ratio'), '1:1'),
            'resolution': _coerce_gpt_resolution(incoming_params.get('resolution')),
            'quality': _coerce_gpt_quality(incoming_params.get('quality', 'auto')),
            'image_count': _coerce_gpt_image_count({'image_count': incoming_params.get('imageCount', incoming_params.get('image_count'))}, prompt),
            'moderation': _coerce_gpt_moderation(incoming_params.get('moderation', 'auto')),
            'task_type': task_type,
            'prompt_mode': _coerce_prompt_mode(incoming_params.get('promptMode', incoming_params.get('prompt_mode', 'smart'))),
            'gpt_provider_route': gpt_provider_route,
            'main_model': _coerce_gpt_main_model(incoming_params.get('gptMainModel', incoming_params.get('main_model'))),
            'reasoning_effort': _coerce_gpt_reasoning_effort(incoming_params.get('reasoningEffort', incoming_params.get('reasoning_effort'))),
            'archive_enabled': _coerce_bool(incoming_params.get('archiveEnabled', incoming_params.get('archive_enabled')), True),
            'telegram_enabled': _coerce_bool(incoming_params.get('telegramEnabled', incoming_params.get('telegram_enabled')), True),
            'use_third_party_api': use_third_party_api,
        }
    else:
        raise TaskRetryError(f'批量暂不支持 {provider}。')
    if lineage:
        params['lineage'] = lineage
    params.update({
        'batch_id': batch_id,
        'batch_index': index + 1,
        'batch_total': total,
        'batch_control': 'running',
        'batch_status': 'queued',
        'queued_at': int(time.time()),
    })
    return params


def _create_batch_tasks(provider, prompts, params, lineage=None):
    batch_id = f"batch_{int(time.time())}_{random.randint(1000, 9999)}"
    total = len(prompts)
    created = []
    for index, prompt in enumerate(prompts):
        task_params = _make_batch_task_params(provider, params, prompt, batch_id, index, total, lineage=lineage)
        task_type = _batch_task_type(provider, task_params)
        if task_type in ('gpt-edit', 'google-edit') or task_params.get('source_image_count'):
            raise TaskRetryError('批量第一版只支持纯生成任务，暂不支持批量图片编辑。')
        if task_type == 'gpt-file' and _coerce_gpt_task_type(task_params.get('task_type')) == 'psd':
            raise TaskRetryError('PSD 批量任务需要逐项参考图，第一版暂不支持。')
        task_id = _batch_task_id(provider, task_params, index)
        task_params['batch_task_id'] = task_id
        create_task(task_id, prompt, task_params, status='queued', task_type=task_type)
        created.append({
            'task_id': task_id,
            'prompt': prompt,
            'params': task_params,
            'type': task_type,
            'status': 'queued',
        })
    return batch_id, created


def _run_batch_task(task):
    task_id = task['task_id']
    prompt = task['prompt']
    params = task['params']
    task_type = task['type']
    if task_type == 'google-gen':
        process_task(task_id, prompt, params)
    elif task_type == 'gpt':
        process_gpt_task(
            task_id,
            prompt,
            _coerce_image_ratio(params.get('ratio'), '1:1'),
            _coerce_gpt_resolution(params.get('resolution')),
            _coerce_gpt_quality(params.get('quality', 'auto')),
            _coerce_gpt_image_count({'image_count': params.get('image_count')}, prompt),
            _coerce_gpt_moderation(params.get('moderation', 'auto')),
            _coerce_prompt_mode(params.get('prompt_mode', 'smart')),
            _coerce_gpt_main_model(params.get('main_model')),
            _coerce_gpt_reasoning_effort(params.get('reasoning_effort')),
            _coerce_gpt_provider_route(params.get('gpt_provider_route', 'codex')),
            _coerce_use_third_party_api(params.get('use_third_party_api'), params.get('useThirdPartyApi')),
            _coerce_bool(params.get('archive_enabled'), True),
            _coerce_bool(params.get('telegram_enabled'), True),
        )
    elif task_type == 'gpt-file':
        process_gpt_editable_file_task(
            task_id,
            _coerce_gpt_task_type(params.get('task_type')),
            prompt,
            [],
            _coerce_prompt_mode(params.get('prompt_mode', 'smart')),
            'chatgpt_pool',
            _coerce_bool(params.get('archive_enabled'), True),
            _coerce_bool(params.get('telegram_enabled'), True),
        )
    else:
        update_task(task_id, 'failed', error=f'批量暂不支持 {task_type}', stage='failed', progress_text=f'批量暂不支持 {task_type}')


def _batch_task_uses_chatgpt_pool(task):
    if not isinstance(task, dict) or task.get('type') != 'gpt':
        return False
    params = task.get('params') if isinstance(task.get('params'), dict) else {}
    if _coerce_use_third_party_api(params.get('use_third_party_api'), params.get('useThirdPartyApi')):
        return False
    return _coerce_gpt_provider_route(params.get('gpt_provider_route', 'codex')) == 'chatgpt_pool'


def _batch_task_requested_image_count(task):
    params = task.get('params') if isinstance(task.get('params'), dict) else {}
    return _coerce_gpt_image_count({'image_count': params.get('image_count')}, task.get('prompt') or '')


def _batch_chatgpt_pool_parallel_limit(tasks):
    if not tasks or not all(_batch_task_uses_chatgpt_pool(task) for task in tasks):
        return 1
    try:
        status = _collect_chatgpt_pool_status()
        stats = status.get('stats') if isinstance(status.get('stats'), dict) else {}
        capacity = int(stats.get('capacity') or stats.get('available') or 0)
    except Exception as exc:
        print(f"⚠️ 批量任务读取账号池容量失败，改为顺序执行：{exc}")
        capacity = 0
    if capacity <= 0:
        return 1
    per_task_count = max(1, max(_batch_task_requested_image_count(task) for task in tasks))
    by_pool = max(1, capacity // per_task_count)
    return max(1, min(len(tasks), by_pool, _current_generation_limit()))


def _wait_acquire_generation_slot_for_batch(batch_id):
    sem = _GENERATION_SEMAPHORE
    if sem is None:
        return True
    while True:
        control = get_batch_control(batch_id)
        if control == 'canceled':
            return False
        if control == 'paused':
            time.sleep(1)
            continue
        if sem.acquire(timeout=1):
            return True


def _run_batch_task_guarded(batch_id, task):
    while get_batch_control(batch_id) == 'paused':
        time.sleep(1)
    if get_batch_control(batch_id) == 'canceled':
        return False
    current = get_task(task['task_id'])
    if current and current.get('status') == 'canceled':
        return True
    try:
        _run_batch_task(task)
    except Exception as e:
        error = str(e)
        print(f"❌ 批量子任务失败：{task['task_id']} - {error}")
        update_task(task['task_id'], 'failed', error=error, stage='failed', progress_text=error, transport_error_type=type(e).__name__)
    return True


def _run_batch_tasks_parallel(batch_id, tasks, parallel_limit):
    task_queue: queue.Queue = queue.Queue()
    for task in tasks:
        task_queue.put(task)

    def worker(use_parent_slot=False):
        while True:
            try:
                task = task_queue.get_nowait()
            except queue.Empty:
                return
            acquired = False
            try:
                if not use_parent_slot:
                    acquired = _wait_acquire_generation_slot_for_batch(batch_id)
                    if not acquired:
                        return
                if not _run_batch_task_guarded(batch_id, task):
                    return
            finally:
                if acquired:
                    _release_generation_slot()
                task_queue.task_done()

    threads = [
        threading.Thread(target=worker, name=f"batch-{batch_id}-{index}", daemon=True)
        for index in range(max(0, int(parallel_limit or 1) - 1))
    ]
    for thread in threads:
        thread.start()
    worker(use_parent_slot=True)
    for thread in threads:
        thread.join()


def process_batch_tasks(batch_id, tasks):
    parallel_limit = _batch_chatgpt_pool_parallel_limit(tasks)
    mode_text = f"账号池并发 {parallel_limit}" if parallel_limit > 1 else "顺序执行"
    print(f"📦 开始处理批量任务：{batch_id}（{len(tasks)} 个，{mode_text}）")
    if parallel_limit > 1:
        _run_batch_tasks_parallel(batch_id, tasks, parallel_limit)
    else:
        for task in tasks:
            if not _run_batch_task_guarded(batch_id, task):
                break
    if get_batch_control(batch_id) == 'canceled':
        cancel_batch_queued_tasks(batch_id)
    print(f"✅ 批量任务处理完成：{batch_id}")


def _batch_tasks(batch_id):
    tasks = [
        task for task in get_all_tasks(limit=5000, offset=0)
        if isinstance(task.get('params'), dict) and task['params'].get('batch_id') == batch_id
    ]
    tasks.sort(key=lambda task: int((task.get('params') or {}).get('batch_index') or 0))
    return tasks


def get_batch_control(batch_id):
    for task in _batch_tasks(batch_id):
        control = str((task.get('params') or {}).get('batch_control') or '').strip().lower()
        if control:
            return control
    return 'running'


def set_batch_control(batch_id, control):
    control = str(control or '').strip().lower()
    if control not in ('running', 'paused', 'canceled'):
        raise ValueError('无效的批量控制状态')
    tasks = _batch_tasks(batch_id)
    if not tasks:
        return 0
    now = int(time.time())
    for task in tasks:
        params = copy.deepcopy(task.get('params') or {})
        params['batch_control'] = control
        params['batch_control_at'] = now
        update_task_fields(task['task_id'], params=json.dumps(params, ensure_ascii=False))
    return len(tasks)


def cancel_batch_queued_tasks(batch_id):
    changed = 0
    now = int(time.time())
    for task in _batch_tasks(batch_id):
        status = str(task.get('status') or '')
        if status in ('succeeded', 'success', 'succeeded_no_telegram', 'failed', 'telegram_failed', 'canceled'):
            continue
        update_task_fields(
            task['task_id'],
            status='canceled',
            stage='canceled',
            progress_text='批量任务已取消',
            error='',
            transport_error_type='BatchCanceled',
            heartbeat_at=now,
            finished_at=now,
        )
        changed += 1
    return changed


def get_batch_summary(batch_id):
    tasks = _batch_tasks(batch_id)
    counts = {
        'total': len(tasks),
        'queued': 0,
        'processing': 0,
        'succeeded': 0,
        'failed': 0,
        'canceled': 0,
    }
    for task in tasks:
        status = str(task.get('status') or '')
        if status in ('succeeded', 'success', 'succeeded_no_telegram'):
            counts['succeeded'] += 1
        elif status in FAILED_RETRY_STATUSES:
            counts['failed'] += 1
        elif status == 'canceled':
            counts['canceled'] += 1
        elif status in ('queued', 'pending'):
            counts['queued'] += 1
        else:
            counts['processing'] += 1
    control = get_batch_control(batch_id) if tasks else ''
    status = 'completed' if counts['total'] and counts['succeeded'] + counts['failed'] + counts['canceled'] >= counts['total'] else 'running'
    if status == 'running' and control == 'paused':
        status = 'paused'
    if status == 'running' and control == 'canceled':
        status = 'canceling'
    if not counts['total']:
        status = 'missing'
    return {
        'ok': bool(tasks),
        'batch_id': batch_id,
        'status': status,
        'control': control,
        'counts': counts,
        'tasks': [_format_history_task(task) for task in tasks],
    }


def _prompt_chat_english_feed(text):
    text = str(text or '').strip()
    if not text:
        return ''
    return (
        "Image prompt in English: "
        f"{text}\n\n"
        "Keep the subject, composition, atmosphere, lighting, materials, and camera details explicit. "
        "Avoid vague decorative wording."
    )


def _prompt_chat_style_enhanced(text, style):
    text = str(text or '').strip()
    if not text:
        return ''
    style = style if isinstance(style, dict) else {}
    style_text = str(style.get('promptTemplate') or style.get('prompt_style') or style.get('description') or '').strip()
    title = str(style.get('title') or style.get('name') or '').strip()
    if style_text:
        return f"{text}\n\n风格增强：{style_text}"
    if title:
        return f"{text}\n\n风格增强：保持「{title}」的视觉语言，强化构图、光影、材质和情绪一致性。"
    return f"{text}\n\n风格增强：强化画面主体、构图层次、光影方向、材质细节和整体情绪，保持可执行的图像生成描述。"


def _prompt_version_candidates(base, message="", style=None, polished=None):
    """Build formal prompt candidates for the text-node assistant, excluding Original."""
    base = str(base or "").strip()
    message = str(message or "").strip()
    style = style if isinstance(style, dict) else {}
    polished = polished if isinstance(polished, dict) else {}
    candidates = []

    def add_candidate(kind, label, text, badge=""):
        text = str(text or "").strip()
        if not text:
            return
        if kind == "original":
            return
        if text == base and kind in {"compact", "polished"}:
            return
        if any(item["text"] == text for item in candidates):
            return
        candidates.append({
            "id": f"{kind}_{len(candidates) + 1}",
            "kind": kind,
            "label": label,
            "badge": badge,
            "text": text,
            "created_at": int(time.time()),
        })

    full_prompt = polished.get("full_prompt") or polished.get("fullPrompt") or ""
    compact_prompt = polished.get("compact_prompt") or polished.get("compactPrompt") or ""
    generation_base = full_prompt or base
    add_candidate("polished", "完整成片版", full_prompt, "完整")
    add_candidate("compact", "精简投喂版", compact_prompt or _short_text(base, 260), "精简")
    add_candidate("english_feed", "英文投喂版", _prompt_chat_english_feed(generation_base), "英文")
    add_candidate("style_enhanced", "风格增强版", _prompt_chat_style_enhanced(generation_base, style), "风格")
    if message:
        direction_text = "\n\n".join(part for part in [
            generation_base,
            f"方向聚焦：{message}。请围绕这个方向强化主体、构图、光影、材质和避免跑偏的约束。"
        ] if part)
        add_candidate("custom_direction", "自定义方向版", direction_text, "方向")
    return candidates[:5]


def _read_versioned_json(path, root_key):
    try:
        if not path.exists():
            return {"version": 1, root_key: []}
        data = json.loads(path.read_text(encoding='utf-8') or '{}')
        if not isinstance(data, dict):
            return {"version": 1, root_key: []}
        items = data.get(root_key)
        if not isinstance(items, list):
            data[root_key] = []
        data.setdefault("version", 1)
        return data
    except Exception:
        return {"version": 1, root_key: []}


def _write_versioned_json(path, root_key, items):
    PROMPT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, root_key: items}
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)
    return payload


def list_style_presets():
    return _read_versioned_json(STYLE_PRESETS_FILE, "presets").get("presets", [])


def save_style_preset(data):
    name = str(data.get("name") or data.get("title") or "").strip()[:48]
    prompt_style = str(data.get("prompt_style") or data.get("promptTemplate") or data.get("text") or "").strip()
    if not name:
        raise ValueError("风格名称不能为空")
    if not prompt_style:
        raise ValueError("风格内容不能为空")
    now = int(time.time())
    preset_id = str(data.get("id") or f"style_{now}_{random.randint(1000, 9999)}").strip()
    presets = [item for item in list_style_presets() if item.get("id") != preset_id]
    preset = {
        "id": preset_id,
        "name": name,
        "title": name,
        "description": str(data.get("description") or "").strip()[:500],
        "positive_style": str(data.get("positive_style") or prompt_style).strip(),
        "avoid": str(data.get("avoid") or "").strip()[:1000],
        "best_for": str(data.get("best_for") or "").strip()[:500],
        "prompt_style": prompt_style,
        "promptTemplate": prompt_style,
        "tags": data.get("tags") if isinstance(data.get("tags"), list) else [],
        "created_at": int(data.get("created_at") or now),
        "updated_at": now,
        "source": str(data.get("source") or "prompt_drawer"),
    }
    presets.append(preset)
    _write_versioned_json(STYLE_PRESETS_FILE, "presets", presets[-200:])
    return preset


def list_prompt_versions(limit=200):
    versions = _read_versioned_json(PROMPT_VERSIONS_FILE, "versions").get("versions", [])
    return sorted(versions, key=lambda item: int(item.get("created_at") or 0), reverse=True)[:limit]


def save_prompt_version(data):
    text = str(data.get("text") or "").strip()
    if not text:
        raise ValueError("提示词版本内容不能为空")
    now = int(time.time())
    version = {
        "id": str(data.get("id") or f"prompt_version_{now}_{random.randint(1000, 9999)}"),
        "type": str(data.get("type") or data.get("kind") or "custom"),
        "label": str(data.get("label") or data.get("type") or "Prompt Version")[:80],
        "text": text,
        "source_message": str(data.get("source_message") or data.get("message") or "")[:1000],
        "target": data.get("target") if isinstance(data.get("target"), dict) else {},
        "style": data.get("style") if isinstance(data.get("style"), dict) else {},
        "created_at": int(data.get("created_at") or now),
    }
    for key in ("language", "task_type", "intent", "risk_score", "risk_level", "risk_flags", "changed_terms", "warnings", "adapter"):
        value = data.get(key)
        if key in {"risk_flags", "changed_terms", "warnings"} and isinstance(value, list):
            version[key] = value
        elif key in {"task_type", "intent", "adapter"} and isinstance(value, dict):
            version[key] = value
        elif key in {"language", "risk_score", "risk_level"} and value not in (None, ""):
            version[key] = value
    versions = _read_versioned_json(PROMPT_VERSIONS_FILE, "versions").get("versions", [])
    versions.append(version)
    _write_versioned_json(PROMPT_VERSIONS_FILE, "versions", versions[-1000:])
    return version
COMFY_CLIENT_ID = os.environ.get('COMFY_CLIENT_ID', f"tg-mini-app-{uuid.uuid4().hex[:12]}")
COMFY_WORKFLOW_DIR = PROJECT_ROOT / 'workflows'
COMFY_POLL_INTERVAL_SECONDS = float(os.environ.get('COMFY_POLL_INTERVAL_SECONDS', '2'))
COMFY_TASK_TIMEOUT_SECONDS = int(os.environ.get('COMFY_TASK_TIMEOUT_SECONDS', '1800'))
UPSCALE_MODEL_DIR = Path(
    os.environ.get('UPSCALE_MODEL_DIR')
    or (APP_DATA_DIR / 'components' / 'upscale' / 'current' / 'models' if os.environ.get('CANVASHUB_DATA_DIR') else default_upscale_model_dir(PROJECT_ROOT))
).expanduser()
COMFY_RATIO_SIZES = {
    '1:1': (1024, 1024),
    '16:9': (1344, 768),
    '9:16': (768, 1344),
    '4:3': (1152, 864),
    '3:4': (864, 1152),
}

# 确保静态文件始终从 mini-app 目录提供（避免因启动 cwd 不同导致前端 404）
try:
    os.chdir(DIRECTORY)
except Exception as e:
    print(f"⚠️ 切换工作目录失败: {e}")

AUTH_COOKIE_NAME = 'miniapp_auth'
AUTH_HEADER_NAME = 'X-Miniapp-Auth'
TELEGRAM_INIT_DATA_HEADER_NAME = 'X-Telegram-Init-Data'
TELEGRAM_INIT_DATA_ENCODED_HEADER_NAME = 'X-Telegram-Init-Data-Encoded'
AUTH_COOKIE_MAX_AGE = int(os.environ.get('MINIAPP_AUTH_MAX_AGE', str(7 * 24 * 60 * 60)))


def _load_auth_password():
    return get_miniapp_access_password()


AUTH_PASSWORD = _load_auth_password()


def _effective_access_password_configured(settings=None):
    env_password = (
        os.environ.get("MINIAPP_ACCESS_PASSWORD")
        or os.environ.get("MINIAPP_AUTH_PASSWORD")
        or ""
    ).strip()
    if env_password:
        return True
    if settings is None:
        return bool(AUTH_PASSWORD)
    return bool(str(_settings_dict(settings).get("miniapp_access_password") or "").strip())


def _validate_public_mode_password(settings=None, *, server_config=None):
    cfg = server_config or get_server_config()
    if cfg.get("public_mode") and not _effective_access_password_configured(settings):
        raise ValueError("公网模式必须先设置访问密码")


def _server_config_from_settings_snapshot(settings):
    section = _settings_dict(_settings_dict(settings).get("server"))
    public_mode = _coerce_bool(
        os.environ.get("MINIAPP_PUBLIC_MODE")
        or os.environ.get("PUBLIC_MODE")
        or section.get("public_mode"),
        False,
    )
    try:
        port = int(
            os.environ.get("PORT")
            or os.environ.get("MINIAPP_PORT")
            or section.get("port")
            or 18463
        )
    except (TypeError, ValueError):
        port = 18463
    port = max(1, min(65535, port))
    requested_host = str(
        os.environ.get("HOST")
        or os.environ.get("BIND_HOST")
        or os.environ.get("MINIAPP_HOST")
        or section.get("host")
        or ""
    ).strip()
    if public_mode:
        host = requested_host or "0.0.0.0"
    else:
        host = "127.0.0.1"
    return {
        "host": host,
        "requested_host": requested_host,
        "port": port,
        "public_mode": public_mode,
    }

_LOGIN_FAILURES = {}
_LOGIN_FAILURE_LOCK = threading.Lock()
_LOGIN_FAILURE_LIMIT = 5
_LOGIN_FAILURE_WINDOW_SECONDS = 5 * 60
_LOGIN_LOCKOUT_SECONDS = 5 * 60

# Bounded semaphore limiting concurrent generation tasks. Initialized at server
# startup from settings (default 3, clamp 1-8). The thread-start wrapper owns
# acquire/release so business functions can also be called synchronously.
_GENERATION_SEMAPHORE = None
_GENERATION_CONCURRENCY_LIMIT = None


def _init_generation_semaphore():
    """Instantiate the global generation semaphore from config. Called once at startup."""
    global _GENERATION_SEMAPHORE, _GENERATION_CONCURRENCY_LIMIT
    limit = get_max_concurrent_tasks()
    _GENERATION_CONCURRENCY_LIMIT = limit
    _GENERATION_SEMAPHORE = threading.BoundedSemaphore(limit)
    print(f"🎚️ 生成任务并发上限：{limit}")
    return _GENERATION_SEMAPHORE


def _current_generation_limit():
    if _GENERATION_CONCURRENCY_LIMIT is not None:
        return _GENERATION_CONCURRENCY_LIMIT
    return get_max_concurrent_tasks()


def _generation_busy_message():
    return f"生成任务已满（最多 {_current_generation_limit()} 个并发），请稍后重试"


def _generation_busy_payload():
    return {
        "ok": False,
        "error": "GenerationQueueFull",
        "message": _generation_busy_message(),
        "max_concurrent_tasks": _current_generation_limit(),
    }


def _acquire_generation_slot():
    """Try to acquire a generation slot. Returns False (no slot) without blocking."""
    sem = _GENERATION_SEMAPHORE
    if sem is None:
        return True
    acquired = sem.acquire(blocking=False)
    return bool(acquired)


def _release_generation_slot():
    """Release a generation slot. Safe to call even if semaphore is unset."""
    sem = _GENERATION_SEMAPHORE
    if sem is None:
        return
    try:
        sem.release()
    except ValueError:
        pass


def _run_generation_target(target, args, kwargs):
    try:
        target(*args, **kwargs)
    finally:
        _release_generation_slot()


def _start_generation_thread(target, args=(), kwargs=None):
    if not _acquire_generation_slot():
        return None
    kwargs = kwargs or {}
    thread = threading.Thread(
        target=_run_generation_target,
        args=(target, args, kwargs),
        daemon=True,
    )
    try:
        thread.start()
    except Exception:
        _release_generation_slot()
        raise
    return thread


def _auth_enabled():
    return bool(AUTH_PASSWORD)


def _request_client_ip(headers, client_address):
    cf_ip = str(headers.get('CF-Connecting-IP') or '').strip()
    if cf_ip:
        return cf_ip
    xff = str(headers.get('X-Forwarded-For') or '').strip()
    if xff:
        return xff.split(',', 1)[0].strip()
    real_ip = str(headers.get('X-Real-IP') or '').strip()
    if real_ip:
        return real_ip
    try:
        return str(client_address[0] or '').strip()
    except Exception:
        return ''


def _login_lock_state(client_ip, now=None):
    now = now or time.time()
    with _LOGIN_FAILURE_LOCK:
        failures = [
            ts for ts in _LOGIN_FAILURES.get(client_ip, [])
            if now - ts < _LOGIN_FAILURE_WINDOW_SECONDS
        ]
        if failures:
            _LOGIN_FAILURES[client_ip] = failures
        else:
            _LOGIN_FAILURES.pop(client_ip, None)
        if len(failures) < _LOGIN_FAILURE_LIMIT:
            return False, 0
        retry_after = max(1, int(_LOGIN_LOCKOUT_SECONDS - (now - failures[-1])))
        if retry_after <= 0:
            _LOGIN_FAILURES.pop(client_ip, None)
            return False, 0
        return True, retry_after


def _record_login_failure(client_ip, now=None):
    now = now or time.time()
    with _LOGIN_FAILURE_LOCK:
        failures = [
            ts for ts in _LOGIN_FAILURES.get(client_ip, [])
            if now - ts < _LOGIN_FAILURE_WINDOW_SECONDS
        ]
        failures.append(now)
        _LOGIN_FAILURES[client_ip] = failures
        if len(failures) < _LOGIN_FAILURE_LIMIT:
            return False, 0
        retry_after = max(1, int(_LOGIN_LOCKOUT_SECONDS - (now - failures[-1])))
        return True, retry_after


def _clear_login_failures(client_ip):
    with _LOGIN_FAILURE_LOCK:
        _LOGIN_FAILURES.pop(client_ip, None)


def _login_locked_payload(retry_after):
    return {
        "ok": False,
        "error": "TooManyLoginAttempts",
        "message": "登录失败次数过多，请稍后重试",
        "retry_after_seconds": retry_after,
    }


def _sensitive_db_base_paths():
    paths = [
        Path(get_database_path()),
        Path(DIRECTORY) / 'assets.db',
        Path(DIRECTORY) / 'prompt_sources.db',
        Path(DIRECTORY) / 'prompt_library.db',
    ]
    try:
        pool_db = get_chatgpt_pool_config().get('db_path')
        if pool_db:
            paths.append(Path(pool_db))
    except Exception as exc:
        print(f"⚠️ ChatGPT 账号池 DB 路径读取失败: {exc}")
    unique = []
    seen = set()
    for path in paths:
        key = str(path.expanduser())
        if key not in seen:
            unique.append(path.expanduser())
            seen.add(key)
    return unique


def _ensure_db_file_permissions():
    changed = []
    for db_path in _sensitive_db_base_paths():
        try:
            if db_path.parent.exists() and db_path.name == 'accounts.db':
                db_path.parent.chmod(0o700)
            for candidate in (
                db_path,
                Path(f"{db_path}-wal"),
                Path(f"{db_path}-shm"),
                Path(f"{db_path}-journal"),
            ):
                if candidate.exists() and candidate.is_file():
                    candidate.chmod(0o600)
                    changed.append(str(candidate))
        except Exception as exc:
            print(f"⚠️ DB 文件权限收紧失败：{db_path} - {exc}")
    if changed:
        print(f"🔒 已收紧 {len(changed)} 个敏感 DB 文件权限")


def _load_telegram_auth_config():
    try:
        cfg = get_telegram_auth_config()
        bot_token = str(cfg.get('bot_token', '') or '').strip()
        allowed_ids = cfg.get('allowed_user_ids') or set()
        return bot_token, {str(x).strip() for x in allowed_ids if str(x).strip()}
    except Exception as e:
        print(f"⚠️ Telegram 鉴权配置读取失败: {e}")
        return '', set()


TELEGRAM_AUTH_BOT_TOKEN, TELEGRAM_AUTH_ALLOWED_IDS = _load_telegram_auth_config()


def _verify_telegram_init_data(init_data):
    if not init_data or not TELEGRAM_AUTH_BOT_TOKEN:
        return False
    try:
        pairs = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
        data = dict(pairs)
        received_hash = data.pop('hash', '')
        if not received_hash:
            return False

        data_check_string = '\n'.join(f"{key}={value}" for key, value in sorted(data.items()))
        secret_key = hmac.new(
            b'WebAppData',
            TELEGRAM_AUTH_BOT_TOKEN.encode('utf-8'),
            hashlib.sha256,
        ).digest()
        expected_hash = hmac.new(
            secret_key,
            data_check_string.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_hash, received_hash):
            return False

        user_raw = data.get('user') or '{}'
        try:
            user = json.loads(user_raw)
        except Exception:
            user = {}
        user_id = str(user.get('id') or '').strip()
        if TELEGRAM_AUTH_ALLOWED_IDS and user_id not in TELEGRAM_AUTH_ALLOWED_IDS:
            print(f"⚠️ Telegram WebApp 鉴权拒绝：user_id={user_id}")
            return False

        auth_date_raw = str(data.get('auth_date') or '')
        if auth_date_raw.isdigit():
            max_age = int(os.environ.get('MINIAPP_TELEGRAM_AUTH_MAX_AGE', str(7 * 24 * 60 * 60)))
            if int(auth_date_raw) + max_age < int(time.time()):
                return False

        return True
    except Exception as e:
        print(f"⚠️ Telegram initData 校验失败: {e}")
        return False


def _auth_secret():
    seed = f"{AUTH_PASSWORD}|{DIRECTORY}|miniapp-auth-v1"
    return hashlib.sha256(seed.encode('utf-8')).digest()


def _build_auth_cookie_value(issued_at=None):
    issued_at = int(issued_at or time.time())
    payload = str(issued_at)
    signature = hmac.new(_auth_secret(), payload.encode('utf-8'), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _verify_auth_cookie_value(cookie_value):
    if not _auth_enabled():
        return True
    if not cookie_value or '.' not in cookie_value:
        return False
    issued_at_raw, signature = cookie_value.split('.', 1)
    if not issued_at_raw.isdigit() or not signature:
        return False
    expected = hmac.new(_auth_secret(), issued_at_raw.encode('utf-8'), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    issued_at = int(issued_at_raw)
    if issued_at + AUTH_COOKIE_MAX_AGE < int(time.time()):
        return False
    return True


def _new_comfy_session():
    session = requests.Session()
    session.trust_env = False
    session.proxies = {}
    session.headers.update({'User-Agent': 'MiniApp-ComfyProxy/1.0'})
    return session


def _load_comfy_workflow(workflow_name):
    if not workflow_name:
        raise ValueError('缺少工作流名称')

    workflow_path = (COMFY_WORKFLOW_DIR / Path(workflow_name).name).resolve()
    if workflow_path.parent != COMFY_WORKFLOW_DIR.resolve() or not workflow_path.exists():
        raise FileNotFoundError(f'工作流不存在：{workflow_name}')

    with open(workflow_path, 'r', encoding='utf-8') as f:
        return json.load(f), workflow_path.name


def _resolve_comfy_size(ratio):
    return COMFY_RATIO_SIZES.get(str(ratio or '1:1').strip(), COMFY_RATIO_SIZES['1:1'])


def _replace_comfy_tokens(value, replacements):
    if isinstance(value, dict):
        return {k: _replace_comfy_tokens(v, replacements) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_comfy_tokens(v, replacements) for v in value]
    if isinstance(value, str):
        if value in replacements:
            return replacements[value]
        updated = value
        for token, replacement in replacements.items():
            updated = updated.replace(token, str(replacement))
        return updated
    return value


def _decode_data_uri_image(data):
    if not data:
        raise ValueError('缺少图片数据')

    mime_type = 'image/png'
    payload = data
    if ',' in data:
        header, payload = data.split(',', 1)
        if ';base64' not in header:
            raise ValueError('仅支持 base64 data URI')
        if header.startswith('data:'):
            mime_type = header[5:].split(';', 1)[0] or mime_type

    image_bytes = base64.b64decode(payload)
    extension = '.png'
    if '/' in mime_type:
        subtype = mime_type.split('/', 1)[1].split('+', 1)[0].lower()
        if subtype in ('jpeg', 'jpg'):
            extension = '.jpg'
        elif subtype == 'webp':
            extension = '.webp'

    return image_bytes, mime_type, extension


def _upload_comfy_image(image_data):
    image_bytes, mime_type, extension = _decode_data_uri_image(image_data)
    filename = f"miniapp_{int(time.time())}_{random.randint(1000, 9999)}{extension}"

    with _new_comfy_session() as session:
        response = session.post(
            f'{COMFY_BASE_URL}/upload/image',
            files={'image': (filename, image_bytes, mime_type)},
            data={'type': 'input', 'overwrite': 'true'},
            timeout=COMFY_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        result = response.json()

    return result.get('name') or filename


def _prepare_comfy_workflow(workflow, prompt, ratio, uploaded_image_name=None):
    width, height = _resolve_comfy_size(ratio)
    prepared = json.loads(json.dumps(workflow))
    replacements = {
        '{{PROMPT}}': prompt or '',
        '{{WIDTH}}': width,
        '{{HEIGHT}}': height,
        '{{SEED}}': random.randint(1, 2**31 - 1),
        '{{IMAGE}}': uploaded_image_name or '',
    }
    prepared = _replace_comfy_tokens(prepared, replacements)

    for node in prepared.values():
        if not isinstance(node, dict):
            continue

        class_type = node.get('class_type')
        inputs = node.get('inputs') if isinstance(node.get('inputs'), dict) else None
        if not inputs:
            continue

        if class_type == 'EmptyLatentImage':
            inputs['width'] = width
            inputs['height'] = height

        if uploaded_image_name and class_type == 'LoadImage':
            inputs['image'] = uploaded_image_name

    return prepared


def _proxy_comfy_json(method, path, *, params=None, payload=None):
    with _new_comfy_session() as session:
        response = session.request(
            method,
            f'{COMFY_BASE_URL}{path}',
            params=params,
            json=payload,
            timeout=COMFY_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()


def _fetch_comfy_binary(filename, subfolder='', file_type='output'):
    params = {
        'filename': filename,
        'subfolder': subfolder or '',
        'type': file_type or 'output',
    }
    with _new_comfy_session() as session:
        response = session.get(
            f'{COMFY_BASE_URL}/view',
            params=params,
            timeout=COMFY_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.content, response.headers.get('Content-Type', 'application/octet-stream')


def _find_best_comfy_image(outputs):
    final_img = None
    temp_img = None

    if not isinstance(outputs, dict):
        return None

    for node_output in outputs.values():
        images = node_output.get('images') if isinstance(node_output, dict) else None
        if not images:
            continue
        for image in images:
            if not isinstance(image, dict):
                continue
            if image.get('type') == 'output' and final_img is None:
                final_img = image
            elif temp_img is None:
                temp_img = image

    return final_img or temp_img


def _save_task_params(task_id, params):
    update_task_fields(task_id, params=json.dumps(params, ensure_ascii=False))


def _extract_comfy_error(entry):
    status = entry.get('status') if isinstance(entry, dict) else {}
    if isinstance(status, dict):
        for key in ('messages', 'error', 'status_str'):
            value = status.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, list) and value:
                return str(value[-1])
    return 'ComfyUI 任务失败'


def _sync_comfy_task(prompt_id, entry):
    task = get_task(prompt_id)
    if not task:
        return

    status = entry.get('status') if isinstance(entry, dict) else {}
    outputs = entry.get('outputs') if isinstance(entry, dict) else {}
    completed = bool(status.get('completed')) if isinstance(status, dict) else False
    status_str = str(status.get('status_str', '') if isinstance(status, dict) else '').lower()
    comfy_image = _find_best_comfy_image(outputs)

    params = task.get('params') or {}
    updated_params = dict(params)
    if comfy_image:
        updated_params['comfy_image'] = comfy_image

    if completed and comfy_image:
        update_task_status(
            prompt_id,
            'processing',
            'ComfyUI 已完成，正在整理结果...',
            stage='comfy_completed',
            result_file=comfy_image.get('filename'),
            params=json.dumps(updated_params, ensure_ascii=False),
        )
        return {
            'completed': True,
            'image': comfy_image,
            'params': updated_params,
            'progress_text': 'ComfyUI 已完成，正在整理结果...',
        }

    if completed and not comfy_image:
        error_msg = _extract_comfy_error(entry)
        update_task(
            prompt_id,
            'failed',
            error=error_msg,
            stage='failed',
            progress_text=error_msg,
            params=json.dumps(updated_params, ensure_ascii=False),
        )
        return {
            'completed': True,
            'error': error_msg,
            'params': updated_params,
            'progress_text': error_msg,
        }

    progress_text = 'ComfyUI 生成中...'
    if status_str:
        progress_text = f'ComfyUI {status_str}...'
    update_task_status(
        prompt_id,
        'processing',
        progress_text,
        stage='processing',
        params=json.dumps(updated_params, ensure_ascii=False),
    )
    return {
        'completed': False,
        'params': updated_params,
        'progress_text': progress_text,
    }


def _fetch_comfy_history_entry(prompt_id):
    result = _proxy_comfy_json('GET', f'/history/{urllib.parse.quote(prompt_id)}')
    if isinstance(result, dict) and prompt_id not in result and 'outputs' in result:
        result = {prompt_id: result}
    entry = result.get(prompt_id) if isinstance(result, dict) else None
    return result, entry


def _coerce_upscale_tile(value, fallback=256, minimum=64, maximum=2048):
    try:
        parsed = int(value)
    except Exception:
        parsed = fallback
    return max(minimum, min(maximum, parsed))


def _upscale_progress_callback(task_id):
    last_state = {'text': '', 'progress': -1}

    def progress(_ratio, text):
        try:
            ratio = float(_ratio)
        except Exception:
            ratio = 0.0
        if ratio > 1:
            percent = round(max(0.0, min(100.0, ratio)))
        else:
            percent = round(max(0.0, min(1.0, ratio)) * 100)
        message = str(text or '高清放大中...').strip() or '高清放大中...'
        if message == last_state['text'] and percent == last_state['progress']:
            update_task_fields(task_id, heartbeat_at=int(time.time()), progress=percent)
            return
        last_state['text'] = message
        last_state['progress'] = percent
        update_task_status(task_id, 'processing', message, stage='upscaling', progress=percent)

    return progress


def _write_upscale_sidecar(output_path, prompt, params, result_meta):
    sidecar = Path(output_path).with_suffix('.txt')
    lines = [
        str(prompt or '高清放大').strip() or '高清放大',
        '',
        f"task_type: upscale",
        f"model: {result_meta.model}",
        f"scale: {result_meta.scale}x",
        f"input_size: {result_meta.input_width}x{result_meta.input_height}",
        f"output_size: {result_meta.output_width}x{result_meta.output_height}",
        f"device: {result_meta.device}",
    ]
    lineage = params.get('lineage') if isinstance(params.get('lineage'), dict) else {}
    refs = lineage.get('reference_assets') if isinstance(lineage, dict) else []
    if refs:
        lines.append('')
        lines.append('source_refs:')
        for ref in refs[:8]:
            if not isinstance(ref, dict):
                continue
            title = ref.get('title') or ref.get('file') or ref.get('image_url') or ref.get('source_node_id') or 'source'
            lines.append(f"- {title}")
    try:
        write_obsidian_prompt_sidecar(Path(output_path), '\n'.join(lines), txt_path=sidecar)
    except Exception as exc:
        print(f"⚠️ 写入高清放大 sidecar 失败: {exc}")


def process_upscale_task(task_id, prompt, image_data, params):
    """后台线程：本地高清放大任务。"""
    temp_path = None
    run_id = ''
    task_kind = 'upscale'
    task_provider = 'local_upscale'
    task_route = 'spandrel'
    try:
        model_name = normalize_upscale_model(params.get('model'))
        model_label = UPSCALE_MODELS.get(model_name, {}).get('label', model_name)
        archive_enabled = True
        telegram_enabled = _coerce_bool(params.get('telegram_enabled', params.get('telegramEnabled')), True)
        params = dict(params or {})
        params['archive_enabled'] = archive_enabled
        params['telegram_enabled'] = telegram_enabled
        params['model'] = model_name
        params['scale'] = 4
        _merge_task_params(task_id, params)

        run_id = _start_generation_audit(
            task_id,
            task_kind,
            prompt,
            params,
            provider=task_provider,
            route=task_route,
            stage='preparing',
        )
        update_task_status(task_id, 'preparing', '正在准备高清放大...', stage='preparing', progress=4)
        send_status_notification(task_id, f'已提交高清放大：{model_label}', '✅')

        image_bytes, _mime_type, extension = _decode_data_uri_image(image_data)
        with tempfile.NamedTemporaryFile(delete=False, suffix=extension or '.png') as tmp:
            tmp.write(image_bytes)
            temp_path = tmp.name

        now = datetime.now()
        timestamp = now.strftime('%Y%m%d_%H%M%S')
        model_slug = re.sub(r'[^a-zA-Z0-9]+', '_', model_name).strip('_').lower() or 'upscale'
        filename = f"upscale_{model_slug}_{timestamp}_{random.randint(1000, 9999)}.png"
        output_dir = daily_output_dir(now)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename

        update_task_status(task_id, 'processing', '正在载入高清放大模型...', stage='loading_model', progress=8)
        _record_generation_event(task_id, 'provider_call_started', '开始执行本地高清放大', stage='loading_model', payload={'provider': task_provider, 'route': task_route, 'model': model_name})
        result_meta = upscale_image_file(
            Path(temp_path),
            output_path,
            model_name=model_name,
            model_dir=UPSCALE_MODEL_DIR,
            device=params.get('device') or 'auto',
            tile_size=_coerce_upscale_tile(params.get('tile_size', params.get('tileSize')), 256),
            tile_overlap=_coerce_upscale_tile(params.get('tile_overlap', params.get('tileOverlap')), 32, minimum=0, maximum=256),
            progress=_upscale_progress_callback(task_id),
        )

        _write_upscale_sidecar(output_path, prompt, params, result_meta)
        save_thumbnail(str(output_path), filename)

        _merge_task_params(task_id, {
            'model': result_meta.model,
            'scale': result_meta.scale,
            'device': result_meta.device,
            'input_size': f'{result_meta.input_width}x{result_meta.input_height}',
            'output_size': f'{result_meta.output_width}x{result_meta.output_height}',
            'archive_dir': str(output_dir),
        })

        telegram_success = False
        if telegram_enabled:
            update_task_status(task_id, 'processing', '正在发送高清结果到 Telegram...', stage='sending_telegram', progress=96)
            _record_generation_event(task_id, 'telegram_send_started', '开始发送高清放大结果到 Telegram', stage='sending_telegram')
            caption = f"高清放大 | {model_label} | {result_meta.input_width}x{result_meta.input_height} -> {result_meta.output_width}x{result_meta.output_height}"
            prompt_line = str(prompt or '').strip()
            if prompt_line:
                caption = f"{caption}\n{prompt_line[:400]}"
            try:
                send_tg_document(output_path, caption=caption[:1000])
                telegram_success = True
            except Exception as exc:
                print(f"❌ 高清放大 Telegram 发送失败：{exc}")
        else:
            update_task_status(task_id, 'processing', 'Telegram 已关闭，正在整理高清结果...', stage='saving', progress=98)
            _record_generation_event(task_id, 'telegram_send_skipped', '已按节点开关跳过 Telegram', stage='saving')

        if telegram_success or not telegram_enabled:
            progress_text = '高清放大完成' if telegram_enabled else '高清放大完成，已按节点开关跳过 Telegram'
            final_status = 'succeeded' if telegram_enabled else 'succeeded_no_telegram'
        else:
            progress_text = '高清放大完成，但 Telegram 发送失败'
            final_status = 'succeeded_no_telegram'

        _finalize_generation_task(
            task_id,
            final_status,
            run_id=run_id,
            provider=task_provider,
            route=task_route,
            task_type=task_kind,
            result_file=filename,
            stage='done',
            progress_text=progress_text,
            result_files=[filename],
            image_count=1,
            extra={
                'model': result_meta.model,
                'scale': result_meta.scale,
                'device': result_meta.device,
                'output_size': f'{result_meta.output_width}x{result_meta.output_height}',
            },
        )
        _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload={'provider': task_provider, 'route': task_route, 'model': model_name, 'scale': result_meta.scale})
        send_status_notification(task_id, '✅ 高清放大完成！', '🎉')
    except Exception as e:
        raw_error_msg = str(e)
        error_type = type(e).__name__
        error_info = _translate_generation_failure(
            task_id,
            raw_error_msg,
            provider=task_provider,
            route=task_route,
            task_type=task_kind,
            stage='failed',
            exception_name=error_type,
        )
        display = error_info.get('display_error') or raw_error_msg
        if isinstance(e, UpscaleRuntimeError):
            display = raw_error_msg
            error_info['display_error'] = display
        _finalize_generation_task(
            task_id,
            'failed',
            run_id=run_id,
            provider=task_provider,
            route=task_route,
            task_type=task_kind,
            stage='failed',
            progress_text=display,
            error_info=error_info,
            error_type=error_type,
        )
        send_status_notification(task_id, f'❌ 高清放大失败：{display[:100]}', '⚠️')
        print(f"❌ 高清放大任务失败：{task_id} - {raw_error_msg}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass


def _send_comfy_result(task_id, prompt, workflow, ratio, comfy_image, params):
    temp_path = None
    filename = str(comfy_image.get('filename', '')).strip()
    if not filename:
        raise RuntimeError('ComfyUI 输出缺少 filename')

    subfolder = comfy_image.get('subfolder', '')
    file_type = comfy_image.get('type', 'output')

    update_task_status(task_id, 'processing', 'ComfyUI 已完成，正在发送到 Telegram...', stage='sending_telegram')
    send_status_notification(task_id, 'ComfyUI 已完成，正在发送图片...', '📤')

    try:
        image_bytes, _ = _fetch_comfy_binary(filename, subfolder, file_type)
        suffix = Path(filename).suffix or '.png'
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(image_bytes)
            temp_path = tmp.name

        caption_parts = [part for part in (f'ComfyUI {workflow}'.strip(), ratio) if part]
        caption = ' | '.join(caption_parts)
        if prompt:
            caption = f"{caption}\n{prompt}" if caption else prompt
        caption = caption[:500] + '...' if len(caption) > 500 else caption

        sent = send_telegram(None, temp_path, caption)
        params = dict(params or {})
        params['comfy_image'] = comfy_image
        params['comfy_telegram_sent'] = bool(sent)
        params['comfy_telegram_sent_at'] = int(time.time()) if sent else None

        if sent:
            update_task(
                task_id,
                'succeeded',
                result_file=filename,
                stage='done',
                progress_text='ComfyUI 生成成功',
                params=json.dumps(params, ensure_ascii=False),
            )
            send_status_notification(task_id, '✅ ComfyUI 图片生成成功！', '🎉')
        else:
            update_task(
                task_id,
                'succeeded_no_telegram',
                result_file=filename,
                stage='done',
                progress_text='ComfyUI 已生成，但 Telegram 发送失败',
                params=json.dumps(params, ensure_ascii=False),
            )
            send_status_notification(task_id, '❌ ComfyUI 已生成，但 Telegram 发送失败', '⚠️')
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass


def process_comfy_task(task_id, prompt, workflow, ratio):
    deadline = time.time() + COMFY_TASK_TIMEOUT_SECONDS
    update_task_status(task_id, 'processing', 'ComfyUI 任务已提交，等待执行...', stage='queued')
    send_status_notification(task_id, f'已提交 ComfyUI 任务：{workflow}', '✅')
    last_notified_text = None

    while time.time() < deadline:
        try:
            _, entry = _fetch_comfy_history_entry(task_id)
            if isinstance(entry, dict):
                sync_state = _sync_comfy_task(task_id, entry)
                progress_text = sync_state.get('progress_text')
                if progress_text and progress_text != last_notified_text:
                    status_text = str(entry.get('status', {}).get('status_str', '')).lower()
                    icon = '⏳'
                    if status_text and status_text not in ('success', 'succeeded'):
                        icon = '🤖'
                    send_status_notification(task_id, progress_text, icon)
                    last_notified_text = progress_text
                if sync_state.get('completed'):
                    comfy_image = sync_state.get('image')
                    if comfy_image:
                        params = sync_state.get('params') or {}
                        if not params.get('comfy_telegram_sent'):
                            _send_comfy_result(task_id, prompt, workflow, ratio, comfy_image, params)
                        return
                    return
            else:
                progress_text = 'ComfyUI 排队中...'
                update_task_status(task_id, 'processing', progress_text, stage='queued')
                if progress_text != last_notified_text:
                    send_status_notification(task_id, progress_text, '⏳')
                    last_notified_text = progress_text
        except Exception as e:
            msg = f'等待 ComfyUI 状态失败：{str(e)[:120]}'
            update_task_status(task_id, 'processing', msg, stage='waiting_history')
            if msg != last_notified_text:
                send_status_notification(task_id, msg, '⚠️')
                last_notified_text = msg

        time.sleep(COMFY_POLL_INTERVAL_SECONDS)

    update_task(
        task_id,
        'failed',
        error='ComfyUI 任务超时',
        stage='failed',
        progress_text='ComfyUI 任务超时',
    )
    send_status_notification(task_id, '❌ ComfyUI 任务超时', '⚠️')


def _resolve_download_file(filename):
    if not filename:
        return None

    for downloads_root in image_lookup_roots():
        direct_path = downloads_root / filename
        if direct_path.exists():
            return direct_path

        today_path = downloads_root / time.strftime('%Y-%m-%d') / filename
        if today_path.exists():
            return today_path

        try:
            subdirs = sorted(
                (p for p in downloads_root.iterdir() if p.is_dir()),
                key=lambda p: p.name,
                reverse=True,
            )
        except FileNotFoundError:
            continue

        for subdir in subdirs:
            candidate = subdir / filename
            if candidate.exists():
                return candidate

    return None


def _resolve_archive_image_file(rel_path):
    raw = urllib.parse.unquote(str(rel_path or '').strip()).lstrip('/\\')
    if not raw:
        return None
    normalized = raw.replace("\\", "/")
    parts = normalized.split("/", 1)
    requested_key = parts[0] if len(parts) == 2 else ""
    requested_rel = parts[1] if len(parts) == 2 else normalized
    for root_key, root_path in archive_scan_roots():
        candidate_rel = requested_rel if requested_key == root_key else normalized
        candidate = (root_path / candidate_rel).expanduser()
        try:
            resolved = candidate.resolve()
            root = root_path.expanduser().resolve()
        except Exception:
            continue
        if resolved != root and root not in resolved.parents:
            continue
        if not resolved.is_file():
            continue
        if resolved.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
            continue
        return resolved
    return None


def _resolve_download_image(filename):
    """Compatibility wrapper for history original-image export."""
    return _resolve_download_file(filename)


def _load_telegram_notify_config():
    telegram_cfg = get_telegram_config()
    return (
        telegram_cfg.get('bot_token', ''),
        telegram_cfg.get('chat_id', ''),
        telegram_cfg.get('proxy_url', ''),
    )


def _path_diagnostics(path_value, expect_dir=False):
    path = Path(path_value).expanduser()
    exists = path.exists()
    is_dir = path.is_dir()
    parent = path if is_dir else path.parent
    return {
        "path": str(path),
        "exists": exists,
        "is_dir": is_dir,
        "is_file": path.is_file(),
        "parent_exists": parent.exists(),
        "writable": os.access(str(path if exists else parent), os.W_OK) if (exists or parent.exists()) else False,
        "expected_type": "directory" if expect_dir else "file",
    }


def _collect_chatgpt_pool_status():
    """Return safe sidecar health/config without exposing the Bearer auth key."""
    cfg = get_chatgpt_pool_config(ensure_auth_key=True)
    status = get_chatgpt_pool_public_config()
    status.update({
        "online": False,
        "health_error": "",
        "stats": {},
    })
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.get(f"{cfg['base_url'].rstrip('/')}/health", timeout=2)
        data = response.json() if response.text else {}
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}")
        status["online"] = bool(data.get("ok", True)) if isinstance(data, dict) else True
        if isinstance(data, dict):
            status["stats"] = data.get("stats") if isinstance(data.get("stats"), dict) else {}
            status["model"] = data.get("model") or status.get("generation_model")
            stats = status["stats"]
            status["summary"] = {
                "total": int(stats.get("total") or 0),
                "active": int(stats.get("active") or 0),
                "available": int(stats.get("available") or 0),
                "inflight": int(stats.get("inflight") or 0),
                "limited": int(stats.get("limited") or 0),
                "abnormal": int(stats.get("abnormal") or 0),
                "refreshable": int(stats.get("refreshable") or 0),
            }
    except Exception as exc:
        status["health_error"] = str(exc)[:240]
    return status


def _chatgpt_pool_request(method, path, payload=None, timeout=None):
    cfg = get_chatgpt_pool_config(ensure_auth_key=True)
    auth_key = str(cfg.get("auth_key") or "").strip()
    if not auth_key:
        raise RuntimeError("ChatGPT pool auth key missing")
    endpoint = f"{str(cfg.get('base_url') or '').rstrip('/')}{path}"
    session = requests.Session()
    session.trust_env = False
    headers = {
        "Authorization": f"Bearer {auth_key}",
        "Content-Type": "application/json",
    }
    response = session.request(
        str(method or "GET").upper(),
        endpoint,
        headers=headers,
        json=payload if payload is not None else None,
        timeout=timeout or min(30, int(cfg.get("timeout_seconds") or 30)),
    )
    data = response.json() if response.text else {}
    if response.status_code >= 400:
        detail = data.get("detail") if isinstance(data, dict) else ""
        if isinstance(detail, dict):
            detail = detail.get("error") or detail.get("message") or detail
        message = detail
        if not message and isinstance(data, dict):
            message = data.get("error") or data.get("message")
        if not message:
            message = response.text[:300] or f"HTTP {response.status_code}"
        raise RuntimeError(str(message))
    return data if isinstance(data, dict) else {"ok": True, "data": data}


def _chatgpt_pool_safe_auth_candidates():
    """Return local Codex auth files that diagnostics already considers valid."""
    status = get_gpt_provider_auth_status()
    candidates = []
    for item in status.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        if not item.get("exists") or not item.get("readable") or not item.get("has_access_token"):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        try:
            candidates.append(Path(path).expanduser().resolve())
        except Exception:
            continue
    selected = str(status.get("selected_path") or "").strip()
    if selected:
        try:
            selected_path = Path(selected).expanduser().resolve()
            if selected_path not in candidates and selected_path.exists():
                candidates.insert(0, selected_path)
        except Exception:
            pass
    return candidates


def _chatgpt_pool_build_local_auth_account(requested_path=""):
    """Load one safe local Codex auth file and normalize it for sidecar import."""
    candidates = _chatgpt_pool_safe_auth_candidates()
    if not candidates:
        raise RuntimeError("未找到可导入的本机 Codex Auth 文件")

    if requested_path:
        target = Path(str(requested_path)).expanduser().resolve()
        if target not in candidates:
            raise RuntimeError("只能导入本机诊断页识别到的 Codex Auth 文件")
    else:
        target = candidates[0]

    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"本机 Auth JSON 读取失败：{target}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("本机 Auth JSON 格式错误")

    token_obj = raw.get("tokens") if isinstance(raw.get("tokens"), dict) else raw
    access_token = str(token_obj.get("access_token") or raw.get("access_token") or "").strip()
    refresh_token = str(token_obj.get("refresh_token") or raw.get("refresh_token") or "").strip()
    id_token = str(token_obj.get("id_token") or raw.get("id_token") or "").strip()
    if not access_token:
        raise RuntimeError("本机 Auth 缺少 access_token")
    if not refresh_token:
        raise RuntimeError("本机 Auth 缺少 refresh_token，无法加入可自动续期的账号池")

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token,
        "account_id": str(token_obj.get("account_id") or raw.get("account_id") or "").strip(),
        "email": str(token_obj.get("email") or raw.get("email") or "").strip(),
        "source_type": "local_codex_auth",
    }, str(target)


def _chatgpt_pool_open_authorize_url_clean(authorize_url):
    """Open an OpenAI authorize URL in an isolated Chrome profile."""
    url = str(authorize_url or "").strip()
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    if parsed.scheme != "https" or parsed.netloc != "auth.openai.com" or parsed.path != "/api/accounts/authorize":
        raise RuntimeError("只能打开 OpenAI 授权链接")
    if (query.get("client_id") or [""])[0] != "app_2SKx67EdpoN0G6j64rFvigXD":
        raise RuntimeError("授权链接 client_id 不匹配")
    if (query.get("redirect_uri") or [""])[0] != "https://platform.openai.com/auth/callback":
        raise RuntimeError("授权链接 redirect_uri 不匹配")

    profile_dir = Path(tempfile.gettempdir()) / "tg-mini-app-chatgpt-pool-oauth-chrome"
    profile_dir.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            "open",
            "-na",
            "Google Chrome",
            "--args",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--disable-extensions",
            "--new-window",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"ok": True, "profile_dir": str(profile_dir)}


def _chatgpt_pool_account_by_id(account_id):
    target_id = str(account_id or "").strip()
    if not target_id:
        raise RuntimeError("缺少账号 ID")
    accounts_payload = _chatgpt_pool_request("GET", "/accounts")
    accounts = accounts_payload.get("items") if isinstance(accounts_payload, dict) else []
    account = next(
        (
            item
            for item in accounts or []
            if isinstance(item, dict)
            and str(item.get("account_id") or "").strip() == target_id
        ),
        None,
    )
    if not account:
        raise RuntimeError("账号不存在或已删除")
    return account


def _chatgpt_pool_verification_profile_dir(account_or_id):
    root = APP_DATA_DIR / "chatgpt_pool" / "verify_chrome_profiles"
    email = ""
    if isinstance(account_or_id, dict):
        email = str(account_or_id.get("email") or "").strip()
        raw_key = (
            str(account_or_id.get("user_id") or "").strip()
            or email
            or str(account_or_id.get("account_id") or "").strip()
        )
    else:
        raw_key = str(account_or_id or "").strip()
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw_key)[:96] or "account"
    stable_dir = root / safe_id
    if stable_dir.exists() or not email or not root.exists():
        return stable_dir
    try:
        for candidate in root.iterdir():
            prefs = candidate / "Default" / "Preferences"
            if not prefs.exists() or not candidate.is_dir():
                continue
            text = prefs.read_text(encoding="utf-8", errors="ignore")
            if email in text:
                return candidate
    except Exception:
        pass
    return stable_dir


def _chatgpt_pool_find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _chatgpt_pool_complete_account_verification(account_id, debug_port=None):
    target_id = str(account_id or "").strip()
    if not target_id:
        raise RuntimeError("缺少账号 ID")
    account = _chatgpt_pool_account_by_id(target_id)
    email = str(account.get("email") or "").strip()
    profile_dir = _chatgpt_pool_verification_profile_dir(account)
    data = _chatgpt_pool_request(
        "POST",
        "/accounts/update",
        {
            "account_id": target_id,
            "status": "正常",
            "image_quota_unknown": True,
            "restore_at": "",
            "last_refresh_error": "",
        },
    )
    if isinstance(data, dict):
        data.update({
            "ok": True,
            "account_id": target_id,
            "email": email,
            "profile_dir": str(profile_dir),
            "message": "账号已恢复为正常，后续请求使用轻量 HTTP 链路",
        })
    return data


def _collect_system_diagnostics():
    telegram_cfg = get_telegram_config()
    storage_cfg = get_storage_config()
    server_cfg = get_server_config()
    database_path = get_database_path()
    prompt_skill_cfg = get_prompt_skill_config()
    third_party_cfg = get_third_party_image_config()
    managed_codex_cfg = get_managed_codex_oauth_status()

    return {
        "ok": True,
        "auth": {
            "password_enabled": _auth_enabled(),
            "telegram_init_data_enabled": bool(TELEGRAM_AUTH_BOT_TOKEN),
            "allowed_user_count": len(TELEGRAM_AUTH_ALLOWED_IDS),
        },
        "server": {
            "host": SERVER_HOST,
            "port": PORT,
            "url": f"http://{SERVER_HOST}:{PORT}",
            "public_mode": bool(server_cfg.get("public_mode")),
            "configured_host": server_cfg.get("host", SERVER_HOST),
            "configured_port": server_cfg.get("port", PORT),
            "password_required": bool(server_cfg.get("public_mode")),
            "password_configured": bool(get_miniapp_access_password()),
            "restart_required": (
                str(server_cfg.get("host", SERVER_HOST)) != str(SERVER_HOST)
                or int(server_cfg.get("port", PORT)) != int(PORT)
            ),
        },
        "telegram": {
            "bot_token_configured": bool(telegram_cfg.get("bot_token")),
            "chat_id_configured": bool(telegram_cfg.get("chat_id")),
            "proxy_url": telegram_cfg.get("proxy_url", ""),
            "delivery_method": "sendDocument",
        },
        "yunwu": {
            "api_key_configured": bool(get_yunwu_api_key()),
            "base_url": get_yunwu_api_base_url(),
        },
        "nano_banana_api": {
            "api_key_configured": bool(get_nano_banana_api_key()),
            "base_url": get_nano_banana_api_base_url(),
        },
        "third_party_image_api": {
            "api_key_configured": bool(third_party_cfg.get("api_key_configured")),
            "base_url": third_party_cfg.get("base_url", ""),
            "model": third_party_cfg.get("model", ""),
            "generate_path": third_party_cfg.get("generate_path", ""),
            "edit_path": third_party_cfg.get("edit_path", ""),
            "format": third_party_cfg.get("format", "png"),
            "timeout_seconds": third_party_cfg.get("timeout_seconds", 900),
        },
        "storage": {
            "image_archive_dir": _path_diagnostics(storage_cfg["image_archive_dir"], expect_dir=True),
            "source_image_dir": _path_diagnostics(storage_cfg["source_image_dir"], expect_dir=True),
            "archive_read_roots": [{"key": key, "path": str(path)} for key, path in archive_scan_roots()],
            "source_image_read_roots": [{"key": key, "path": str(path)} for key, path in source_image_roots()],
        },
        "database": {
            "tasks_db": _path_diagnostics(database_path),
        },
        "gpt_provider": get_gpt_provider_auth_status(),
        "managed_codex_oauth": managed_codex_cfg,
        "chatgpt_pool": _collect_chatgpt_pool_status(),
        "prompt_skill": {
            "provider": prompt_skill_cfg.get("provider", ""),
            "skill": prompt_skill_cfg.get("skill", ""),
            "model": prompt_skill_cfg.get("model", ""),
            "reasoning_effort": prompt_skill_cfg.get("reasoning_effort", ""),
            "default_output": prompt_skill_cfg.get("default_output", ""),
        },
    }


def _collect_gpt_runtime_config():
    provider_cfg = get_gpt_provider_config()
    return {
        "ok": True,
        "gpt_provider": {
            "image_main_model": provider_cfg.get("image_main_model") or DEFAULT_GPT_IMAGE_MAIN_MODEL,
            "reasoning_effort": provider_cfg.get("reasoning_effort") or DEFAULT_GPT_REASONING_EFFORT,
            "transport_mode": provider_cfg.get("transport_mode") or DEFAULT_GPT_TRANSPORT_MODE,
            "total_timeout_seconds": provider_cfg.get("total_timeout_seconds") or DEFAULT_GPT_PROVIDER_TOTAL_TIMEOUT_SECONDS,
            "allowed_image_main_models": provider_cfg.get("allowed_image_main_models") or sorted(VALID_GPT_MAIN_MODELS),
            "allowed_reasoning_efforts": provider_cfg.get("allowed_reasoning_efforts") or sorted(VALID_GPT_REASONING_EFFORTS),
            "allowed_transport_modes": provider_cfg.get("allowed_transport_modes") or sorted(VALID_GPT_TRANSPORT_MODES),
        },
    }


def _collect_system_settings():
    """Return editable settings without exposing secret values."""
    telegram_cfg = get_telegram_config()
    storage_cfg = get_storage_config()
    server_cfg = get_server_config()
    provider_cfg = get_gpt_provider_config()
    managed_codex_cfg = get_managed_codex_oauth_public_config()
    pool_cfg = get_chatgpt_pool_public_config()
    prompt_cfg = get_prompt_skill_config()
    third_party_cfg = get_third_party_image_config()
    proxy_cfg = get_proxy_config()
    prompt_source_proxy_cfg = get_proxy_config("prompt_source")
    return {
        "ok": True,
        "settings": {
            "auth": {
                "miniapp_access_password_configured": bool(get_miniapp_access_password()),
            },
            "server": {
                "host": server_cfg.get("host", SERVER_HOST),
                "port": server_cfg.get("port", PORT),
                "public_mode": bool(server_cfg.get("public_mode")),
                "runtime_host": SERVER_HOST,
                "runtime_port": PORT,
                "restart_required": (
                    str(server_cfg.get("host", SERVER_HOST)) != str(SERVER_HOST)
                    or int(server_cfg.get("port", PORT)) != int(PORT)
                ),
            },
            "telegram": {
                "bot_token_configured": bool(telegram_cfg.get("bot_token")),
                "chat_id": telegram_cfg.get("chat_id", ""),
                "allowed_user_ids": sorted(TELEGRAM_AUTH_ALLOWED_IDS),
                "proxy_url": telegram_cfg.get("proxy_url", ""),
            },
            "yunwu": {
                "api_key_configured": bool(get_yunwu_api_key()),
                "base_url": get_yunwu_api_base_url(),
            },
            "nano_banana_api": {
                "api_key_configured": bool(get_nano_banana_api_key()),
                "base_url": get_nano_banana_api_base_url(),
            },
            "third_party_image_api": {
                "api_key_configured": bool(third_party_cfg.get("api_key_configured")),
                "base_url": third_party_cfg.get("base_url", ""),
                "model": third_party_cfg.get("model", ""),
                "generate_path": third_party_cfg.get("generate_path", ""),
                "edit_path": third_party_cfg.get("edit_path", ""),
                "format": third_party_cfg.get("format", "png"),
                "timeout_seconds": third_party_cfg.get("timeout_seconds", 900),
            },
            "paths": {
                "image_archive_dir": str(storage_cfg["image_archive_dir"]),
                "source_image_dir": str(storage_cfg["source_image_dir"]),
                "tasks_db": str(get_database_path()),
                "archive_read_roots": [{"key": key, "path": str(path)} for key, path in archive_scan_roots()],
                "source_image_read_roots": [{"key": key, "path": str(path)} for key, path in source_image_roots()],
            },
            "managed_codex_oauth": managed_codex_cfg,
            "chatgpt_pool": pool_cfg,
            "prompt_skill": prompt_cfg,
            "proxy": proxy_cfg,
            "prompt_source_proxy": prompt_source_proxy_cfg,
        },
    }


def _settings_dict(value):
    return value if isinstance(value, dict) else {}


def _clean_text(value, max_len=4096):
    return str(value or "").strip()[:max_len]


def _clean_text_list(value):
    if isinstance(value, (list, tuple, set)):
        return [_clean_text(item, 128) for item in value if _clean_text(item, 128)]
    text = _clean_text(value, 4096)
    if not text:
        return []
    return [_clean_text(item, 128) for item in re.split(r"[\n,，\s]+", text) if _clean_text(item, 128)]


def _patch_text(target, source, key, max_len=4096, allow_empty=True):
    if key not in source:
        return
    value = _clean_text(source.get(key), max_len=max_len)
    if value or allow_empty:
        target[key] = value


def _patch_secret(target, source, key, clear_key=None, max_len=8192):
    clear_key = clear_key or f"clear_{key}"
    if _coerce_bool(source.get(clear_key), False):
        target.pop(key, None)
        return
    if key not in source:
        return
    value = _clean_text(source.get(key), max_len=max_len)
    if value:
        target[key] = value


def _sanitize_system_settings_patch(payload):
    if not isinstance(payload, dict):
        return None
    data = _settings_dict(payload.get("settings")) or payload
    settings = load_app_settings()
    if not isinstance(settings, dict):
        settings = {}

    _patch_secret(settings, data, "miniapp_access_password")
    _patch_secret(settings, data, "yunwu_api_key")
    _patch_text(settings, data, "yunwu_api_base_url", max_len=2048)

    nano_banana = _settings_dict(settings.get("nano_banana_api")).copy()
    nano_banana_data = _settings_dict(data.get("nano_banana_api"))
    _patch_secret(nano_banana, nano_banana_data, "api_key")
    _patch_text(nano_banana, nano_banana_data, "base_url", max_len=2048)
    if _coerce_bool(nano_banana_data.get("clear_api_key"), False):
        settings.pop("nano_banana_api_key", None)
        settings.pop("yunwu_api_key", None)
    if "base_url" in nano_banana_data and not _clean_text(nano_banana_data.get("base_url"), max_len=2048):
        settings.pop("nano_banana_api_base_url", None)
        settings.pop("yunwu_api_base_url", None)
    if nano_banana_data:
        settings["nano_banana_api"] = nano_banana

    server = _settings_dict(settings.get("server")).copy()
    server_data = _settings_dict(data.get("server"))
    if "public_mode" in server_data:
        server["public_mode"] = _coerce_bool(server_data.get("public_mode"), False)
    _patch_text(server, server_data, "host", max_len=255)
    if "port" in server_data:
        try:
            server["port"] = max(1, min(65535, int(server_data.get("port"))))
        except (TypeError, ValueError):
            pass
    if server_data:
        settings["server"] = server

    telegram = _settings_dict(settings.get("telegram")).copy()
    telegram_data = _settings_dict(data.get("telegram"))
    _patch_secret(telegram, telegram_data, "bot_token")
    _patch_text(telegram, telegram_data, "chat_id", max_len=128)
    _patch_text(telegram, telegram_data, "proxy_url", max_len=512)
    if "allowed_user_ids" in telegram_data:
        telegram["allowed_user_ids"] = _clean_text_list(telegram_data.get("allowed_user_ids"))
    if telegram_data:
        settings["telegram"] = telegram

    paths = _settings_dict(settings.get("paths")).copy()
    paths_data = _settings_dict(data.get("paths"))
    for key in ("image_archive_dir", "source_image_dir", "tasks_db"):
        _patch_text(paths, paths_data, key, max_len=2048)
    if paths_data:
        settings["paths"] = paths

    provider = _settings_dict(settings.get("gpt_provider")).copy()
    provider_data = _settings_dict(data.get("gpt_provider"))
    for key in ("auth_file", "auth_dir", "api_base"):
        _patch_text(provider, provider_data, key, max_len=2048)
    if "image_main_model" in provider_data:
        provider["image_main_model"] = _coerce_gpt_main_model(provider_data.get("image_main_model"))
    if "reasoning_effort" in provider_data:
        provider["reasoning_effort"] = _coerce_gpt_reasoning_effort(provider_data.get("reasoning_effort"))
    if "transport_mode" in provider_data:
        provider["transport_mode"] = _coerce_gpt_transport_mode(provider_data.get("transport_mode"))
    if "total_timeout_seconds" in provider_data:
        provider["total_timeout_seconds"] = _coerce_gpt_provider_total_timeout(provider_data.get("total_timeout_seconds"))
    if provider_data:
        settings["gpt_provider"] = provider

    third_party = _settings_dict(settings.get("third_party_image_api")).copy()
    third_party_data = _settings_dict(data.get("third_party_image_api"))
    _patch_secret(third_party, third_party_data, "api_key")
    for key in ("base_url", "model", "generate_path", "edit_path", "format"):
        _patch_text(third_party, third_party_data, key, max_len=2048 if key in ("base_url", "generate_path", "edit_path") else 128)
    if "timeout_seconds" in third_party_data:
        try:
            third_party["timeout_seconds"] = max(30, min(1800, int(third_party_data.get("timeout_seconds"))))
        except (TypeError, ValueError):
            pass
    if third_party_data:
        settings["third_party_image_api"] = third_party

    pool = _settings_dict(settings.get("chatgpt_pool")).copy()
    pool_data = _settings_dict(data.get("chatgpt_pool"))
    if "enabled" in pool_data:
        pool["enabled"] = _coerce_bool(pool_data.get("enabled"), True)
    for key in ("base_url", "generation_model", "db_path"):
        _patch_text(pool, pool_data, key, max_len=2048)
    if "timeout_seconds" in pool_data:
        try:
            pool["timeout_seconds"] = max(60, min(900, int(pool_data.get("timeout_seconds"))))
        except (TypeError, ValueError):
            pass
    _patch_secret(pool, pool_data, "auth_key")
    if pool_data:
        settings["chatgpt_pool"] = pool

    managed_codex = _settings_dict(settings.get("managed_codex_oauth")).copy()
    managed_codex_data = _settings_dict(data.get("managed_codex_oauth"))
    if "enabled" in managed_codex_data:
        managed_codex["enabled"] = _coerce_bool(managed_codex_data.get("enabled"), True)
    for key in ("auth_file", "accounts_dir", "api_base", "redirect_uri"):
        _patch_text(managed_codex, managed_codex_data, key, max_len=2048)
    if managed_codex_data:
        settings["managed_codex_oauth"] = managed_codex

    for bool_key, url_key, section_key in (
        ("proxy_enabled", "proxy_url", "proxy"),
        ("prompt_source_proxy_enabled", "prompt_source_proxy_url", "prompt_source_proxy"),
    ):
        proxy_data = _settings_dict(data.get(section_key))
        if "enabled" in proxy_data:
            settings[bool_key] = _coerce_bool(proxy_data.get("enabled"), False)
        if "proxy_url" in proxy_data:
            settings[url_key] = _clean_text(proxy_data.get("proxy_url"), max_len=512)

    _validate_public_mode_password(settings, server_config=_server_config_from_settings_snapshot(settings))
    return settings


def _sanitize_gpt_provider_patch(data):
    allowed = {}
    transport_mode = str(data.get("transport_mode") or data.get("transportMode") or "").strip().lower()
    if transport_mode in GPT_TRANSPORT_MODES:
        allowed["transport_mode"] = transport_mode
    timeout_value = data.get("total_timeout_seconds", data.get("totalTimeoutSeconds"))
    if timeout_value not in (None, ""):
        allowed["total_timeout_seconds"] = _coerce_gpt_provider_total_timeout(timeout_value)
    return allowed


def _collect_prompt_skill_runtime_config(provider_id=None):
    config = get_prompt_skill_config()
    models_payload = discover_prompt_models(provider_id or config.get("provider"))
    return {
        "ok": True,
        "prompt_skill": config,
        "providers": list_prompt_providers(),
        "models": models_payload.get("models") or [],
        "default_model": models_payload.get("default_model") or "",
        "warning": models_payload.get("warning") or "",
    }


def _sanitize_prompt_skill_patch(data):
    allowed = {}
    provider = str(data.get("provider") or "").strip()
    skill = str(data.get("skill") or "").strip()
    model = str(data.get("model") or "").strip()
    reasoning_effort = str(data.get("reasoning_effort") or data.get("reasoningEffort") or "").strip().lower()
    default_output = str(data.get("default_output") or data.get("defaultOutput") or "").strip().lower()
    if provider:
        allowed["provider"] = provider[:80]
    if skill:
        allowed["skill"] = skill[:120]
    allowed["model"] = model[:160]
    if reasoning_effort in GPT_REASONING_EFFORTS:
        allowed["reasoning_effort"] = reasoning_effort
    if default_output in {"full_prompt", "compact_prompt"}:
        allowed["default_output"] = default_output
    return allowed


def save_thumbnail(image_path, output_filename):
    """为历史记录生成缩略图到 google_outputs/thumb_*.png"""
    try:
        google_outputs_dir = os.path.join(DIRECTORY, 'google_outputs')
        os.makedirs(google_outputs_dir, exist_ok=True)
        thumb_path = os.path.join(google_outputs_dir, f'thumb_{output_filename}')
        with Image.open(image_path) as img:
            img.thumbnail((300, 300), Image.LANCZOS)
            img.save(thumb_path, 'PNG', quality=80)
        print(f"🖼️ 缩略图已保存：{thumb_path}")
        return True
    except Exception as e:
        print(f"⚠️ 缩略图生成失败：{e}")
        return False

def safe_basename(filename):
    return os.path.basename(str(filename or '').strip())

def ensure_gpt_preview_image(filename, max_side=2048):
    """为 GPT 原图生成查看页用 2K 预览图，并缓存到 gpt_outputs。"""
    safe_name = safe_basename(filename)
    if not safe_name.endswith('_preview.png'):
        return None

    preview_path = Path(DIRECTORY) / 'gpt_outputs' / safe_name
    if preview_path.exists():
        return preview_path

    source_name = safe_name.replace('_preview.png', '.png')
    source_path = Path(DIRECTORY) / 'gpt_outputs' / source_name
    if not source_path.exists():
        return None

    try:
        with Image.open(source_path) as img:
            img = img.convert('RGB') if img.mode not in ('RGB', 'RGBA') else img.copy()
            img.thumbnail((max_side, max_side), Image.LANCZOS)
            img.save(preview_path, 'PNG', optimize=True)
        print(f"🖼️ GPT 2K 预览已生成：{preview_path.name}")
        return preview_path
    except Exception as e:
        print(f"⚠️ GPT 2K 预览生成失败：{e}")
        return None


def _path_is_inside(path: Path, root: Path) -> bool:
    try:
        resolved = path.expanduser().resolve()
        resolved_root = root.expanduser().resolve()
        return resolved == resolved_root or resolved_root in resolved.parents
    except Exception:
        return False


def _allowed_asset_delete_roots():
    roots = [
        Path(root).expanduser()
        for root in image_lookup_roots()
    ]
    roots.extend([
        Path(DIRECTORY) / 'gpt_outputs',
        Path(DIRECTORY) / 'google_outputs',
    ])
    return roots


def _unique_trash_path(filename):
    trash_dir = Path.home() / '.Trash'
    trash_dir.mkdir(parents=True, exist_ok=True)
    clean_name = safe_basename(filename) or f"deleted_asset_{int(time.time())}"
    target = trash_dir / clean_name
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    for index in range(1, 1000):
        candidate = trash_dir / f"{stem} {index}{suffix}"
        if not candidate.exists():
            return candidate
    return trash_dir / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"


def _move_asset_file_to_trash(path, deleted, missing, skipped, moves=None):
    if not path:
        return
    candidate = Path(path).expanduser()
    if not candidate.exists():
        missing.append(candidate.name)
        return
    if not candidate.is_file():
        skipped.append(candidate.name)
        return
    if not any(_path_is_inside(candidate, root) for root in _allowed_asset_delete_roots()):
        skipped.append(candidate.name)
        return
    target = _unique_trash_path(candidate.name)
    shutil.move(str(candidate), str(target))
    deleted.append(candidate.name)
    if isinstance(moves, list):
        moves.append({
            "original_path": str(candidate),
            "trash_path": str(target),
            "filename": candidate.name,
        })


def _asset_delete_candidates(asset):
    filename = safe_basename(asset.get('file') or urllib.parse.urlparse(str(asset.get('imageUrl') or '')).path.split('/')[-1])
    archive_rel = str(asset.get('archiveRelPath') or asset.get('archive_rel_path') or '').strip()
    archive_path = _resolve_archive_image_file(archive_rel)
    if not filename and not archive_path:
        return []

    provider = str(asset.get('provider') or '').lower()
    project_gpt_dir = Path(DIRECTORY) / 'gpt_outputs'
    project_google_dir = Path(DIRECTORY) / 'google_outputs'
    candidates = []

    if archive_path:
        candidates.append(archive_path)
        candidates.append(archive_path.with_suffix('.txt'))

    original = _resolve_download_file(filename)
    if original:
        candidates.append(original)
        candidates.append(original.with_suffix('.txt'))

    if provider == 'gpt':
        gpt_file = project_gpt_dir / filename
        candidates.append(gpt_file)
        candidates.append(gpt_file.with_suffix('.txt'))
        candidates.append(project_gpt_dir / f"{Path(filename).stem}_thumb.png")
        candidates.append(project_gpt_dir / f"{Path(filename).stem}_preview.png")
    else:
        candidates.append(project_google_dir / f"thumb_{filename}")

    deduped = []
    seen = set()
    for path in candidates:
        key = str(Path(path).expanduser())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(Path(path))
    return deduped


def _asset_filename(asset):
    return safe_basename(
        asset.get('file')
        or urllib.parse.urlparse(str(asset.get('imageUrl') or asset.get('image_url') or '')).path.split('/')[-1]
    )


def _asset_url_file_exists(url):
    raw_url = str(url or '').strip()
    if not raw_url:
        return False
    if raw_url.startswith(('http://', 'https://', 'data:', 'blob:')):
        return True
    parsed = urllib.parse.urlparse(raw_url)
    path = urllib.parse.unquote(parsed.path or raw_url)
    filename = safe_basename(path)
    if path.startswith('/archive_image/'):
        return bool(_resolve_archive_image_file(path[len('/archive_image/'):]))
    if path.startswith('/gpt_outputs/') and filename:
        return (Path(DIRECTORY) / 'gpt_outputs' / filename).exists() or bool(_resolve_download_file(filename))
    if path.startswith('/google_outputs/') and filename:
        return (Path(DIRECTORY) / 'google_outputs' / filename).exists()
    if path.startswith('/image/') and filename:
        return bool(_resolve_download_file(filename))
    if filename:
        return bool(_resolve_download_file(filename))
    return True


def _asset_file_exists(asset):
    filename = _asset_filename(asset)
    provider = str(asset.get('provider') or '').lower()
    archive_rel = str(asset.get('archiveRelPath') or asset.get('archive_rel_path') or '').strip()
    if archive_rel and _resolve_archive_image_file(archive_rel):
        return True
    if filename:
        if provider == 'gpt':
            if (Path(DIRECTORY) / 'gpt_outputs' / filename).exists():
                return True
            if _resolve_download_file(filename):
                return True
            if _asset_url_file_exists(asset.get('imageUrl') or asset.get('image_url') or asset.get('thumbUrl') or ''):
                return True
            return False
        if _resolve_download_file(filename):
            return True
        if (Path(DIRECTORY) / 'google_outputs' / filename).exists():
            return True
        if (Path(DIRECTORY) / 'gpt_outputs' / filename).exists():
            return True
    return _asset_url_file_exists(asset.get('imageUrl') or asset.get('image_url') or asset.get('thumbUrl') or '')


def _remove_old_history_asset(asset, filename, removed_lines=None):
    timestamp = int(asset.get('createdAt') or asset.get('created_at') or 0)
    if not timestamp:
        raw_task_id = str(asset.get('taskId') or asset.get('task_id') or '')
        match = re.match(r'old_(\d+)', raw_task_id)
        timestamp = int(match.group(1)) if match else 0
    if not timestamp:
        return False

    history_path = Path(DIRECTORY) / 'history.jsonl'
    if not history_path.exists():
        return False

    removed = False
    kept = []
    with open(history_path, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:
                kept.append(line)
                continue
            same_time = int(item.get('timestamp') or item.get('created_at') or -1) == timestamp
            same_file = safe_basename(item.get('output_file') or item.get('result_file') or '') == filename
            if same_time and same_file:
                removed = True
                if isinstance(removed_lines, list):
                    removed_lines.append(line.rstrip('\n'))
                continue
            kept.append(line)

    if removed:
        with open(history_path, 'w', encoding='utf-8') as f:
            f.writelines(kept)
    return removed


def _restore_old_history_lines(lines):
    clean_lines = [str(line or '').strip() for line in (lines or []) if str(line or '').strip()]
    if not clean_lines:
        return 0
    history_path = Path(DIRECTORY) / 'history.jsonl'
    existing = set()
    if history_path.exists():
        with open(history_path, 'r', encoding='utf-8') as f:
            existing = {line.strip() for line in f if line.strip()}
    restored = 0
    with open(history_path, 'a', encoding='utf-8') as f:
        for line in clean_lines:
            if line in existing:
                continue
            f.write(line + '\n')
            existing.add(line)
            restored += 1
    return restored


def _remove_asset_from_task(asset, removed_history=None):
    task_id = str(asset.get('taskId') or asset.get('task_id') or '').strip()
    filename = _asset_filename(asset)
    if not task_id or not filename:
        return False
    if task_id.startswith('old_'):
        return _remove_old_history_asset(asset, filename, removed_history)
    task = get_task(task_id)
    if not task:
        return False
    files = list(task.get('result_files') or [])
    primary = task.get('result_file') or ''
    if not files and primary:
        files = [primary]
    if filename not in files and filename != primary:
        return False
    remaining = [item for item in files if item != filename]
    if not remaining:
        update_task_fields(
            task_id,
            result_file='',
            result_files=json.dumps([], ensure_ascii=False),
            progress_text='图片资产已从图库移除',
        )
        return True
    update_task_fields(
        task_id,
        result_file=remaining[0],
        result_files=json.dumps(remaining, ensure_ascii=False),
        progress_text='部分图片已从图库移除',
    )
    return True


def _remove_assets_from_tasks(assets, removed_history=None):
    grouped = {}
    old_assets = []
    for asset in assets or []:
        task_id = str(asset.get('taskId') or asset.get('task_id') or '').strip()
        filename = _asset_filename(asset)
        if not task_id or not filename:
            continue
        if task_id.startswith('old_'):
            old_assets.append((asset, filename))
            continue
        grouped.setdefault(task_id, set()).add(filename)

    changed = 0
    for asset, filename in old_assets:
        if _remove_old_history_asset(asset, filename, removed_history):
            changed += 1

    for task_id, filenames in grouped.items():
        task = get_task(task_id)
        if not task:
            continue
        files = list(task.get('result_files') or [])
        primary = task.get('result_file') or ''
        if not files and primary:
            files = [primary]
        if not files:
            continue
        remaining = [item for item in files if safe_basename(item) not in filenames]
        if len(remaining) == len(files):
            continue
        if not remaining:
            update_task_fields(
                task_id,
                result_file='',
                result_files=json.dumps([], ensure_ascii=False),
                progress_text='图片资产已从图库移除',
            )
        else:
            update_task_fields(
                task_id,
                result_file=remaining[0],
                result_files=json.dumps(remaining, ensure_ascii=False),
                progress_text='部分图片已从图库移除',
            )
        changed += 1
    return changed


def _delete_gallery_assets(asset_ids):
    clean_ids = []
    seen_ids = set()
    for raw_id in asset_ids or []:
        asset_id = str(raw_id or '').strip()
        if not asset_id or asset_id in seen_ids:
            continue
        seen_ids.add(asset_id)
        clean_ids.append(asset_id)
    if not clean_ids:
        raise ValueError("缺少资产 ID")
    if len(clean_ids) > 120:
        raise ValueError("单次最多删除 120 张图片")

    data = list_gallery_assets(limit=5000, offset=0, include_hidden=True)
    missing_data = list_gallery_assets(limit=5000, offset=0, include_hidden=True, source='missing_history')
    asset_map = {
        str(asset.get('id') or asset.get('asset_id') or ''): asset
        for asset in (data.get('assets') or []) + (missing_data.get('assets') or [])
        if asset.get('id') or asset.get('asset_id')
    }
    assets = []
    missing_asset_ids = []
    for asset_id in clean_ids:
        asset = asset_map.get(asset_id) or get_gallery_asset(asset_id)
        if asset:
            assets.append(asset)
        else:
            missing_asset_ids.append(asset_id)
    if not assets:
        raise FileNotFoundError("资产不存在")

    task_snapshots = {}
    set_snapshots = {}
    for asset in assets:
        task_id = str(asset.get('taskId') or asset.get('task_id') or '').strip()
        if task_id and not task_id.startswith('old_') and task_id not in task_snapshots:
            task = get_task(task_id)
            if task:
                task_snapshots[task_id] = task
        for snapshot in snapshot_sets_for_asset(str(asset.get('id') or asset.get('asset_id') or '')):
            set_id = str(snapshot.get('set_id') or '').strip()
            if set_id:
                set_snapshots[set_id] = snapshot

    deleted = []
    missing = []
    skipped = []
    moves = []
    seen_paths = set()
    for asset in assets:
        for path in _asset_delete_candidates(asset):
            path_key = str(Path(path).expanduser())
            if path_key in seen_paths:
                continue
            seen_paths.add(path_key)
            _move_asset_file_to_trash(path, deleted, missing, skipped, moves=moves)

    removed_history = []
    task_updates = _remove_assets_from_tasks(assets, removed_history=removed_history)
    hidden_updates = 0
    set_updates = 0
    processed_ids = []
    for asset in assets:
        asset_id = str(asset.get('id') or asset.get('asset_id') or '').strip()
        if not asset_id:
            continue
        processed_ids.append(asset_id)
        try:
            update_asset_meta(asset_id, hidden=True)
            hidden_updates += 1
        except Exception:
            pass
        set_updates += remove_asset_from_sets(asset_id)

    journal = record_delete_batch({
        "asset_ids": processed_ids,
        "assets": assets,
        "moves": moves,
        "task_snapshots": list(task_snapshots.values()),
        "task_snapshot": next(iter(task_snapshots.values()), None),
        "old_history_lines": removed_history,
        "set_snapshots": list(set_snapshots.values()),
        "deleted_files": deleted,
        "missing_files": missing,
        "skipped_files": skipped,
    })

    return {
        "ok": True,
        "asset_ids": processed_ids,
        "asset_id": processed_ids[0] if len(processed_ids) == 1 else "",
        "missing_asset_ids": missing_asset_ids,
        "delete_batch_id": journal.get("batch_id"),
        "undo_id": journal.get("batch_id"),
        "deleted_files": deleted,
        "missing_files": missing,
        "skipped_files": skipped,
        "task_updates": task_updates,
        "task_updated": task_updates > 0,
        "hidden_updates": hidden_updates,
        "set_updates": set_updates,
        "message": "资产文件已移入废纸篓" if deleted else "资产已从图库移除",
    }


def _collect_asset_health():
    data = list_gallery_assets(limit=3000, offset=0, include_hidden=True)
    stats = data.get('stats') if isinstance(data.get('stats'), dict) else {}
    assets = [asset for asset in data.get('assets', []) if asset.get('id') or asset.get('asset_id')]
    missing_assets = []
    valid_asset_ids = set()
    all_asset_ids = set()
    for asset in assets:
        asset_id = str(asset.get('id') or asset.get('asset_id') or '').strip()
        if not asset_id:
            continue
        all_asset_ids.add(asset_id)
        if _asset_file_exists(asset):
            valid_asset_ids.add(asset_id)
        else:
            missing_assets.append({
                "asset_id": asset_id,
                "id": asset_id,
                "task_id": asset.get('taskId') or asset.get('task_id') or '',
                "title": asset.get('title') or '',
                "file": asset.get('file') or '',
                "imageUrl": asset.get('imageUrl') or asset.get('image_url') or '',
                "provider": asset.get('provider') or '',
            })

    sets_data = list_asset_sets(limit=300, offset=0)
    invalid_set_refs = 0
    empty_sets = []
    for asset_set in sets_data.get('sets', []):
        ids = [str(value or '').strip() for value in (asset_set.get('assetIds') or asset_set.get('asset_ids') or []) if str(value or '').strip()]
        valid_count = sum(1 for asset_id in ids if asset_id in valid_asset_ids)
        invalid_set_refs += sum(1 for asset_id in ids if asset_id not in valid_asset_ids)
        if ids and valid_count <= 0:
            empty_sets.append({
                "set_id": asset_set.get('id') or asset_set.get('set_id') or '',
                "name": asset_set.get('name') or '未命名候选集',
                "count": len(ids),
            })

    invalid_lineage_refs = 0
    invalid_lineage_tasks = 0
    no_image_history = 0
    for task in get_all_tasks(limit=3000, offset=0):
        result_files = task.get('result_files') or []
        primary = task.get('result_file') or ''
        if not result_files and primary:
            result_files = [primary]
        if not _history_task_should_render(task.get('status'), result_files):
            no_image_history += 1

        params = task.get('params') if isinstance(task.get('params'), dict) else {}
        lineage = params.get('lineage') if isinstance(params.get('lineage'), dict) else {}
        refs = lineage.get('reference_assets') or lineage.get('referenceAssets') or []
        if not isinstance(refs, list):
            continue
        missing_refs = [
            ref for ref in refs
            if isinstance(ref, dict)
            and str(ref.get('asset_id') or ref.get('assetId') or ref.get('id') or '').strip()
            and str(ref.get('asset_id') or ref.get('assetId') or ref.get('id') or '').strip() not in valid_asset_ids
        ]
        if missing_refs:
            invalid_lineage_refs += len(missing_refs)
            invalid_lineage_tasks += 1

    history_missing_count = int(stats.get('history_missing_count') or 0)
    issue_count = len(missing_assets) + invalid_set_refs + len(empty_sets) + invalid_lineage_refs + no_image_history + history_missing_count
    return {
        "ok": issue_count == 0,
        "assets_total": len(assets),
        "assets_valid": len(valid_asset_ids),
        "missing_count": len(missing_assets),
        "missing_assets": missing_assets[:120],
        "missing_assets_all": missing_assets,
        "invalid_set_refs": invalid_set_refs,
        "empty_sets": empty_sets,
        "empty_set_count": len(empty_sets),
        "invalid_lineage_refs": invalid_lineage_refs,
        "invalid_lineage_tasks": invalid_lineage_tasks,
        "no_image_history": no_image_history,
        "valid_asset_ids": sorted(valid_asset_ids),
        "all_asset_ids": sorted(all_asset_ids),
        "issue_count": issue_count,
        "stats": stats,
        "obsidian_image_count": stats.get('obsidian_image_count', len(assets)),
        "archive_image_count": stats.get('archive_image_count', len(assets)),
        "gallery_asset_count": stats.get('gallery_asset_count', len(assets)),
        "indexed_asset_count": stats.get('indexed_asset_count', len(assets)),
        "task_record_image_count": stats.get('task_record_image_count', 0),
        "linked_asset_count": stats.get('linked_asset_count', 0),
        "orphan_asset_count": stats.get('orphan_asset_count', 0),
        "archive_only_count": stats.get('archive_only_count', 0),
        "history_result_count": stats.get('history_result_count', 0),
        "history_missing_count": history_missing_count,
        "history_missing_archive_count": stats.get('history_missing_archive_count', history_missing_count),
    }


def _cleanup_lineage_refs(valid_asset_ids):
    valid_ids = {str(value or '').strip() for value in (valid_asset_ids or []) if str(value or '').strip()}
    removed = 0
    updated_tasks = 0
    for task in get_all_tasks(limit=3000, offset=0):
        task_id = str(task.get('task_id') or '').strip()
        params = task.get('params') if isinstance(task.get('params'), dict) else {}
        lineage = params.get('lineage') if isinstance(params.get('lineage'), dict) else {}
        refs = lineage.get('reference_assets') or lineage.get('referenceAssets') or []
        if not task_id or not isinstance(refs, list):
            continue
        next_refs = []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            ref_id = str(ref.get('asset_id') or ref.get('assetId') or ref.get('id') or '').strip()
            if ref_id and ref_id not in valid_ids:
                removed += 1
                continue
            next_refs.append(ref)
        if len(next_refs) == len(refs):
            continue
        asset_ids = []
        task_ids = []
        for ref in next_refs:
            ref_id = str(ref.get('asset_id') or ref.get('assetId') or ref.get('id') or '').strip()
            ref_task_id = str(ref.get('task_id') or ref.get('taskId') or '').strip()
            if ref_id and ref_id not in asset_ids:
                asset_ids.append(ref_id)
            if ref_task_id and ref_task_id not in task_ids:
                task_ids.append(ref_task_id)
        lineage['reference_assets'] = next_refs
        lineage['referenceAssets'] = next_refs
        lineage['reference_asset_ids'] = asset_ids
        lineage['referenceAssetIds'] = asset_ids
        lineage['source_task_ids'] = task_ids
        lineage['sourceTaskIds'] = task_ids
        params['lineage'] = lineage
        update_task_fields(task_id, params=json.dumps(params, ensure_ascii=False))
        updated_tasks += 1
    return {"removed_refs": removed, "updated_tasks": updated_tasks}


def _cleanup_no_image_history():
    removed = 0
    for task in get_all_tasks(limit=3000, offset=0):
        result_files = task.get('result_files') or []
        primary = task.get('result_file') or ''
        if not result_files and primary:
            result_files = [primary]
        if _history_task_should_render(task.get('status'), result_files):
            continue
        task_id = str(task.get('task_id') or '').strip()
        if task_id and delete_task(task_id):
            removed += 1

    history_path = Path(DIRECTORY) / 'history.jsonl'
    if history_path.exists():
        kept = []
        old_removed = 0
        with open(history_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    kept.append(line)
                    continue
                filename = safe_basename(item.get('output_file') or item.get('result_file') or '')
                status = item.get('status') or 'success'
                if not _history_task_should_render(status, [filename] if filename else []):
                    old_removed += 1
                    continue
                kept.append(line)
        if old_removed:
            with open(history_path, 'w', encoding='utf-8') as f:
                f.writelines(kept)
            removed += old_removed
    return removed


def _restore_trash_move(move):
    original_raw = str(move.get('original_path') or '').strip()
    trash_raw = str(move.get('trash_path') or '').strip()
    if not original_raw or not trash_raw:
        return "skipped"
    original = Path(original_raw).expanduser()
    trash_path = Path(trash_raw).expanduser()
    trash_root = Path.home() / '.Trash'
    if not _path_is_inside(trash_path, trash_root):
        return "skipped"
    if not any(_path_is_inside(original, root) for root in _allowed_asset_delete_roots()):
        return "skipped"
    if original.exists():
        return "exists"
    if not trash_path.exists() or not trash_path.is_file():
        return "missing"
    original.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(trash_path), str(original))
    return "restored"


class RequestHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        """Serve frontend assets from frontend/ while keeping public URLs stable."""
        parsed = urllib.parse.urlparse(path)
        # URL paths always use "/" separators.  Do not use os.path.normpath here:
        # on Windows it turns "/desktop.html" into "\\desktop.html", so the
        # frontend entrypoint no longer matches and SimpleHTTPRequestHandler
        # returns 404 for the page opened by start-windows.bat.
        clean_path = posixpath.normpath(urllib.parse.unquote(parsed.path or "/"))
        parts = [part for part in clean_path.split("/") if part and part not in (".", "..")]
        if not parts:
            parts = ["index.html"]
        if len(parts) == 1 and parts[0] in {"desktop.html", "index.html"}:
            return str(FRONTEND_ROOT / parts[0])
        if parts[0] in {"scripts", "styles", "assets", "vendor"}:
            return str(FRONTEND_ROOT.joinpath(*parts))
        if parts[0] == "static":
            return str(PROJECT_ROOT.joinpath(*parts))
        # Do not expose project databases, settings, source code, or auth files
        # through SimpleHTTPRequestHandler's catch-all static fallback.
        return str(FRONTEND_ROOT / "__not_found__")

    def end_headers(self):
        """入口页防旧包；带版本号的静态资源允许 Telegram WebView 缓存。"""
        try:
            self._apply_cors_headers()
        except Exception:
            pass
        try:
            parsed = urllib.parse.urlparse(getattr(self, 'path', '') or '')
            path = parsed.path
            query = parsed.query
            no_cache = path in ('', '/') or path.endswith('.html')
            if no_cache:
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Expires', '0')
            elif path.startswith(('/scripts/', '/styles/')):
                if 'v=' in query:
                    self.send_header('Cache-Control', 'public, max-age=31536000, immutable')
                else:
                    self.send_header('Cache-Control', 'public, max-age=3600')
        except Exception:
            pass
        super().end_headers()

    def _get_cookie_value(self, name):
        raw = self.headers.get('Cookie', '')
        if not raw:
            return ''
        try:
            cookie = SimpleCookie()
            cookie.load(raw)
            morsel = cookie.get(name)
            return morsel.value if morsel else ''
        except Exception:
            return ''

    def is_authenticated(self):
        if not _auth_enabled():
            return True
        init_data = self.headers.get(TELEGRAM_INIT_DATA_HEADER_NAME, '')
        encoded_init_data = self.headers.get(TELEGRAM_INIT_DATA_ENCODED_HEADER_NAME, '')
        if not init_data and encoded_init_data:
            try:
                init_data = urllib.parse.unquote(encoded_init_data)
            except Exception:
                init_data = ''
        if init_data and _verify_telegram_init_data(init_data):
            return True
        header_token = self.headers.get(AUTH_HEADER_NAME, '')
        if header_token and _verify_auth_cookie_value(header_token):
            return True
        try:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(getattr(self, 'path', '') or '').query)
            query_token = (
                query.get('miniappAuth', [''])[0]
                or query.get('authToken', [''])[0]
                or query.get('auth_token', [''])[0]
            )
            if query_token and _verify_auth_cookie_value(query_token):
                return True
        except Exception:
            pass
        return _verify_auth_cookie_value(self._get_cookie_value(AUTH_COOKIE_NAME))

    def require_auth(self):
        if self.is_authenticated():
            return True
        self.send_json({
            "ok": False,
            "error": "Unauthorized",
            "message": "需要先输入访问密码"
        }, 401)
        return False

    def _apply_cors_headers(self):
        if getattr(self, '_cors_headers_applied', False):
            return
        self._cors_headers_applied = True
        origin = str(self.headers.get('Origin') or '').strip().rstrip('/')
        if not origin:
            return
        if origin in set(get_allowed_cors_origins()):
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')

    def start_generation_task(self, task_id, target, args=(), task_ids=None):
        thread = _start_generation_thread(target, args=args)
        if thread:
            return True
        message = _generation_busy_message()
        for rejected_id in (task_ids or [task_id]):
            update_task(
                rejected_id,
                'failed',
                error=message,
                stage='rejected',
                progress_text=message,
                transport_error_type='GenerationQueueFull',
            )
        payload = _generation_busy_payload()
        payload['task_id'] = task_id
        self.send_json(payload, 503)
        return False

    def do_OPTIONS(self):
        """处理 CORS 预检请求"""
        self.send_response(200)
        self._apply_cors_headers()
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, PATCH, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', f'Content-Type, {TELEGRAM_INIT_DATA_HEADER_NAME}, {TELEGRAM_INIT_DATA_ENCODED_HEADER_NAME}, {AUTH_HEADER_NAME}')
        self.end_headers()

    def do_GET(self):
        """处理 GET 请求"""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == '/v' or path.startswith('/v=') or path.lower().startswith('/%3f'):
            self.path = '/'
            super().do_GET()
            return

        # API 路由
        if path == '/api/history':
            if not self.require_auth():
                return
            self.handle_history()
        elif path == '/api/assets':
            if not self.require_auth():
                return
            self.handle_assets(parsed)
        elif path == '/api/assets/health':
            if not self.require_auth():
                return
            self.handle_asset_health()
        elif path == '/api/system/diagnostics':
            if not self.require_auth():
                return
            self.handle_system_diagnostics()
        elif path == '/api/app/update-status':
            if not self.require_auth():
                return
            self.handle_app_update_status()
        elif path == '/api/system/settings':
            if not self.require_auth():
                return
            self.handle_system_settings()
        elif path == '/api/gpt/config':
            if not self.require_auth():
                return
            self.handle_gpt_config()
        elif path == '/api/gpt/models':
            if not self.require_auth():
                return
            self.handle_gpt_models(parsed)
        elif path == '/api/gpt-pool/status':
            if not self.require_auth():
                return
            self.handle_chatgpt_pool_status()
        elif path == '/api/managed-codex-oauth/status':
            if not self.require_auth():
                return
            self.handle_managed_codex_oauth_status()
        elif path == '/api/gpt-pool/accounts':
            if not self.require_auth():
                return
            self.handle_chatgpt_pool_accounts()
        elif path == '/api/editable-files':
            if not self.require_auth():
                return
            self.handle_editable_files(parsed)
        elif path == '/api/prompt/config':
            if not self.require_auth():
                return
            self.handle_prompt_config(parsed)
        elif path == '/api/prompt/models':
            if not self.require_auth():
                return
            self.handle_prompt_models(parsed)
        elif path == '/api/prompt/style-presets':
            if not self.require_auth():
                return
            self.handle_prompt_style_presets()
        elif path == '/api/prompt/versions':
            if not self.require_auth():
                return
            self.handle_prompt_versions(parsed)
        elif path == '/api/prompt-library/blocks/list':
            if not self.require_auth():
                return
            self.handle_prompt_library_blocks_list(parsed)
        elif path == '/api/prompt-library/templates/list':
            if not self.require_auth():
                return
            self.handle_prompt_library_templates_list()
        elif path == '/api/assets/sets':
            if not self.require_auth():
                return
            self.handle_asset_sets(parsed)
        elif path == '/api/prompt-sources':
            if not self.require_auth():
                return
            self.handle_prompt_sources()
        elif path == '/api/prompt-source-items':
            if not self.require_auth():
                return
            self.handle_prompt_source_items(parsed)
        elif path.startswith('/api/prompt-sources/runs/'):
            if not self.require_auth():
                return
            run_id = urllib.parse.unquote(path.split('/')[-1])
            self.handle_prompt_source_run(run_id)
        elif path.startswith('/api/generation-runs/'):
            if not self.require_auth():
                return
            task_id = urllib.parse.unquote(path.split('/')[-1])
            self.handle_generation_runs(parsed, task_id)
        elif path.startswith('/api/generation-events/'):
            if not self.require_auth():
                return
            run_id = urllib.parse.unquote(path.split('/')[-1])
            self.handle_generation_events(parsed, run_id)
        elif path.startswith('/api/batches/'):
            if not self.require_auth():
                return
            batch_id = urllib.parse.unquote(path.split('/')[-1])
            self.handle_batch_status(batch_id)
        elif path.startswith('/api/status/'):
            if not self.require_auth():
                return
            task_id = path.split('/')[-1]
            self.handle_status(task_id)
        elif path == '/api/upscale/models':
            if not self.require_auth():
                return
            self.handle_upscale_models()
        elif path == '/api/upscale/component/status':
            if not self.require_auth():
                return
            self.handle_upscale_component_status()
        elif path.startswith('/image/'):
            if not self.require_auth():
                return
            filename = urllib.parse.unquote(path.split('/')[-1])
            self.handle_image(filename)
        elif path.startswith('/archive_image/'):
            if not self.require_auth():
                return
            rel_path = urllib.parse.unquote(path[len('/archive_image/'):])
            self.handle_archive_image(rel_path)
        elif path.startswith('/editable_file/'):
            if not self.require_auth():
                return
            rel_path = urllib.parse.unquote(path[len('/editable_file/'):])
            self.handle_editable_file(rel_path)
        elif path.startswith('/source_image/'):
            if not self.require_auth():
                return
            rel_path = urllib.parse.unquote(path[len('/source_image/'):])
            self.handle_source_image(rel_path)
        elif path.startswith('/thumb/'):
            if not self.require_auth():
                return
            self.handle_thumb(parsed)
        elif path.startswith('/google_outputs/'):
            if not self.require_auth():
                return
            filename = urllib.parse.unquote(path.split('/')[-1])
            self.handle_google_output(filename)
        elif path.startswith('/gpt_outputs/'):
            if not self.require_auth():
                return
            filename = urllib.parse.unquote(path.split('/')[-1])
            self.handle_gpt_output(filename)
        elif path == '/api/comfy/workflows':
            if not self.require_auth():
                return
            self.handle_comfy_workflows()
        elif path == '/api/comfy/history':
            if not self.require_auth():
                return
            self.handle_comfy_history()
        elif path == '/api/comfy/image':
            if not self.require_auth():
                return
            self.handle_comfy_image()
        elif path == '/api/layout/fonts':
            if not self.require_auth():
                return
            self.handle_layout_fonts()
        elif path == '/api/layout/drafts':
            if not self.require_auth():
                return
            self.handle_layout_draft_list(parsed)
        elif path.startswith('/api/layout/drafts/'):
            if not self.require_auth():
                return
            self.handle_layout_draft_get(parsed)
        elif path == '/api/pose/assets/status':
            if not self.require_auth():
                return
            self.handle_pose_assets_status()
        else:
            # 静态文件服务
            super().do_GET()
    
    def do_DELETE(self):
        """处理 DELETE 请求"""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # API 路由
        if path == '/api/history/delete':
            if not self.require_auth():
                return
            self.handle_delete_history_item()
        elif path == '/api/history/delete_failed':
            if not self.require_auth():
                return
            self.handle_delete_failed()
        elif path.startswith('/api/assets/sets/'):
            if not self.require_auth():
                return
            set_id = urllib.parse.unquote(path.split('/')[-1])
            self.handle_asset_set_delete(set_id)
        elif path.startswith('/api/assets/'):
            if not self.require_auth():
                return
            asset_id = urllib.parse.unquote(path.split('/')[-1])
            self.handle_asset_delete(asset_id)
        else:
            self.send_error(404, "Not Found")
    
    def do_POST(self):
        """处理 POST 请求"""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        
        # API 路由
        if path == '/generate':
            if not self.require_auth():
                return
            self.handle_generate()
        elif path == '/api/skill/generate':
            if not self.require_auth():
                return
            self.handle_generate(force_caller='skill')
        elif path == '/edit':
            if not self.require_auth():
                return
            self.handle_edit()
        elif path == '/api/skill/edit':
            if not self.require_auth():
                return
            self.handle_edit(force_caller='skill')
        elif path == '/api/gpt/generate':
            if not self.require_auth():
                return
            self.handle_gpt_generate()
        elif path == '/api/gpt/edit':
            if not self.require_auth():
                return
            self.handle_gpt_edit()
        elif path == '/api/upscale/run':
            if not self.require_auth():
                return
            self.handle_upscale_run()
        elif path == '/api/upscale/component/install':
            if not self.require_auth():
                return
            self.handle_upscale_component_install()
        elif path == '/api/upscale/component/remove':
            if not self.require_auth():
                return
            self.handle_upscale_component_remove()
        elif path == '/api/gpt/config':
            if not self.require_auth():
                return
            self.handle_gpt_config_save()
        elif path == '/api/system/settings':
            if not self.require_auth():
                return
            self.handle_system_settings_save()
        elif path.startswith('/api/gpt-pool/'):
            if not self.require_auth():
                return
            self.handle_chatgpt_pool_post(path)
        elif path.startswith('/api/managed-codex-oauth/'):
            if not self.require_auth():
                return
            self.handle_managed_codex_oauth_post(path)
        elif path == '/api/editable-files/send':
            if not self.require_auth():
                return
            self.handle_editable_file_send()
        elif path == '/api/editable-files/delete':
            if not self.require_auth():
                return
            self.handle_editable_file_delete()
        elif path == '/api/custom/generate':
            if not self.require_auth():
                return
            self.handle_custom_generate()
        elif path == '/api/spell/generate-prompt':
            if not self.require_auth():
                return
            self.handle_spell_generate_prompt()
        elif path == '/api/prompt/config':
            if not self.require_auth():
                return
            self.handle_prompt_config_save()
        elif path == '/api/prompt/polish':
            if not self.require_auth():
                return
            self.handle_prompt_polish()
        elif path == '/api/prompt/assistant-chat/stream':
            if not self.require_auth():
                return
            self.handle_prompt_assistant_chat_stream()
        elif path == '/api/prompt/assistant-chat':
            if not self.require_auth():
                return
            self.handle_prompt_assistant_chat()
        elif path == '/api/prompt/safe-rewrite':
            if not self.require_auth():
                return
            self.handle_prompt_safe_rewrite()
        elif path == '/api/prompt/image-analysis':
            if not self.require_auth():
                return
            self.handle_prompt_image_analysis()
        elif path == '/api/prompt/versions/generate':
            if not self.require_auth():
                return
            self.handle_prompt_versions_generate()
        elif path == '/api/prompt/chat':
            if not self.require_auth():
                return
            self.handle_prompt_chat()
        elif path == '/api/prompt/style-presets/extract':
            if not self.require_auth():
                return
            self.handle_prompt_style_preset_extract()
        elif path == '/api/prompt/style-presets':
            if not self.require_auth():
                return
            self.handle_prompt_style_preset_save()
        elif path == '/api/prompt/versions':
            if not self.require_auth():
                return
            self.handle_prompt_version_save()
        elif path == '/api/prompt-library/blocks/save':
            if not self.require_auth():
                return
            self.handle_prompt_library_block_save()
        elif path == '/api/prompt-library/blocks/delete':
            if not self.require_auth():
                return
            self.handle_prompt_library_block_delete()
        elif path == '/api/prompt-library/blocks/use':
            if not self.require_auth():
                return
            self.handle_prompt_library_block_use()
        elif path == '/api/prompt-library/blocks/extract':
            if not self.require_auth():
                return
            self.handle_prompt_library_blocks_extract()
        elif path == '/api/prompt-library/templates/save':
            if not self.require_auth():
                return
            self.handle_prompt_library_template_save()
        elif path == '/api/prompt-library/templates/delete':
            if not self.require_auth():
                return
            self.handle_prompt_library_template_delete()
        elif path == '/api/comfy/run':
            if not self.require_auth():
                return
            self.handle_comfy_run()
        elif path == '/api/comfy/send_tg':
            if not self.require_auth():
                return
            self.handle_comfy_send_tg()
        elif path == '/api/history/export_tg':
            if not self.require_auth():
                return
            self.handle_history_export_tg()
        elif path == '/api/assets/meta':
            if not self.require_auth():
                return
            self.handle_asset_meta()
        elif path == '/api/assets/health/cleanup':
            if not self.require_auth():
                return
            self.handle_asset_health_cleanup()
        elif path == '/api/assets/undo-delete':
            if not self.require_auth():
                return
            self.handle_asset_undo_delete()
        elif path == '/api/assets/delete-batch':
            if not self.require_auth():
                return
            self.handle_asset_delete_batch()
        elif path == '/api/assets/sets':
            if not self.require_auth():
                return
            self.handle_asset_set_post()
        elif path == '/api/desktop/workflow/save':
            if not self.require_auth():
                return
            self.handle_desktop_workflow_save()
        elif path == '/api/prompt-sources/sync':
            if not self.require_auth():
                return
            self.handle_prompt_source_sync()
        elif path == '/api/prompt-sources/stop':
            if not self.require_auth():
                return
            self.handle_prompt_source_stop()
        elif path == '/api/tasks/batch':
            if not self.require_auth():
                return
            self.handle_task_batch()
        elif path.startswith('/api/batches/'):
            if not self.require_auth():
                return
            parts = path.strip('/').split('/')
            batch_id = urllib.parse.unquote(parts[2]) if len(parts) >= 3 else ''
            action = parts[3] if len(parts) >= 4 else ''
            self.handle_batch_control(batch_id, action)
        elif path.startswith('/api/tasks/') and path.endswith('/cancel'):
            if not self.require_auth():
                return
            task_id = path.split('/')[-2]
            self.handle_task_cancel(task_id)
        elif path.startswith('/api/tasks/') and path.endswith('/retry'):
            if not self.require_auth():
                return
            task_id = path.split('/')[-2]
            self.handle_task_retry(task_id)
        elif path == '/api/layout/drafts' or path.startswith('/api/layout/drafts/'):
            if not self.require_auth():
                return
            self.handle_layout_draft_post(parsed)
        elif path == '/api/auth/login':
            self.handle_login()
        elif path == '/api/auth/verify':
            self.handle_auth_verify()
        else:
            self.send_error(404, "Not Found")

    def do_PATCH(self):
        """处理 PATCH 请求"""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == '/api/system/settings':
            if not self.require_auth():
                return
            self.handle_system_settings_save()
        else:
            self.send_error(404, "Not Found")

    def do_PUT(self):
        """处理 PUT 请求"""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith('/api/layout/drafts/'):
            if not self.require_auth():
                return
            self.handle_layout_draft_post(parsed)
        else:
            self.send_error(404, "Not Found")

    def send_json(self, data, status=200, extra_headers=None):
        """发送 JSON 响应"""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self._apply_cors_headers()
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def read_json_body(self, max_bytes=64 * 1024 * 1024):
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > max_bytes:
            raise ValueError('请求体过大')
        body = self.rfile.read(content_length)
        return json.loads(body or b'{}')

    def handle_desktop_workflow_save(self):
        """Save a desktop workflow JSON file to a user-provided local path."""
        tmp_path = None
        try:
            data = self.read_json_body(max_bytes=192 * 1024 * 1024)
            payload = data.get('payload')
            if not isinstance(payload, dict):
                self.send_json({"ok": False, "error": "工作流内容格式错误"}, 400)
                return

            raw_path = str(data.get('path') or data.get('file_path') or data.get('filePath') or '').strip()
            if not raw_path or '\x00' in raw_path:
                self.send_json({"ok": False, "error": "请填写保存路径"}, 400)
                return

            target = Path(raw_path).expanduser()
            if not target.is_absolute():
                target = Path.home() / 'Downloads' / target
            target = target.resolve()
            if not target.name.lower().endswith(('.tcflow.json', '.json')):
                self.send_json({"ok": False, "error": "工作流文件必须保存为 .tcflow.json 或 .json"}, 400)
                return
            if target.exists() and target.is_dir():
                self.send_json({"ok": False, "error": "保存路径不能是文件夹"}, 400)
                return
            if target.exists() and not _coerce_bool(data.get('overwrite'), False):
                self.send_json({"ok": False, "error": "文件已存在", "path": str(target)}, 409)
                return

            target.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(tmp_path, target)
            self.send_json({
                "ok": True,
                "path": str(target),
                "filename": target.name,
                "bytes": target.stat().st_size,
            })
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            print(f"❌ 工作流文件保存失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)
        finally:
            try:
                if tmp_path and tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass

    def handle_pose_assets_status(self):
        try:
            self.send_json(pose_assets_status())
        except Exception as e:
            print(f"❌ pose assets status failed: {e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_layout_fonts(self):
        """列出项目内置字体，供排版编辑器按需加载。"""
        font_dir = PROJECT_ROOT / 'font'
        extensions = {'.ttf', '.otf', '.ttc', '.woff', '.woff2'}

        def infer_weight(stem):
            lower = stem.lower()
            if 'thin' in lower:
                return 100
            if 'extralight' in lower or lower.endswith('-el'):
                return 200
            if 'light' in lower or lower.endswith('-l'):
                return 300
            if 'medium' in lower or lower.endswith('-m'):
                return 500
            if 'semibold' in lower or lower.endswith('-sb') or 'demibold' in lower:
                return 600
            if 'extrabold' in lower or lower.endswith('-h'):
                return 800
            if 'black' in lower or 'heavy' in lower:
                return 900
            if 'bold' in lower or lower.endswith('-b'):
                return 700
            return 400

        def normalize_family(stem):
            family = stem
            suffixes = [
                'VariableFont_wght',
                'ExtraLight',
                'ExtraBold',
                'SemiBold',
                'Regular',
                'Medium',
                'Light',
                'Black',
                'Heavy',
                'Bold',
                'Thin',
                'EL',
                'SB',
                'B',
                'H',
                'L',
                'M',
                'R',
            ]
            changed = True
            while changed:
                changed = False
                for suffix in suffixes:
                    for separator in ('-', '_', ' '):
                        tail = f'{separator}{suffix}'
                        if family.endswith(tail):
                            family = family[:-len(tail)]
                            changed = True
            return family.strip('-_ ') or stem

        if not font_dir.exists():
            self.send_json({"fonts": []})
            return

        groups = {}
        for path in sorted(font_dir.iterdir(), key=lambda item: item.name.lower()):
            if not path.is_file() or path.suffix.lower() not in extensions:
                continue
            stem = path.stem
            family = normalize_family(stem)
            face = {
                "file": path.name,
                "url": f"/font/{urllib.parse.quote(path.name)}",
                "weight": infer_weight(stem),
                "style": "normal",
            }
            groups.setdefault(family, {
                "family": family,
                "label": family,
                "faces": [],
            })["faces"].append(face)

        fonts = sorted(groups.values(), key=lambda item: item["label"].lower())
        self.send_json({"fonts": fonts})

    def send_binary_file(self, path):
        file_path = Path(path)
        content_type = mimetypes.guess_type(str(file_path))[0] or 'application/octet-stream'
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(file_path.stat().st_size))
        self.send_header('Cache-Control', 'private, max-age=60')
        self._apply_cors_headers()
        self.end_headers()
        with open(file_path, 'rb') as f:
            self.wfile.write(f.read())

    def handle_layout_draft_get(self, parsed):
        """读取排版草稿、预览图、导出图或草稿资产。"""
        parts = parsed.path.strip('/').split('/')
        if len(parts) < 4:
            self.send_json({"error": "缺少草稿 ID"}, 400)
            return

        draft_id = parts[3]
        try:
            if len(parts) == 4:
                self.send_json(load_layout_draft(draft_id))
                return

            kind = parts[4]
            if kind in ('preview', 'export'):
                self.send_binary_file(get_layout_draft_file(draft_id, kind))
                return
            if kind == 'assets' and len(parts) >= 6:
                asset_name = urllib.parse.unquote(parts[5])
                self.send_binary_file(get_layout_draft_file(draft_id, 'asset', asset_name))
                return

            self.send_json({"error": "排版草稿资源不存在"}, 404)
        except FileNotFoundError as e:
            self.send_json({"error": str(e)}, 404)
        except Exception as e:
            self.send_json({"error": str(e)}, 400)

    def handle_layout_draft_list(self, parsed):
        """列出排版草稿。"""
        try:
            query = urllib.parse.parse_qs(parsed.query)
            limit = int(query.get('limit', [50])[0])
            offset = int(query.get('offset', [0])[0])
            self.send_json({"drafts": list_layout_drafts(limit=limit, offset=offset)})
        except Exception as e:
            self.send_json({"error": str(e)}, 400)

    def handle_layout_draft_post(self, parsed):
        """创建或更新排版草稿。"""
        parts = parsed.path.strip('/').split('/')
        try:
            data = self.read_json_body()
        except Exception:
            self.send_json({"error": "请求体格式错误"}, 400)
            return

        try:
            if parsed.path == '/api/layout/drafts':
                draft = create_layout_draft(
                    title=str(data.get('title') or '排版工作区'),
                    node_id=str(data.get('node_id') or ''),
                    project=data.get('project') or {},
                    preview_data_url=str(data.get('preview_data_url') or ''),
                    export_data_url=str(data.get('export_data_url') or ''),
                )
                self.send_json(draft, 201)
                return

            if len(parts) < 4:
                self.send_json({"error": "缺少草稿 ID"}, 400)
                return

            draft_id = parts[3]
            if len(parts) == 4:
                draft = update_layout_draft(
                    draft_id,
                    title=data.get('title') if 'title' in data else None,
                    node_id=data.get('node_id') if 'node_id' in data else None,
                    project=data.get('project') if 'project' in data else None,
                    preview_data_url=str(data.get('preview_data_url') or ''),
                    export_data_url=str(data.get('export_data_url') or ''),
                )
                self.send_json(draft)
                return

            action = parts[4]
            if action == 'asset':
                asset = save_layout_draft_asset(
                    draft_id,
                    filename=str(data.get('filename') or ''),
                    data_url=str(data.get('data_url') or ''),
                )
                self.send_json(asset, 201)
                return

            if action in ('preview', 'export'):
                draft = update_layout_draft(
                    draft_id,
                    preview_data_url=str(data.get('data_url') or '') if action == 'preview' else '',
                    export_data_url=str(data.get('data_url') or '') if action == 'export' else '',
                )
                self.send_json(draft)
                return

            if action == 'publish':
                self.send_json(self.publish_layout_draft(draft_id, data), 201)
                return

            self.send_json({"error": "排版草稿操作不存在"}, 404)
        except FileNotFoundError as e:
            self.send_json({"error": str(e)}, 404)
        except Exception as e:
            self.send_json({"error": str(e)}, 400)

    def publish_layout_draft(self, draft_id, data):
        """把排版草稿导出为正式历史记录。"""
        draft = load_layout_draft(draft_id)
        title = str(data.get('title') or draft.get('title') or '排版导出').strip()
        prompt = str(data.get('prompt') or title or '排版导出').strip()
        node_id = str(data.get('node_id') or draft.get('node_id') or '').strip()
        data_url = str(data.get('data_url') or '').strip()

        from datetime import datetime
        now = datetime.now()
        created_at = int(time.time())
        timestamp = now.strftime('%Y%m%d_%H%M%S')
        draft_suffix = str(draft_id)[-8:]

        if data_url:
            image_bytes, _mime_type, extension = _decode_data_uri_image(data_url)
            filename = f"layout_{timestamp}_{draft_suffix}{extension}"
        else:
            source_path = get_layout_draft_file(draft_id, 'export')
            extension = source_path.suffix.lower() if source_path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp') else '.png'
            filename = f"layout_{timestamp}_{draft_suffix}{extension}"

        output_dir = daily_output_dir(now)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename

        if data_url:
            with open(output_path, 'wb') as f:
                f.write(image_bytes)
        else:
            shutil.copyfile(source_path, output_path)

        sidecar = output_dir / f"{Path(filename).stem}.txt"
        with open(sidecar, 'w', encoding='utf-8') as f:
            f.write(prompt)
            f.write('\n\n')
            f.write(f"layout_draft_id: {draft_id}\n")
            if node_id:
                f.write(f"layout_node_id: {node_id}\n")
        try:
            sidecar_content = sidecar.read_text(encoding='utf-8')
            write_obsidian_prompt_sidecar(output_path, sidecar_content, txt_path=sidecar)
        except Exception as exc:
            print(f"⚠️ 写入 Obsidian 提示词 md 失败: {exc}")

        save_thumbnail(str(output_path), filename)

        task_id = f"layout_{created_at}_{random.randint(1000, 9999)}"
        params = {
            'draft_id': draft_id,
            'node_id': node_id,
            'title': title,
            'ratio': 'layout',
            'archive_dir': str(output_dir),
        }
        create_task(task_id, prompt, params, status='succeeded', task_type='layout-export')
        update_task(
            task_id,
            'succeeded',
            result_file=filename,
            result_files=json.dumps([filename], ensure_ascii=False),
            stage='done',
            progress_text='排版导出完成',
            finished_at=created_at,
        )

        return {
            'ok': True,
            'task_id': task_id,
            'status': 'succeeded',
            'type': 'layout-export',
            'prompt': prompt,
            'params': params,
            'result_file': filename,
            'output_file': filename,
            'result_files': [filename],
            'output_files': [filename],
            'image_paths': [f"/image/{filename}"],
            'primary_image_path': f"/image/{filename}",
            'created_at': created_at,
            'updated_at': created_at,
            'progress_text': '排版导出完成',
        }
    
    def handle_login(self):
        """处理密码登录并写入 HttpOnly Cookie"""
        if not _auth_enabled():
            self.send_json({
                "ok": True,
                "auth_enabled": False,
                "message": "未配置访问密码，鉴权自动关闭"
            })
            return

        client_ip = _request_client_ip(self.headers, self.client_address)
        locked, retry_after = _login_lock_state(client_ip)
        if locked:
            self.send_json(_login_locked_payload(retry_after), 429)
            return

        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body or b'{}')
        except Exception:
            self.send_json({"ok": False, "error": "请求体格式错误"}, 400)
            return

        password = str(data.get('password') or data.get('apiKey') or '').strip()
        if password != AUTH_PASSWORD:
            locked, retry_after = _record_login_failure(client_ip)
            if locked:
                self.send_json(_login_locked_payload(retry_after), 429)
                return
            self.send_json({"ok": False, "error": "密码错误"}, 401)
            return

        _clear_login_failures(client_ip)
        cookie_value = _build_auth_cookie_value()
        cookie_parts = [
            f"{AUTH_COOKIE_NAME}={cookie_value}",
            f"Max-Age={AUTH_COOKIE_MAX_AGE}",
            "Path=/",
            "HttpOnly",
            "SameSite=Lax",
        ]
        self.send_json({
            "ok": True,
            "auth_enabled": True,
            "auth_token": cookie_value,
            "max_age": AUTH_COOKIE_MAX_AGE,
            "message": "登录成功"
        }, extra_headers={"Set-Cookie": "; ".join(cookie_parts)})

    def _send_auth_success_cookie(self, message):
        cookie_value = _build_auth_cookie_value()
        cookie_parts = [
            f"{AUTH_COOKIE_NAME}={cookie_value}",
            f"Max-Age={AUTH_COOKIE_MAX_AGE}",
            "Path=/",
            "HttpOnly",
            "SameSite=Lax",
        ]
        self.send_json({
            "ok": True,
            "auth_enabled": True,
            "auth_token": cookie_value,
            "max_age": AUTH_COOKIE_MAX_AGE,
            "message": message
        }, extra_headers={"Set-Cookie": "; ".join(cookie_parts)})
    
    def handle_auth_verify(self):
        """验证当前 Cookie 是否有效"""
        if not _auth_enabled():
            self.send_json({
                "ok": True,
                "auth_enabled": False,
                "message": "未配置访问密码，鉴权自动关闭"
            })
            return

        if self.is_authenticated():
            self._send_auth_success_cookie("验证成功")
            return

        self.send_json({
            "ok": False,
            "auth_enabled": True,
            "error": "Unauthorized",
            "message": "需要先输入访问密码"
        }, 401)
    
    def handle_generate(self, force_caller=None):
        """处理生成请求（支持 skill 调用托底策略）"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            prompt = data.get('prompt', '')
            incoming_params = data.get('params', {}) if isinstance(data.get('params'), dict) else {}
            params = {
                'ratio': _coerce_image_ratio(data.get('ratio', incoming_params.get('ratio', '1:1')), '1:1'),
                'style': str(data.get('style', incoming_params.get('style', 'raw')) or 'raw').strip() or 'raw',
                'quality': _coerce_google_quality(data.get('quality', incoming_params.get('quality', '2k')), '2k'),
                'model': _coerce_model(data.get('model', incoming_params.get('model', DEFAULT_GOOGLE_IMAGE_MODEL))),
                'max_tokens': _coerce_google_max_tokens(data.get('max_tokens', data.get('maxTokens', incoming_params.get('max_tokens', incoming_params.get('maxTokens'))))),
                'archive_enabled': _coerce_bool(
                    data.get(
                        'archive_enabled',
                        data.get('archiveEnabled', incoming_params.get('archive_enabled', incoming_params.get('archiveEnabled')))
                    ),
                    True,
                ),
                'telegram_enabled': _coerce_bool(
                    data.get(
                        'telegram_enabled',
                        data.get('telegramEnabled', incoming_params.get('telegram_enabled', incoming_params.get('telegramEnabled')))
                    ),
                    True,
                ),
            }
            temperature = _coerce_google_temperature(data.get('temperature', incoming_params.get('temperature')))
            if temperature is not None:
                params['temperature'] = temperature
            for k, v in incoming_params.items():
                params.setdefault(k, v)
            params['max_tokens'] = _coerce_google_max_tokens(params.get('max_tokens'))
            temperature = _coerce_google_temperature(params.get('temperature'))
            if temperature is None:
                params.pop('temperature', None)
            else:
                params['temperature'] = temperature
            if 'fallback_resolution' in params:
                params['fallback_resolution'] = _coerce_gpt_resolution(params.get('fallback_resolution'))
            model = params.get('model', '')
            _attach_lineage_params(params, data)

            if not prompt:
                self.send_json({"error": "Prompt is required"}, 400)
                return

            # 统一 caller：query/body/force_caller
            caller = (force_caller or data.get('caller') or params.get('caller') or 'webapp').strip().lower()
            if caller not in ('webapp', 'skill'):
                caller = 'webapp'
            params['caller'] = caller

            # skill 默认开启托底（可被显式关闭）
            fallback_cfg = params.get('fallback') if isinstance(params.get('fallback'), dict) else {}
            if caller == 'skill':
                fallback_cfg.setdefault('enabled', True)
                fallback_cfg.setdefault('target', 'gpt')
                fallback_cfg.setdefault('retryable_only', True)
            params['fallback'] = fallback_cfg

            # 生成任务 ID
            task_id = f"gen_{int(time.time())}_{random.randint(1000, 9999)}"

            # 根据 model 确定任务类型
            task_type = 'gpt' if 'gpt' in str(model).lower() else 'google-gen'

            # 创建任务记录（状态为 queued）
            create_task(task_id, prompt, params, status='queued', task_type=task_type)

            # 启动后台线程处理
            if not self.start_generation_task(task_id, process_task, (task_id, prompt, params)):
                return

            self.send_json({
                "task_id": task_id,
                "status": "queued",
                "message": "已提交图片生成任务，请等待...",
                "type": task_type,
                "caller": caller,
                "fallback": fallback_cfg
            }, 202)

        except Exception as e:
            self.send_json({"error": str(e)}, 500)
    
    def handle_edit(self, force_caller=None):
        """处理编辑请求（支持 skill 调用托底策略）"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            prompt = data.get('prompt', '')
            images = data.get('images', [])

            incoming_params = data.get('params', {}) if isinstance(data.get('params'), dict) else {}

            # 兼容前端顶层字段 + params 字段
            params = {
                'ratio': _coerce_image_ratio(data.get('ratio', incoming_params.get('ratio', '1:1')), '1:1'),
                'quality': _coerce_google_edit_quality(data.get('quality', incoming_params.get('quality', 'hd'))),
                'model': _coerce_model(data.get('model', incoming_params.get('model', DEFAULT_GOOGLE_IMAGE_MODEL))),
                'max_tokens': _coerce_google_max_tokens(data.get('max_tokens', data.get('maxTokens', incoming_params.get('max_tokens', incoming_params.get('maxTokens'))))),
                'feature': str(data.get('feature', incoming_params.get('feature', 'edit')) or 'edit').strip() or 'edit',
                'style': str(data.get('style', incoming_params.get('style', 'raw')) or 'raw').strip() or 'raw',
                'archive_enabled': _coerce_bool(
                    data.get(
                        'archive_enabled',
                        data.get('archiveEnabled', incoming_params.get('archive_enabled', incoming_params.get('archiveEnabled')))
                    ),
                    True,
                ),
                'telegram_enabled': _coerce_bool(
                    data.get(
                        'telegram_enabled',
                        data.get('telegramEnabled', incoming_params.get('telegram_enabled', incoming_params.get('telegramEnabled')))
                    ),
                    True,
                ),
            }
            temperature = _coerce_google_temperature(data.get('temperature', incoming_params.get('temperature')))
            if temperature is not None:
                params['temperature'] = temperature

            # 保留其余参数（如 fallback）
            for k, v in incoming_params.items():
                params.setdefault(k, v)
            params['max_tokens'] = _coerce_google_max_tokens(params.get('max_tokens'))
            temperature = _coerce_google_temperature(params.get('temperature'))
            if temperature is None:
                params.pop('temperature', None)
            else:
                params['temperature'] = temperature
            _attach_lineage_params(params, data)

            if not prompt:
                self.send_json({"error": "Prompt is required"}, 400)
                return

            if not images or len(images) == 0:
                self.send_json({"error": "请上传至少一张图片"}, 400)
                return

            # 统一 caller：query/body/force_caller
            caller = (force_caller or data.get('caller') or params.get('caller') or 'webapp').strip().lower()
            if caller not in ('webapp', 'skill'):
                caller = 'webapp'
            params['caller'] = caller

            # skill 默认开启托底（可被显式关闭）
            fallback_cfg = params.get('fallback') if isinstance(params.get('fallback'), dict) else {}
            if caller == 'skill':
                fallback_cfg.setdefault('enabled', True)
                fallback_cfg.setdefault('target', 'gpt')
                fallback_cfg.setdefault('retryable_only', True)
            params['fallback'] = fallback_cfg

            # 生成任务 ID
            task_id = f"edit_{int(time.time())}_{random.randint(1000, 9999)}"

            # 创建任务记录（状态为 queued）
            create_task(task_id, prompt, params, status='queued', task_type='google-edit')

            # 启动后台线程处理
            if not self.start_generation_task(task_id, process_edit_task, (task_id, prompt, images, params)):
                return

            self.send_json({
                "task_id": task_id,
                "status": "queued",
                "message": "已提交图片编辑任务，请等待...",
                "caller": caller,
                "fallback": fallback_cfg,
            }, 202)

        except Exception as e:
            self.send_json({"error": str(e)}, 500)
    
    def handle_gpt_generate(self):
        """处理 GPT 生成请求（使用 ChatGPT/Codex 浏览器自动化）"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            
            prompt = data.get('prompt', '')
            ratio = _coerce_image_ratio(data.get('ratio'), '1:1')
            resolution = _coerce_gpt_resolution(data.get('resolution'))
            quality = _coerce_gpt_quality(data.get('quality', 'auto'))
            moderation = _coerce_gpt_moderation(data.get('moderation', 'auto'))
            gpt_task_type = _coerce_gpt_task_type(data.get('task_type', data.get('taskType', data.get('gpt_task_type', data.get('gptTaskType')))))
            prompt_mode = _coerce_prompt_mode(data.get('prompt_mode', data.get('promptMode', 'smart')))
            gpt_provider_route = _coerce_gpt_provider_route(
                data.get('gpt_provider_route', data.get('gptProviderRoute', data.get('provider_route', data.get('providerRoute'))))
            )
            if gpt_task_type != 'image':
                gpt_provider_route = 'chatgpt_pool'
            main_model = _coerce_gpt_main_model(data.get('main_model', data.get('mainModel')))
            reasoning_effort = _coerce_gpt_reasoning_effort(data.get('reasoning_effort', data.get('reasoningEffort')))
            image_count = _coerce_gpt_image_count(data, prompt)
            archive_enabled = _coerce_bool(data.get('archive_enabled', data.get('archiveEnabled')), True)
            telegram_enabled = _coerce_bool(data.get('telegram_enabled', data.get('telegramEnabled')), True)
            use_third_party_api = _gpt_route_uses_third_party(gpt_provider_route) or _coerce_use_third_party_api(
                data.get('use_third_party_api'),
                data.get('useThirdPartyApi'),
                data.get('third_party_api'),
                data.get('thirdPartyApi'),
            )
            editable_images = data.get('base64_images') if isinstance(data.get('base64_images'), list) else data.get('images')
            if not isinstance(editable_images, list):
                editable_images = []
            
            if not prompt:
                self.send_json({"error": "Prompt is required"}, 400)
                return

            # 生成任务 ID
            task_id = f"gpt_{int(time.time())}_{random.randint(1000, 9999)}"
            
            # 创建任务记录
            params = {
                'ratio': ratio,
                'resolution': resolution,
                'quality': quality,
                'image_count': image_count,
                'moderation': moderation,
                'task_type': gpt_task_type,
                'prompt_mode': prompt_mode,
                'gpt_provider_route': gpt_provider_route,
                'main_model': main_model,
                'reasoning_effort': reasoning_effort,
                'archive_enabled': archive_enabled,
                'telegram_enabled': telegram_enabled,
                'use_third_party_api': use_third_party_api,
            }
            _attach_lineage_params(params, data)
            create_task(task_id, prompt, params, status='queued', task_type='gpt-file' if gpt_task_type != 'image' else 'gpt')
            
            if gpt_task_type != 'image':
                target = process_gpt_editable_file_task
                args = (task_id, gpt_task_type, prompt, editable_images, prompt_mode, gpt_provider_route, archive_enabled, telegram_enabled)
            else:
                target = process_gpt_task
                args = (task_id, prompt, ratio, resolution, quality, image_count, moderation, prompt_mode, main_model, reasoning_effort, gpt_provider_route, use_third_party_api, archive_enabled, telegram_enabled)
            if not self.start_generation_task(task_id, target, args):
                return
            
            self.send_json({
                "task_id": task_id,
                "status": "queued",
                "message": "已提交 GPT 图片生成任务，请等待..."
            }, 202)
            
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_gpt_edit(self):
        """处理 GPT 图像编辑请求（使用本地 Codex runtime）"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body or b'{}')

            prompt = data.get('prompt', '')
            images = data.get('images', [])
            ratio = _coerce_image_ratio(data.get('ratio'), '1:1')
            resolution = _coerce_gpt_resolution(data.get('resolution'))
            quality = _coerce_gpt_quality(data.get('quality', 'auto'))
            moderation = _coerce_gpt_moderation(data.get('moderation', 'auto'))
            prompt_mode = _coerce_prompt_mode(data.get('prompt_mode', data.get('promptMode', 'smart')))
            gpt_provider_route = _coerce_gpt_provider_route(
                data.get('gpt_provider_route', data.get('gptProviderRoute', data.get('provider_route', data.get('providerRoute'))))
            )
            main_model = _coerce_gpt_main_model(data.get('main_model', data.get('mainModel')))
            reasoning_effort = _coerce_gpt_reasoning_effort(data.get('reasoning_effort', data.get('reasoningEffort')))
            archive_enabled = _coerce_bool(data.get('archive_enabled', data.get('archiveEnabled')), True)
            telegram_enabled = _coerce_bool(data.get('telegram_enabled', data.get('telegramEnabled')), True)
            use_third_party_api = _gpt_route_uses_third_party(gpt_provider_route) or _coerce_use_third_party_api(
                data.get('use_third_party_api'),
                data.get('useThirdPartyApi'),
                data.get('third_party_api'),
                data.get('thirdPartyApi'),
            )
            mask = data.get('mask')

            if not prompt:
                self.send_json({"error": "Prompt is required"}, 400)
                return
            if not images:
                self.send_json({"error": "请上传至少一张图片"}, 400)
                return

            task_id = f"gpt_edit_{int(time.time())}_{random.randint(1000, 9999)}"
            params = {
                'ratio': ratio,
                'resolution': resolution,
                'quality': quality,
                'image_count': 1,
                'source_image_count': len(images),
                'moderation': moderation,
                'prompt_mode': prompt_mode,
                'gpt_provider_route': gpt_provider_route,
                'main_model': main_model,
                'reasoning_effort': reasoning_effort,
                'archive_enabled': archive_enabled,
                'telegram_enabled': telegram_enabled,
                'use_third_party_api': use_third_party_api,
                'feature': 'edit',
            }
            if mask:
                params['has_mask'] = True
            _attach_lineage_params(params, data)
            create_task(task_id, prompt, params, status='queued', task_type='gpt-edit')

            if not self.start_generation_task(
                task_id,
                process_gpt_edit_task,
                (task_id, prompt, images, ratio, resolution, quality, moderation, mask, prompt_mode, main_model, reasoning_effort, use_third_party_api, gpt_provider_route, archive_enabled, telegram_enabled),
            ):
                return

            self.send_json({
                "task_id": task_id,
                "status": "queued",
                "message": "已提交 GPT 图片编辑任务，请等待..."
            }, 202)

        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_upscale_models(self):
        """返回本地高清放大模型状态。"""
        try:
            self.send_json({
                "ok": True,
                "model_dir": str(UPSCALE_MODEL_DIR),
                "models": available_upscale_models(UPSCALE_MODEL_DIR),
                "component": get_upscale_component_status(),
            })
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_upscale_component_status(self):
        try:
            self.send_json({"ok": True, **get_upscale_component_status()})
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_upscale_component_install(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length) if content_length else b'{}'
            data = json.loads(body or b'{}')
            self.send_json({"ok": True, **start_upscale_component_install(bool(data.get('force')))}, 202)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_upscale_component_remove(self):
        try:
            self.send_json({"ok": True, **remove_upscale_component()})
        except Exception as e:
            self.send_json({"error": str(e)}, 409)

    def handle_upscale_run(self):
        """处理本地高清放大请求。"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body or b'{}')

            images = data.get('images', [])
            if not isinstance(images, list):
                images = []
            image_data = next((str(item or '').strip() for item in images if str(item or '').strip()), '')
            if not image_data:
                self.send_json({"error": "请先连接或上传一张图片"}, 400)
                return

            incoming_params = data.get('params') if isinstance(data.get('params'), dict) else {}
            model_name = normalize_upscale_model(data.get('model', incoming_params.get('model')))
            model_status = next((item for item in available_upscale_models(UPSCALE_MODEL_DIR) if item.get('id') == model_name), {})
            if not model_status.get('available'):
                self.send_json({
                    "error": "高清放大组件尚未安装，请先完成组件下载。",
                    "component": get_upscale_component_status(),
                }, 409)
                return
            prompt = str(data.get('prompt') or incoming_params.get('prompt') or f'高清放大：{model_name}').strip()
            params = {
                'model': model_name,
                'scale': 4,
                'tile_size': _coerce_upscale_tile(data.get('tile_size', data.get('tileSize', incoming_params.get('tile_size', incoming_params.get('tileSize')))), 256),
                'tile_overlap': _coerce_upscale_tile(data.get('tile_overlap', data.get('tileOverlap', incoming_params.get('tile_overlap', incoming_params.get('tileOverlap')))), 32, minimum=0, maximum=256),
                'device': str(data.get('device', incoming_params.get('device', 'auto')) or 'auto').strip() or 'auto',
                'archive_enabled': True,
                'telegram_enabled': _coerce_bool(data.get('telegram_enabled', data.get('telegramEnabled', incoming_params.get('telegram_enabled', incoming_params.get('telegramEnabled')))), True),
                'source_image_count': len(images),
            }
            _attach_lineage_params(params, data)

            task_id = f"upscale_{int(time.time())}_{random.randint(1000, 9999)}"
            create_task(task_id, prompt, params, status='queued', task_type='upscale')
            if not self.start_generation_task(task_id, process_upscale_task, (task_id, prompt, image_data, params)):
                return

            self.send_json({
                "task_id": task_id,
                "status": "queued",
                "message": "已提交高清放大任务，请等待...",
                "type": "upscale",
            }, 202)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)
    
    def handle_custom_generate(self):
        """处理 Custom API 生成请求（GPT-5.4 @ localhost:8080）"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            
            prompt = data.get('prompt', '')
            ratio = _coerce_image_ratio(data.get('ratio'), '1:1')
            resolution = _coerce_gpt_resolution(data.get('resolution'))
            quality = _coerce_gpt_quality(data.get('quality', 'auto'))
            moderation = _coerce_gpt_moderation(data.get('moderation', 'auto'))
            
            if not prompt:
                self.send_json({"error": "Prompt is required"}, 400)
                return
            
            # 生成任务 ID
            task_id = f"custom_{int(time.time())}_{random.randint(1000, 9999)}"
            
            # 创建任务记录
            params = {
                'ratio': ratio,
                'resolution': resolution,
                'quality': quality,
                'moderation': moderation,
                'model': 'GPT-5.4'
            }
            create_task(task_id, prompt, params, status='queued', task_type='custom')
            
            # 启动后台线程处理
            if not self.start_generation_task(task_id, process_custom_task, (task_id, prompt, ratio, resolution, quality, moderation)):
                return
            
            self.send_json({
                "task_id": task_id,
                "status": "queued",
                "message": "已提交 Custom API 图片生成任务，请等待..."
            }, 202)
            
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_spell_generate_prompt(self):
        """处理咒术模块的结构化提示词生成请求"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body or b'{}')

            topic = str(data.get('topic') or data.get('prompt') or '').strip()
            if not topic:
                self.send_json({"error": "Topic is required"}, 400)
                return

            result = generate_structured_spell_prompt(topic)
            self.send_json(result)
        except ValueError as e:
            self.send_json({"error": str(e)}, 400)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_status(self, task_id):
        """处理状态查询"""
        task = get_task(task_id)
        if not task:
            # Old cached Telegram WebViews may keep polling stale task ids.
            # Return a terminal failed state instead of 404 so the client can recover.
            self.send_json(_missing_task_payload(task_id))
            return

        self.send_json(_status_response_task(task))

    def handle_generation_runs(self, parsed, task_id):
        """返回任务的 generation runs。"""
        try:
            query = urllib.parse.parse_qs(parsed.query or '')
            limit = _history_page_int((query.get('limit') or ['20'])[0], 20, minimum=1, maximum=200)
            offset = _history_page_int((query.get('offset') or ['0'])[0], 0, minimum=0, maximum=100000)
            runs = get_generation_runs(task_id, limit=limit, offset=offset)
            self.send_json({
                'task_id': task_id,
                'runs': runs,
                'count': len(runs),
            })
        except Exception as e:
            self.send_json({'error': str(e)}, 500)

    def handle_generation_events(self, parsed, run_id):
        """返回指定 generation run 的事件流。"""
        try:
            query = urllib.parse.parse_qs(parsed.query or '')
            limit = _history_page_int((query.get('limit') or ['200'])[0], 200, minimum=1, maximum=1000)
            offset = _history_page_int((query.get('offset') or ['0'])[0], 0, minimum=0, maximum=100000)
            run = get_generation_run(run_id)
            events = get_generation_events(run_id, limit=limit, offset=offset)
            self.send_json({
                'run_id': run_id,
                'task_id': run.get('task_id') if isinstance(run, dict) else '',
                'run': run,
                'events': events,
                'count': len(events),
            })
        except Exception as e:
            self.send_json({'error': str(e)}, 500)

    def handle_assets(self, parsed):
        """返回图库资产索引。"""
        try:
            query = urllib.parse.parse_qs(parsed.query)
            limit = int(query.get('limit', [200])[0])
            offset = int(query.get('offset', [0])[0])
            search = str(query.get('query', [''])[0] or '').strip()
            filter_value = str(query.get('filter', ['all'])[0] or 'all').strip().lower()
            tag = str(query.get('tag', [''])[0] or '').strip()

            provider = filter_value if filter_value in ('gpt', 'google', 'comfy', 'layout') else 'all'
            source = query.get('source', [''])[0] or ''
            if not source and filter_value in ('linked', 'history', 'task_record', 'orphan', 'archive_only', 'missing_history'):
                source = filter_value
            orientation = str(query.get('orientation', [''])[0] or '').strip().lower()
            if not orientation and filter_value in ('landscape', 'portrait', 'square'):
                orientation = filter_value
            file_format = str(query.get('format', query.get('file_format', ['']))[0] or '').strip().lower()
            if not file_format and filter_value in ('png', 'jpg', 'jpeg', 'webp'):
                file_format = filter_value
            resolution = str(query.get('resolution', [''])[0] or '').strip().lower()
            if not resolution and filter_value in ('1k', '2k', '4k'):
                resolution = filter_value
            ratio = str(query.get('ratio', [''])[0] or '').strip().lower()
            favorite = filter_value == 'favorite' or str(query.get('favorite', [''])[0]).lower() in ('1', 'true', 'yes')
            hidden = filter_value == 'hidden' or str(query.get('hidden', [''])[0]).lower() in ('1', 'true', 'yes')
            include_hidden = hidden or str(query.get('include_hidden', [''])[0]).lower() in ('1', 'true', 'yes')

            self.send_json(list_gallery_assets(
                limit=limit,
                offset=offset,
                query=search,
                provider=provider,
                tag=tag,
                favorite=favorite,
                hidden=hidden,
                include_hidden=include_hidden,
                source=source,
                ratio=ratio,
                orientation=orientation,
                file_format=file_format,
                resolution=resolution,
            ))
        except Exception as e:
            self.send_json({"error": str(e)}, 400)

    def handle_asset_sets(self, parsed):
        """返回图库候选集。"""
        try:
            query = urllib.parse.parse_qs(parsed.query)
            limit = int(query.get('limit', [80])[0])
            offset = int(query.get('offset', [0])[0])
            search = str(query.get('query', [''])[0] or '').strip()
            tag = str(query.get('tag', [''])[0] or '').strip()
            self.send_json(list_asset_sets(
                limit=limit,
                offset=offset,
                query=search,
                tag=tag,
            ))
        except Exception as e:
            self.send_json({"error": str(e)}, 400)

    def handle_prompt_sources(self):
        """返回独立远程提示词源状态。"""
        try:
            self.send_json(list_prompt_sources())
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_source_items(self, parsed):
        """返回远程提示词源本地化条目，不进入图库资产索引。"""
        try:
            query = urllib.parse.parse_qs(parsed.query)
            limit = int(query.get('limit', [200])[0])
            offset = int(query.get('offset', [0])[0])
            self.send_json(list_prompt_source_items(
                source_slug=str(query.get('source', [''])[0] or '').strip(),
                query=str(query.get('query', [''])[0] or '').strip(),
                tag=str(query.get('tag', [''])[0] or '').strip(),
                style=str(query.get('style', [''])[0] or '').strip(),
                subject=str(query.get('subject', [''])[0] or '').strip(),
                item_type=str(query.get('type', [''])[0] or query.get('item_type', [''])[0] or '').strip(),
                limit=limit,
                offset=offset,
            ))
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)}, 400)

    def handle_prompt_source_sync(self):
        """启动远程提示词源同步任务。"""
        try:
            data = self.read_json_body(max_bytes=64 * 1024)
            self.send_json(start_prompt_source_sync(str(data.get('source') or 'all')), 202)
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)}, 400)

    def handle_prompt_source_stop(self):
        """停止正在运行的远程提示词源同步任务。"""
        try:
            data = self.read_json_body(max_bytes=64 * 1024)
            self.send_json(stop_prompt_source_sync(str(data.get('run_id') or data.get('runId') or '')))
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)}, 400)

    def handle_prompt_source_run(self, run_id):
        """查询远程提示词源同步任务。"""
        try:
            run = get_prompt_source_run(run_id)
            if not run:
                self.send_json({"ok": False, "error": "同步任务不存在"}, 404)
                return
            self.send_json({"ok": True, "run": run})
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_asset_set_post(self):
        """新建或更新图库候选集。"""
        try:
            data = self.read_json_body(max_bytes=4 * 1024 * 1024)
            set_id = data.get('set_id') or data.get('id') or ''
            if set_id:
                payload = {}
                if 'name' in data:
                    payload['name'] = data.get('name') or ''
                if 'asset_ids' in data or 'assetIds' in data:
                    payload['asset_ids'] = data.get('asset_ids') or data.get('assetIds') or []
                if 'tags' in data:
                    payload['tags'] = data.get('tags') or []
                if 'assets' in data:
                    payload['assets'] = data.get('assets') or []
                item = update_asset_set(set_id, **payload)
                self.send_json({"ok": True, "set": item})
            else:
                payload = {
                    "name": data.get('name') or '',
                    "asset_ids": data.get('asset_ids') or data.get('assetIds') or [],
                    "tags": data.get('tags') or [],
                    "assets": data.get('assets') or [],
                }
                item = create_asset_set(**payload)
                self.send_json({"ok": True, "set": item}, 201)
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)}, 400)

    def handle_asset_set_delete(self, set_id):
        """删除图库候选集。"""
        try:
            item = delete_asset_set(set_id)
            self.send_json({"ok": True, "set": item})
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)}, 400)

    def handle_asset_health(self):
        """检查图库资产、候选集和溯源引用健康状态。"""
        try:
            health = _collect_asset_health()
            public_health = {key: value for key, value in health.items() if key not in ('valid_asset_ids', 'all_asset_ids', 'missing_assets_all')}
            self.send_json({"ok": True, "health": public_health})
        except Exception as e:
            print(f"❌ 图库体检失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_system_diagnostics(self):
        """Return safe runtime configuration status without secret values."""
        try:
            self.send_json(_collect_system_diagnostics())
        except Exception as e:
            print(f"❌ 系统诊断失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_app_update_status(self):
        """Return the latest public CanvasHub release without exposing configuration."""
        self.send_json({"ok": True, **get_app_update_status()})

    def handle_system_settings(self):
        """Return editable project settings without secret values."""
        try:
            self.send_json(_collect_system_settings())
        except Exception as e:
            print(f"❌ 系统设置读取失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_system_settings_save(self):
        """Persist whitelisted project settings into settings.json."""
        try:
            data = self.read_json_body(max_bytes=128 * 1024)
            settings = _sanitize_system_settings_patch(data)
            if settings is None:
                self.send_json({"ok": False, "error": "设置格式错误"}, 400)
                return
            save_app_settings(settings)
            global AUTH_PASSWORD, TELEGRAM_AUTH_BOT_TOKEN, TELEGRAM_AUTH_ALLOWED_IDS
            AUTH_PASSWORD = _load_auth_password()
            TELEGRAM_AUTH_BOT_TOKEN, TELEGRAM_AUTH_ALLOWED_IDS = _load_telegram_auth_config()
            self.send_json(_collect_system_settings())
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            print(f"❌ 系统设置保存失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_gpt_config(self):
        """Return safe GPT runtime options for the desktop UI."""
        try:
            self.send_json(_collect_gpt_runtime_config())
        except Exception as e:
            print(f"❌ GPT 配置读取失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_gpt_config_save(self):
        """Persist non-secret GPT provider settings into project settings.json."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body or b'{}')
            patch = _sanitize_gpt_provider_patch(data)
            if not patch:
                self.send_json({"ok": False, "error": "没有可保存的 GPT 配置"}, 400)
                return
            update_app_settings_section("gpt_provider", patch)
            self.send_json(_collect_gpt_runtime_config())
        except Exception as e:
            print(f"❌ GPT 配置保存失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def _read_json_body(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        if not body:
            return {}
        data = json.loads(body)
        return data if isinstance(data, dict) else {}

    def handle_chatgpt_pool_status(self):
        """Return safe ChatGPT account-pool status for desktop settings."""
        try:
            self.send_json({"ok": True, "chatgpt_pool": _collect_chatgpt_pool_status()})
        except Exception as e:
            print(f"❌ ChatGPT 账号池状态读取失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_gpt_models(self, parsed):
        """Return account-scoped generation models for each GPT route."""
        try:
            query = urllib.parse.parse_qs(parsed.query or '')
            refresh = _coerce_bool((query.get('refresh') or [''])[0], False)
            self.send_json(get_gpt_model_catalog(force=refresh))
        except Exception as e:
            print(f"❌ GPT 模型目录读取失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 502)

    def handle_chatgpt_pool_accounts(self):
        """Proxy account list through server.py so the UI never sees sidecar auth."""
        try:
            data = _chatgpt_pool_request("GET", "/accounts")
            self.send_json(data)
        except Exception as e:
            print(f"❌ ChatGPT 账号池账号读取失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 502)

    def handle_managed_codex_oauth_status(self):
        """Return safe managed Codex OAuth status for desktop settings."""
        try:
            self.send_json({"ok": True, "managed_codex_oauth": get_managed_codex_oauth_status()})
        except Exception as e:
            print(f"❌ Managed Codex OAuth 状态读取失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_managed_codex_oauth_post(self, path):
        """Handle project-managed Codex OAuth mutations."""
        try:
            payload = self._read_json_body()
        except json.JSONDecodeError:
            self.send_json({"ok": False, "error": "请求体格式错误"}, 400)
            return

        try:
            if path == "/api/managed-codex-oauth/start":
                data = start_managed_codex_oauth_login(
                    open_browser=_coerce_bool(payload.get("open_browser", payload.get("openBrowser")), True),
                    force_reauth=_coerce_bool(payload.get("force_reauth", payload.get("forceReauth")), False),
                    email_hint=str(payload.get("email_hint") or payload.get("emailHint") or "").strip(),
                )
                self.send_json(data)
                return
            if path == "/api/managed-codex-oauth/finish":
                data = finish_managed_codex_oauth_callback(
                    callback_url=payload.get("callback_url") or payload.get("callback") or "",
                    code=payload.get("code") or "",
                    state=payload.get("state") or "",
                    session_id=payload.get("session_id") or payload.get("sessionId") or "",
                )
                self.send_json(data)
                return
            if path == "/api/managed-codex-oauth/refresh":
                self.send_json(refresh_managed_auth(
                    account_id=str(payload.get("account_id") or payload.get("accountId") or "").strip(),
                    refresh_all=_coerce_bool(payload.get("all", payload.get("refresh_all", payload.get("refreshAll"))), False),
                ))
                return
            if path == "/api/managed-codex-oauth/import":
                self.send_json(import_managed_auth_accounts(payload))
                return
            if path == "/api/managed-codex-oauth/update":
                account_id = str(payload.get("account_id") or payload.get("accountId") or "").strip()
                disabled = payload.get("disabled")
                if disabled is None and "status" in payload:
                    disabled = str(payload.get("status") or "").strip() in {"禁用", "disabled", "off"}
                self.send_json(update_managed_auth_account(
                    account_id,
                    disabled=None if disabled is None else _coerce_bool(disabled, False),
                    select=_coerce_bool(payload.get("select"), False),
                ))
                return
            if path == "/api/managed-codex-oauth/select":
                account_id = str(payload.get("account_id") or payload.get("accountId") or "").strip()
                self.send_json(update_managed_auth_account(account_id, disabled=False, select=True))
                return
            if path == "/api/managed-codex-oauth/delete":
                self.send_json(delete_managed_auth(
                    account_id=str(payload.get("account_id") or payload.get("accountId") or "").strip(),
                    delete_all=_coerce_bool(payload.get("all", payload.get("delete_all", payload.get("deleteAll"))), False),
                ))
                return
            if path == "/api/managed-codex-oauth/logout":
                self.send_json(delete_managed_auth(delete_all=True))
                return
            self.send_json({"ok": False, "error": "未知 managed_codex_oauth 操作"}, 404)
        except Exception as e:
            print(f"❌ Managed Codex OAuth 操作失败：{path} {e}")
            self.send_json({"ok": False, "error": str(e)}, 502)

    def handle_chatgpt_pool_post(self, path):
        """Proxy account-pool management mutations to the local sidecar."""
        if path == "/api/gpt-pool/oauth/open-clean":
            try:
                payload = self._read_json_body()
                data = _chatgpt_pool_open_authorize_url_clean(payload.get("authorize_url") or "")
                self.send_json(data)
            except json.JSONDecodeError:
                self.send_json({"ok": False, "error": "请求体格式错误"}, 400)
            except Exception as e:
                print(f"❌ ChatGPT 账号池干净窗口打开失败：{e}")
                self.send_json({"ok": False, "error": str(e)}, 400)
            return

        if path == "/api/gpt-pool/accounts/import-local-auth":
            try:
                payload = self._read_json_body()
                account, source_path = _chatgpt_pool_build_local_auth_account(payload.get("path") or "")
                data = _chatgpt_pool_request("POST", "/accounts/import", {"accounts": [account]})
                if isinstance(data, dict):
                    data["imported_from"] = source_path
                self.send_json(data)
            except json.JSONDecodeError:
                self.send_json({"ok": False, "error": "请求体格式错误"}, 400)
            except Exception as e:
                print(f"❌ ChatGPT 账号池本机 Auth 导入失败：{e}")
                self.send_json({"ok": False, "error": str(e)}, 502)
            return

        if path == "/api/gpt-pool/accounts/verify/start":
            try:
                payload = self._read_json_body()
                data = _chatgpt_pool_open_account_verification(
                    payload.get("account_id") or payload.get("accountId") or ""
                )
                self.send_json(data)
            except json.JSONDecodeError:
                self.send_json({"ok": False, "error": "请求体格式错误"}, 400)
            except Exception as e:
                print(f"❌ ChatGPT 账号池验证窗口打开失败：{e}")
                self.send_json({"ok": False, "error": str(e)}, 502)
            return

        if path == "/api/gpt-pool/accounts/verify/complete":
            try:
                payload = self._read_json_body()
                data = _chatgpt_pool_complete_account_verification(
                    payload.get("account_id") or payload.get("accountId") or "",
                    payload.get("debug_port") or payload.get("debugPort"),
                )
                self.send_json(data)
            except json.JSONDecodeError:
                self.send_json({"ok": False, "error": "请求体格式错误"}, 400)
            except Exception as e:
                print(f"❌ ChatGPT 账号池验证会话同步失败：{e}")
                self.send_json({"ok": False, "error": str(e)}, 502)
            return

        if path == "/api/gpt-pool/search":
            try:
                payload = self._read_json_body()
                data = search_chatgpt_pool(
                    str(payload.get("prompt") or payload.get("query") or ""),
                    model=str(payload.get("model") or ""),
                    timeout_seconds=payload.get("timeout_seconds") or payload.get("timeout"),
                )
                self.send_json(data)
            except json.JSONDecodeError:
                self.send_json({"ok": False, "error": "请求体格式错误"}, 400)
            except Exception as e:
                print(f"❌ ChatGPT 账号池检索失败：{e}")
                self.send_json({"ok": False, "error": str(e)}, 502)
            return

        routes = {
            "/api/gpt-pool/oauth/start": "/accounts/oauth/start",
            "/api/gpt-pool/oauth/finish": "/accounts/oauth/finish",
            "/api/gpt-pool/accounts/import": "/accounts/import",
            "/api/gpt-pool/accounts/refresh": "/accounts/refresh",
            "/api/gpt-pool/accounts/update": "/accounts/update",
            "/api/gpt-pool/accounts/delete": "/accounts/delete",
        }
        sidecar_path = routes.get(path)
        if not sidecar_path:
            self.send_json({"ok": False, "error": "未知账号池操作"}, 404)
            return
        try:
            payload = self._read_json_body()
            if path == "/api/gpt-pool/oauth/finish" and payload.get("callback_url") and not payload.get("callback"):
                payload["callback"] = payload.get("callback_url")
            request_timeout = 130 if path == "/api/gpt-pool/oauth/finish" else None
            data = _chatgpt_pool_request("POST", sidecar_path, payload, timeout=request_timeout)
            self.send_json(data)
        except json.JSONDecodeError:
            self.send_json({"ok": False, "error": "请求体格式错误"}, 400)
        except Exception as e:
            print(f"❌ ChatGPT 账号池代理失败：{path} {e}")
            self.send_json({"ok": False, "error": str(e)}, 502)

    def handle_prompt_config(self, parsed):
        """Return prompt-skill settings and runtime model options."""
        try:
            query = urllib.parse.parse_qs(parsed.query)
            provider = query.get("provider", [""])[0] or None
            self.send_json(_collect_prompt_skill_runtime_config(provider))
        except Exception as e:
            print(f"❌ Prompt Skill 配置读取失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_models(self, parsed):
        """Return dynamically discovered text model options for a prompt provider."""
        try:
            query = urllib.parse.parse_qs(parsed.query)
            provider = query.get("provider", [""])[0] or None
            self.send_json(discover_prompt_models(provider))
        except Exception as e:
            print(f"❌ Prompt Skill 模型读取失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_style_presets(self):
        """Return project-local style presets saved by the Prompt Drawer."""
        try:
            self.send_json({"ok": True, "presets": list_style_presets()})
        except Exception as e:
            print(f"❌ 风格预设读取失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_versions(self, parsed):
        """Return saved prompt versions."""
        try:
            query = urllib.parse.parse_qs(parsed.query)
            limit = _history_page_int(query.get('limit', [200])[0], 200, minimum=1, maximum=1000)
            self.send_json({"ok": True, "versions": list_prompt_versions(limit=limit)})
        except Exception as e:
            print(f"❌ Prompt versions 读取失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_library_blocks_list(self, parsed):
        """Return reusable short prompt blocks for slash insertion and editors."""
        try:
            query = urllib.parse.parse_qs(parsed.query)
            result = list_prompt_blocks(
                query=str(query.get('query', [''])[0] or '').strip(),
                module_type=str(query.get('module_type', [''])[0] or '').strip(),
                primary_type=str(query.get('primary_type', [''])[0] or '').strip(),
                favorite=_coerce_bool(query.get('favorite', [False])[0], False),
                limit=_history_page_int(query.get('limit', [500])[0], 500, minimum=1, maximum=1000),
                offset=_history_page_int(query.get('offset', [0])[0], 0, minimum=0, maximum=1000000),
            )
            self.send_json({"ok": True, **result})
        except Exception as e:
            print(f"❌ 提示词素材块读取失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_library_templates_list(self):
        """Return active system and user-defined prompt split rules."""
        try:
            self.send_json({"ok": True, "templates": list_prompt_templates()})
        except Exception as e:
            print(f"❌ 提示词模板读取失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_library_template_save(self):
        """Create or update one user-defined prompt split rule."""
        try:
            template = save_prompt_template(self.read_json_body(max_bytes=2 * 1024 * 1024))
            self.send_json({"ok": True, "template": template})
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            print(f"❌ 拆分规则保存失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_library_template_delete(self):
        """Soft-delete one user-defined prompt split rule."""
        try:
            data = self.read_json_body(max_bytes=64 * 1024)
            template = delete_prompt_template(data.get('id') or data.get('template_id'))
            self.send_json({"ok": True, "template": template})
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            print(f"❌ 拆分规则删除失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_config_save(self):
        """Persist non-secret prompt-skill settings into project settings.json."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body or b'{}')
            patch = _sanitize_prompt_skill_patch(data)
            if not patch:
                self.send_json({"ok": False, "error": "没有可保存的配置"}, 400)
                return
            update_app_settings_section("prompt_skill", patch)
            self.send_json(_collect_prompt_skill_runtime_config(patch.get("provider")))
        except Exception as e:
            print(f"❌ Prompt Skill 配置保存失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_polish(self):
        """Run the selected prompt skill and return full/compact prompt variants."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body or b'{}')
            text = str(data.get("text") or data.get("prompt") or "").strip()
            options = {
                "provider": data.get("provider"),
                "skill": data.get("skill"),
                "model": data.get("model"),
                "reasoning_effort": data.get("reasoning_effort") or data.get("reasoningEffort"),
            }
            try:
                result = polish_prompt(text, options)
            except Exception as exc:
                if not text:
                    raise
                print(f"⚠️ Prompt Skill 润色失败，尝试账号池 chat 兜底：{exc}")
                try:
                    result = _polish_prompt_with_chatgpt_pool_chat(text, exc)
                except Exception as fallback_exc:
                    print(f"⚠️ Prompt Skill 账号池 chat 兜底失败：{fallback_exc}")
                    raise exc
            self.send_json(result)
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            print(f"❌ Prompt Skill 润色失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_style_preset_save(self):
        """Persist one project-local style preset."""
        try:
            preset = save_style_preset(self.read_json_body(max_bytes=512 * 1024))
            self.send_json({"ok": True, "preset": preset})
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            print(f"❌ 风格预设保存失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_style_preset_extract(self):
        """Extract a reusable style preset draft from text-node context."""
        try:
            data = self.read_json_body(max_bytes=512 * 1024)
            preset = extract_style_preset(
                str(data.get("text") or data.get("prompt") or "").strip(),
                str(data.get("message") or data.get("direction") or "").strip(),
                {
                    "candidate": data.get("candidate") or "",
                    "history": data.get("history") if isinstance(data.get("history"), list) else [],
                    "provider": data.get("provider"),
                    "model": data.get("model"),
                    "reasoning_effort": data.get("reasoning_effort") or data.get("reasoningEffort") or "low",
                },
            )
            self.send_json({"ok": True, "preset": preset})
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            print(f"❌ 风格预设提取失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_version_save(self):
        """Persist one prompt candidate/version."""
        try:
            version = save_prompt_version(self.read_json_body(max_bytes=1024 * 1024))
            self.send_json({"ok": True, "version": version})
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            print(f"❌ Prompt version 保存失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_library_block_save(self):
        """Create or update one reusable short prompt block."""
        try:
            block = save_prompt_block(self.read_json_body(max_bytes=2 * 1024 * 1024))
            self.send_json({"ok": True, "block": block})
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            print(f"❌ 提示词素材块保存失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_library_block_delete(self):
        """Soft-delete one reusable short prompt block."""
        try:
            data = self.read_json_body(max_bytes=64 * 1024)
            block = delete_prompt_block(data.get('id') or data.get('block_id'))
            self.send_json({"ok": True, "block": block})
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 404)
        except Exception as e:
            print(f"❌ 提示词素材块删除失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_library_block_use(self):
        """Update block usage ranking after slash insertion."""
        try:
            data = self.read_json_body(max_bytes=64 * 1024)
            block = mark_prompt_block_used(data.get('id') or data.get('block_id'))
            self.send_json({"ok": True, "block": block})
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 404)
        except Exception as e:
            print(f"❌ 提示词素材块使用状态更新失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_library_blocks_extract(self):
        """Extract editable prompt-block candidates from text or one uploaded image."""
        try:
            data = self.read_json_body(max_bytes=64 * 1024 * 1024)
            mode = str(data.get('mode') or 'text').strip().lower()
            primary_type = str(data.get('primary_type') or '').strip()
            rule_id = str(data.get('rule_id') or '').strip()
            split_rule = resolve_prompt_template(rule_id, primary_type)
            if rule_id and not split_rule:
                raise ValueError("拆分规则不存在或已删除")
            if split_rule:
                primary_type = str(split_rule.get('primary_type') or primary_type).strip()
            options = {
                "provider": data.get("provider"),
                "model": data.get("model"),
                "reasoning_effort": data.get("reasoning_effort") or data.get("reasoningEffort") or ("medium" if mode == "image" else "low"),
            }
            if mode == 'image':
                images = data.get('images') if isinstance(data.get('images'), list) else []
                result = extract_reusable_prompt_blocks_from_image(
                    str(data.get('message') or data.get('direction') or '').strip(),
                    images,
                    primary_type,
                    options,
                    split_rule,
                )
            elif mode == 'text':
                result = extract_reusable_prompt_blocks(
                    str(data.get('text') or data.get('prompt') or '').strip(),
                    primary_type,
                    options,
                    split_rule,
                )
            else:
                self.send_json({"ok": False, "error": "不支持的素材块提取模式"}, 400)
                return
            self.send_json(result)
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            print(f"❌ 提示词素材块提取失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_assistant_chat(self):
        """Lightweight text-node Prompt Copilot discussion endpoint."""
        try:
            data = self.read_json_body(max_bytes=512 * 1024)
            text = str(data.get("text") or data.get("prompt") or "").strip()
            message = str(data.get("message") or "").strip()
            result = assistant_chat(text, message, {
                "provider": data.get("provider"),
                "model": data.get("model"),
                "reasoning_effort": data.get("reasoning_effort") or data.get("reasoningEffort") or "low",
                "style": data.get("style") if isinstance(data.get("style"), dict) else {},
                "history": data.get("history") if isinstance(data.get("history"), list) else [],
            })
            self.send_json({
                **result,
                "target": data.get("target") if isinstance(data.get("target"), dict) else {},
                "style": data.get("style") if isinstance(data.get("style"), dict) else {},
                "candidates": [],
            })
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            print(f"❌ Prompt Assistant Chat 失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def _write_ndjson_event(self, event):
        payload = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        self.wfile.write(payload)
        self.wfile.flush()

    def handle_prompt_assistant_chat_stream(self):
        """Stream text-node Prompt Copilot discussion deltas."""
        try:
            data = self.read_json_body(max_bytes=512 * 1024)
            text = str(data.get("text") or data.get("prompt") or "").strip()
            message = str(data.get("message") or "").strip()
            if not text and not message:
                self.send_json({"ok": False, "error": "请输入聊天内容或选择文本节点"}, 400)
                return
            options = {
                "provider": data.get("provider"),
                "model": data.get("model"),
                "reasoning_effort": data.get("reasoning_effort") or data.get("reasoningEffort") or "low",
                "style": data.get("style") if isinstance(data.get("style"), dict) else {},
                "history": data.get("history") if isinstance(data.get("history"), list) else [],
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("X-Accel-Buffering", "no")
            self._apply_cors_headers()
            self.end_headers()
            for event in assistant_chat_stream(text, message, options):
                if event.get("type") == "done":
                    event = {
                        **event,
                        "target": data.get("target") if isinstance(data.get("target"), dict) else {},
                        "style": data.get("style") if isinstance(data.get("style"), dict) else {},
                        "candidates": [],
                    }
                self._write_ndjson_event(event)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as e:
            print(f"❌ Prompt Assistant Chat 流式失败：{e}")
            try:
                self._write_ndjson_event({"type": "error", "ok": False, "error": str(e)})
            except Exception:
                pass

    def handle_prompt_safe_rewrite(self):
        """Rewrite one text-node prompt through the standalone safety adapter."""
        try:
            data = self.read_json_body(max_bytes=512 * 1024)
            prompt = str(data.get("prompt") or data.get("text") or "").strip()
            if not prompt:
                self.send_json({"ok": False, "error": "缺少要安全改写的提示词"}, 400)
                return
            result = safe_rewrite_prompt(prompt, {
                "provider": data.get("provider"),
                "model": data.get("model"),
                "reasoning_effort": data.get("reasoning_effort") or data.get("reasoningEffort") or "low",
                "style": data.get("style") if isinstance(data.get("style"), dict) else {},
            })
            zh_prompt = str(result.get("zh_prompt") or result.get("rewritten_prompt") or "").strip()
            en_prompt = str(result.get("en_prompt") or "").strip()
            now = int(time.time())
            base_candidate = {
                "kind": "safe_rewrite",
                "badge": "安全",
                "task_type": result.get("task_type"),
                "intent": result.get("intent") if isinstance(result.get("intent"), dict) else {},
                "risk_score": result.get("risk_score"),
                "risk_level": result.get("risk_level"),
                "risk_flags": result.get("risk_flags") if isinstance(result.get("risk_flags"), list) else [],
                "changed_terms": result.get("changed_terms") if isinstance(result.get("changed_terms"), list) else [],
                "warnings": result.get("warnings") if isinstance(result.get("warnings"), list) else [],
                "adapter": result.get("adapter") if isinstance(result.get("adapter"), dict) else {},
                "created_at": now,
            }
            candidates = []
            if zh_prompt:
                candidates.append({
                    **base_candidate,
                    "id": f"safe_rewrite_zh_{now}_{random.randint(1000, 9999)}",
                    "kind": "safe_rewrite_zh",
                    "label": "安全审核版（中文）",
                    "text": zh_prompt,
                    "language": "zh",
                })
            if en_prompt:
                candidates.append({
                    **base_candidate,
                    "id": f"safe_rewrite_en_{now}_{random.randint(1000, 9999)}",
                    "kind": "safe_rewrite_en",
                    "label": "安全审核版（英文）",
                    "text": en_prompt,
                    "language": "en",
                })
            if not candidates:
                raise RuntimeError("安全审核版没有返回有效提示词")
            self.send_json({
                **result,
                "target": data.get("target") if isinstance(data.get("target"), dict) else {},
                "style": data.get("style") if isinstance(data.get("style"), dict) else {},
                "candidate": candidates[0],
                "candidates": candidates,
            })
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            print(f"❌ Prompt Safe Rewrite 失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_image_analysis(self):
        """Analyze image references into prompt candidates and structured modules."""
        try:
            data = self.read_json_body(max_bytes=64 * 1024 * 1024)
            images = data.get("images") if isinstance(data.get("images"), list) else []
            message = str(data.get("message") or data.get("direction") or "").strip()
            if not images:
                self.send_json({"ok": False, "error": "请先上传或选择要分析的图片"}, 400)
                return
            result = analyze_prompt_image(message, images, {
                "provider": data.get("provider"),
                "model": data.get("model"),
                "reasoning_effort": data.get("reasoning_effort") or data.get("reasoningEffort") or "medium",
                "style": data.get("style") if isinstance(data.get("style"), dict) else {},
                "target": data.get("target") if isinstance(data.get("target"), dict) else {},
                "keep_text": bool(data.get("keep_text") or data.get("keepText")),
            })
            self.send_json({
                **result,
                "target": data.get("target") if isinstance(data.get("target"), dict) else {},
                "style": data.get("style") if isinstance(data.get("style"), dict) else {},
            })
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            print(f"❌ Prompt 图片分析失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_versions_generate(self):
        """Generate formal prompt candidates for the text-node assistant."""
        try:
            data = self.read_json_body(max_bytes=512 * 1024)
            prompt = str(data.get("prompt") or data.get("text") or "").strip()
            message = str(data.get("message") or data.get("direction") or "").strip()
            style = data.get("style") if isinstance(data.get("style"), dict) else {}
            if not prompt and not message:
                self.send_json({"ok": False, "error": "请输入文本节点内容或生成方向"}, 400)
                return

            base = prompt or message
            instruction = "\n".join(part for part in [
                f"用户确认方向：{message}" if message else "",
                f"文本节点内容：{prompt}" if prompt else "",
                f"风格预设：{style.get('title') or style.get('name') or ''} {style.get('promptTemplate') or style.get('prompt_style') or ''}".strip() if style else "",
            ] if part).strip()
            polish_error = ""
            polished = {}
            try:
                polished = polish_prompt(instruction or base, {
                    "provider": data.get("provider"),
                    "skill": data.get("skill"),
                    "model": data.get("model"),
                    "reasoning_effort": data.get("reasoning_effort") or data.get("reasoningEffort"),
                })
            except Exception as e:
                polish_error = str(e)
                print(f"⚠️ Prompt 版本生成润色降级：{polish_error}")

            candidates = _prompt_version_candidates(base, message=message, style=style, polished=polished)
            self.send_json({
                "ok": True,
                "session_id": str(data.get("session_id") or f"prompt_versions_{int(time.time())}_{random.randint(1000, 9999)}"),
                "target": data.get("target") if isinstance(data.get("target"), dict) else {},
                "style": style,
                "candidates": candidates,
                "warning": polish_error,
                "model": polished.get("model"),
                "provider": polished.get("provider"),
            })
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            print(f"❌ Prompt 版本生成失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_prompt_chat(self):
        """Return prompt candidates for the desktop Prompt Chat Drawer."""
        try:
            data = self.read_json_body(max_bytes=512 * 1024)
            prompt = str(data.get("prompt") or data.get("text") or "").strip()
            message = str(data.get("message") or "").strip()
            style = data.get("style") if isinstance(data.get("style"), dict) else {}
            if not prompt and not message:
                self.send_json({"ok": False, "error": "请输入提示词或改写需求"}, 400)
                return

            base = prompt or message
            instruction = "\n".join(part for part in [
                f"用户需求：{message}" if message else "",
                f"原始提示词：{prompt}" if prompt else "",
                f"风格预设：{style.get('title') or style.get('name') or ''} {style.get('promptTemplate') or style.get('prompt_style') or ''}".strip() if style else "",
            ] if part).strip()
            polish_error = ""
            polished = {}
            try:
                polished = polish_prompt(instruction or base, {
                    "provider": data.get("provider"),
                    "skill": data.get("skill"),
                    "model": data.get("model"),
                    "reasoning_effort": data.get("reasoning_effort") or data.get("reasoningEffort"),
                })
            except Exception as e:
                polish_error = str(e)
                print(f"⚠️ Prompt Chat 润色降级：{polish_error}")

            candidates = _prompt_version_candidates(base, message=message, style=style, polished=polished)

            self.send_json({
                "ok": True,
                "session_id": str(data.get("session_id") or f"prompt_chat_{int(time.time())}_{random.randint(1000, 9999)}"),
                "message": message,
                "target": data.get("target") if isinstance(data.get("target"), dict) else {},
                "style": style,
                "candidates": candidates[:5],
                "warning": polish_error,
                "model": polished.get("model"),
                "provider": polished.get("provider"),
            })
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            print(f"❌ Prompt Chat 失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_asset_health_cleanup(self):
        """清理缺文件资产、候选集坏引用、空候选集和失效溯源。"""
        try:
            health = _collect_asset_health()
            removed_asset_refs = 0
            task_updates = 0
            hidden_updates = 0
            for item in health.get('missing_assets_all') or health.get('missing_assets') or []:
                asset = get_gallery_asset(item.get('asset_id') or item.get('id') or '')
                if not asset:
                    continue
                removed_history = []
                if _remove_asset_from_task(asset, removed_history=removed_history):
                    task_updates += 1
                try:
                    update_asset_meta(item.get('asset_id') or item.get('id') or '', hidden=True)
                    hidden_updates += 1
                except Exception:
                    pass
                removed_asset_refs += remove_asset_from_sets(item.get('asset_id') or item.get('id') or '')

            refreshed = _collect_asset_health()
            valid_ids = set(refreshed.get('valid_asset_ids') or [])
            set_cleanup = cleanup_asset_sets(valid_ids, delete_empty=True)
            lineage_cleanup = _cleanup_lineage_refs(valid_ids)
            no_image_removed = _cleanup_no_image_history()
            after = _collect_asset_health()
            public_before = {key: value for key, value in health.items() if key not in ('valid_asset_ids', 'all_asset_ids', 'missing_assets_all')}
            public_after = {key: value for key, value in after.items() if key not in ('valid_asset_ids', 'all_asset_ids', 'missing_assets_all')}
            self.send_json({
                "ok": True,
                "before": public_before,
                "after": public_after,
                "cleanup": {
                    "missing_assets_removed": len(health.get('missing_assets_all') or health.get('missing_assets') or []),
                    "task_updates": task_updates,
                    "hidden_updates": hidden_updates,
                    "set_updates_from_missing": removed_asset_refs,
                    "sets": set_cleanup,
                    "lineage": lineage_cleanup,
                    "no_image_history_removed": no_image_removed,
                },
                "message": "图库体检清理完成",
            })
        except Exception as e:
            print(f"❌ 图库体检清理失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_asset_meta(self):
        """更新图库资产人工元数据。"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body or b'{}')
            asset_id = data.get('asset_id') or data.get('id') or ''
            payload = {}
            for key in ('favorite', 'hidden', 'tags', 'rating', 'note'):
                if key in data:
                    payload[key] = data.get(key)
            meta = update_asset_meta(asset_id, **payload)
            self.send_json({"ok": True, "asset": meta})
        except Exception as e:
            self.send_json({"ok": False, "error": str(e)}, 400)

    def handle_asset_delete(self, asset_id):
        """从图库移除资产，并把本地原图/提示词/预览移入废纸篓。"""
        try:
            self.send_json(_delete_gallery_assets([asset_id]))
        except FileNotFoundError as e:
            self.send_json({"ok": False, "error": str(e)}, 404)
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            print(f"❌ 删除图库资产失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_asset_delete_batch(self):
        """批量删除图库资产，避免同任务多图逐张删除时 asset_id 重新计算。"""
        try:
            data = self.read_json_body(max_bytes=256 * 1024)
            raw_ids = data.get('asset_ids') or data.get('assetIds') or data.get('ids') or []
            if isinstance(raw_ids, str):
                raw_ids = [raw_ids]
            result = _delete_gallery_assets(raw_ids if isinstance(raw_ids, list) else [])
            self.send_json(result)
        except FileNotFoundError as e:
            self.send_json({"ok": False, "error": str(e)}, 404)
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            print(f"❌ 批量删除图库资产失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_asset_undo_delete(self):
        """撤销最近的图库物理删除。"""
        try:
            data = self.read_json_body(max_bytes=128 * 1024)
            raw_ids = data.get('batch_ids') or data.get('batchIds') or data.get('batch_id') or data.get('batchId') or []
            if isinstance(raw_ids, str):
                batch_ids = [raw_ids]
            elif isinstance(raw_ids, list):
                batch_ids = [str(value or '').strip() for value in raw_ids if str(value or '').strip()]
            else:
                batch_ids = []
            if not batch_ids:
                self.send_json({"ok": False, "error": "缺少删除批次 ID"}, 400)
                return

            restored_files = 0
            existing_files = 0
            missing_files = 0
            skipped_files = 0
            restored_tasks = 0
            restored_history = 0
            restored_assets = 0
            restored_sets = 0
            restored_batches = []
            errors = []
            for batch_id in reversed(batch_ids):
                batch = get_delete_batch(batch_id)
                if not batch:
                    errors.append(f"{batch_id}: 删除记录不存在")
                    continue
                if batch.get('restored'):
                    errors.append(f"{batch_id}: 已撤销")
                    continue
                for move in batch.get('moves') or []:
                    status = _restore_trash_move(move if isinstance(move, dict) else {})
                    if status == 'restored':
                        restored_files += 1
                    elif status == 'exists':
                        existing_files += 1
                    elif status == 'missing':
                        missing_files += 1
                    else:
                        skipped_files += 1
                task_snapshots = batch.get('task_snapshots') or []
                if not isinstance(task_snapshots, list):
                    task_snapshots = []
                task_snapshot = batch.get('task_snapshot')
                if isinstance(task_snapshot, dict):
                    task_snapshots.append(task_snapshot)
                restored_task_ids = set()
                for snapshot in task_snapshots:
                    if not isinstance(snapshot, dict) or not snapshot.get('task_id'):
                        continue
                    task_id = str(snapshot.get('task_id') or '')
                    if task_id in restored_task_ids:
                        continue
                    restored_task_ids.add(task_id)
                    restored_tasks += 1 if restore_task_snapshot(snapshot) else 0
                restored_history += _restore_old_history_lines(batch.get('old_history_lines') or [])
                restored_sets += restore_asset_set_snapshots(batch.get('set_snapshots') or [])
                for asset_id in batch.get('asset_ids') or []:
                    try:
                        update_asset_meta(asset_id, hidden=False)
                        restored_assets += 1
                    except Exception:
                        pass
                mark_delete_batch_restored(batch_id)
                restored_batches.append(batch_id)

            status = 207 if errors and restored_batches else (400 if errors and not restored_batches else 200)
            self.send_json({
                "ok": bool(restored_batches),
                "batch_ids": restored_batches,
                "errors": errors,
                "restored_files": restored_files,
                "existing_files": existing_files,
                "missing_files": missing_files,
                "skipped_files": skipped_files,
                "restored_tasks": restored_tasks,
                "restored_history": restored_history,
                "restored_assets": restored_assets,
                "restored_sets": restored_sets,
                "message": "已撤销删除" if restored_batches else "没有可撤销的删除",
            }, status)
        except Exception as e:
            print(f"❌ 撤销图库删除失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_task_cancel(self, task_id):
        """取消正在运行的任务。

        生成线程会通过任务状态感知取消；正在进行中的单次上游调用不会被强杀，
        但后续图片、托底和 Telegram 发送会停止。
        """
        task = get_task(task_id)
        if not task:
            self.send_json(_missing_task_payload(task_id), 404)
            return

        status = str(task.get('status') or '')
        if status in ('succeeded', 'success', 'succeeded_no_telegram', 'failed', 'telegram_failed', 'canceled'):
            self.send_json({
                **task,
                'ok': True,
                'message': '任务已结束，无需取消。'
            })
            return

        result_files = task.get('result_files') or []
        progress_text = f'任务已取消，已保留 {len(result_files)} 张图' if result_files else '任务已取消'
        now = int(time.time())
        update_task_fields(
            task_id,
            status='canceled',
            stage='canceled',
            progress_text=progress_text,
            error='',
            transport_error_type='UserCanceled',
            heartbeat_at=now,
            finished_at=now,
        )
        canceled_task = get_task(task_id) or task
        if canceled_task.get('result_files'):
            canceled_task['output_files'] = canceled_task['result_files']
            canceled_task['image_paths'] = [f"/gpt_outputs/{name}" for name in canceled_task['result_files']] if canceled_task.get('type') in ('gpt', 'gpt-edit') else [f"/image/{name}" for name in canceled_task['result_files']]
            canceled_task['image_count'] = len(canceled_task['result_files'])
        canceled_task['ok'] = True
        canceled_task['message'] = progress_text
        self.send_json(canceled_task)

    def handle_task_retry(self, task_id):
        """从失败历史记录创建一个新的重跑任务，不修改原任务。"""
        task = get_task(task_id)
        if not task:
            self.send_json(_missing_task_payload(task_id), 404)
            return
        try:
            retry_task = retry_failed_task(task)
            self.send_json(retry_task, 202)
        except GenerationQueueFullError as e:
            payload = _generation_busy_payload()
            payload.update({"message": str(e), "task_id": task_id})
            self.send_json(payload, 503)
        except TaskRetryError as e:
            self.send_json({"ok": False, "error": str(e), "task_id": task_id}, 400)
        except Exception as e:
            print(f"❌ 重跑任务失败：{task_id} - {e}")
            self.send_json({"ok": False, "error": str(e), "task_id": task_id}, 500)

    def handle_task_batch(self):
        """创建顺序执行的批量生成任务。"""
        try:
            data = self.read_json_body()
            provider = str(data.get('provider') or 'gpt').strip().lower()
            if provider not in ('gpt', 'google'):
                self.send_json({"ok": False, "error": "批量第一版只支持 GPT 和 Google 纯生成任务。"}, 400)
                return
            if data.get('images') or data.get('base64_images') or data.get('reference_images'):
                self.send_json({"ok": False, "error": "批量第一版暂不支持带参考图的编辑任务。"}, 400)
                return
            prompts = _batch_prompt_items(data)
            if len(prompts) < 2:
                self.send_json({"ok": False, "error": "批量任务至少需要 2 条提示词。"}, 400)
                return
            if len(prompts) > 50:
                self.send_json({"ok": False, "error": "批量任务一次最多 50 条提示词。"}, 400)
                return
            params = data.get('params') if isinstance(data.get('params'), dict) else {}
            lineage = data.get('lineage') if isinstance(data.get('lineage'), dict) else None
            batch_id, tasks = _create_batch_tasks(provider, prompts, params, lineage=lineage)
            if not self.start_generation_task(
                batch_id,
                process_batch_tasks,
                (batch_id, tasks),
                task_ids=[task['task_id'] for task in tasks],
            ):
                return
            self.send_json({
                "ok": True,
                "batch_id": batch_id,
                "status": "queued",
                "counts": {
                    "total": len(tasks),
                    "queued": len(tasks),
                    "processing": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "canceled": 0,
                },
                "tasks": tasks,
                "message": f"已提交 {len(tasks)} 个批量任务，将按线路容量调度执行。",
            }, 202)
        except TaskRetryError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            print(f"❌ 创建批量任务失败：{e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_batch_status(self, batch_id):
        """聚合同一个 batch_id 下的子任务状态。"""
        summary = get_batch_summary(batch_id)
        self.send_json(summary, 200 if summary.get('ok') else 404)

    def handle_batch_control(self, batch_id, action):
        """暂停、恢复或取消批量任务。"""
        if action not in ('pause', 'resume', 'cancel'):
            self.send_json({"ok": False, "error": "不支持的批量操作"}, 404)
            return
        if not batch_id:
            self.send_json({"ok": False, "error": "缺少 batch_id"}, 400)
            return
        try:
            control = 'running' if action == 'resume' else ('canceled' if action == 'cancel' else 'paused')
            changed = set_batch_control(batch_id, control)
            if not changed:
                self.send_json({"ok": False, "error": "批量任务不存在", "batch_id": batch_id}, 404)
                return
            canceled = cancel_batch_queued_tasks(batch_id) if action == 'cancel' else 0
            summary = get_batch_summary(batch_id)
            summary.update({
                "ok": True,
                "action": action,
                "changed": changed,
                "canceled": canceled,
                "message": {
                    "pause": "批量任务已暂停，将在当前子任务结束后停止启动新任务。",
                    "resume": "批量任务已恢复。",
                    "cancel": "批量任务已取消。",
                }[action],
            })
            self.send_json(summary)
        except Exception as e:
            print(f"❌ 批量控制失败：{batch_id} {action} - {e}")
            self.send_json({"ok": False, "error": str(e), "batch_id": batch_id}, 500)

    def handle_comfy_workflows(self):
        """返回可用的 ComfyUI 工作流列表"""
        try:
            workflows = sorted(p.name for p in COMFY_WORKFLOW_DIR.glob('*.json'))
            self.send_json({"workflows": workflows})
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def handle_comfy_run(self):
        """将前端请求转发到远端 ComfyUI /prompt"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body or b'{}')

            workflow_name = data.get('workflow', '')
            prompt = data.get('prompt', '')
            ratio = data.get('ratio', '1:1')
            image_data = data.get('image')

            workflow, normalized_name = _load_comfy_workflow(workflow_name)
            uploaded_image_name = _upload_comfy_image(image_data) if image_data else None
            prepared_prompt = _prepare_comfy_workflow(workflow, prompt, ratio, uploaded_image_name)

            result = _proxy_comfy_json(
                'POST',
                '/prompt',
                payload={'prompt': prepared_prompt, 'client_id': COMFY_CLIENT_ID},
            )
            prompt_id = result.get('prompt_id')
            if not prompt_id:
                raise RuntimeError(f'ComfyUI 未返回 prompt_id: {result}')

            create_task(
                prompt_id,
                prompt,
                {
                    'workflow': normalized_name,
                    'ratio': ratio,
                    'comfy_prompt_id': prompt_id,
                    'comfy_uploaded_image': uploaded_image_name,
                },
                status='queued',
                task_type='comfy',
            )

            if not self.start_generation_task(
                prompt_id,
                process_comfy_task,
                (prompt_id, prompt, normalized_name, ratio),
            ):
                return

            self.send_json({
                'status': 'queued',
                'prompt_id': prompt_id,
                'task_id': prompt_id,
                'workflow': normalized_name,
            })
        except Exception as e:
            print(f"❌ Comfy run failed: {e}")
            self.send_json({"error": str(e)}, 500)

    def handle_comfy_history(self):
        """代理查询远端 ComfyUI 历史任务"""
        try:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            prompt_id = params.get('prompt_id', [''])[0].strip()
            if not prompt_id:
                self.send_json({"error": "缺少 prompt_id"}, 400)
                return

            result, entry = _fetch_comfy_history_entry(prompt_id)
            if isinstance(entry, dict):
                _sync_comfy_task(prompt_id, entry)
            self.send_json(result)
        except Exception as e:
            print(f"❌ Comfy history failed: {e}")
            self.send_json({"error": str(e)}, 500)

    def handle_comfy_image(self):
        """代理远端 ComfyUI 图片下载"""
        try:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            filename = params.get('filename', [''])[0].strip()
            subfolder = params.get('subfolder', [''])[0]
            file_type = params.get('type', ['output'])[0]
            if not filename:
                self.send_json({"error": "缺少 filename"}, 400)
                return

            image_bytes, content_type = _fetch_comfy_binary(filename, subfolder, file_type)
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self._apply_cors_headers()
            self.end_headers()
            self.wfile.write(image_bytes)
        except Exception as e:
            print(f"❌ Comfy image failed: {e}")
            self.send_json({"error": str(e)}, 500)

    def handle_comfy_send_tg(self):
        """下载远端 ComfyUI 结果并无损发送到 Telegram"""
        temp_path = None
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body or b'{}')

            filename = str(data.get('filename', '')).strip()
            subfolder = data.get('subfolder', '')
            file_type = data.get('type', 'output')
            prompt = str(data.get('prompt', '')).strip()
            workflow = str(data.get('workflow', '')).strip()
            ratio = str(data.get('ratio', '')).strip()

            if not filename:
                self.send_json({"error": "缺少 filename"}, 400)
                return

            image_bytes, _ = _fetch_comfy_binary(filename, subfolder, file_type)
            suffix = Path(filename).suffix or '.png'
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(image_bytes)
                temp_path = tmp.name

            caption_parts = [part for part in (f'ComfyUI {workflow}'.strip(), ratio) if part]
            caption = ' | '.join(caption_parts)
            if prompt:
                caption = f"{caption}\n{prompt}" if caption else prompt
            caption = caption[:500] + '...' if len(caption) > 500 else caption

            sent = send_telegram(None, temp_path, caption)
            if not sent:
                raise RuntimeError('Telegram 发送失败')

            self.send_json({"ok": True})
        except Exception as e:
            print(f"❌ Comfy send_tg failed: {e}")
            self.send_json({"error": str(e)}, 500)
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass

    def handle_history_export_tg(self):
        """把历史记录中的本机原图通过 Telegram sendDocument 发送出去。"""
        temp_path = None
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body or b'{}')

            raw_output_file = str(data.get('output_file') or data.get('filename') or '').strip()
            image_data = str(data.get('image_data') or data.get('imageData') or '').strip()
            filename = safe_basename(raw_output_file)
            archive_rel_path = str(data.get('archiveRelPath') or data.get('archive_rel_path') or '').strip()
            task_id = str(data.get('task_id') or '').strip()
            item_type = str(data.get('type') or '').strip()
            prompt = str(data.get('prompt') or '').strip()

            if image_data:
                image_bytes, _mime_type, extension = _decode_data_uri_image(image_data)
                filename = filename or f"source_{int(time.time())}_{random.randint(1000, 9999)}{extension}"
                suffix = Path(filename).suffix or extension
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(image_bytes)
                    temp_path = tmp.name
                file_path = Path(temp_path)
            elif not raw_output_file:
                self.send_json({"error": "缺少 output_file"}, 400)
                return
            elif item_type != 'gpt-file' and not filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                self.send_json({"error": "不支持的文件类型"}, 400)
                return

            if not image_data:
                task = get_task(task_id) if task_id else None
                if task_id:
                    allowed_files = task.get('result_files') if task else []
                    primary_file = task.get('result_file') if task else ''
                    check_name = raw_output_file if item_type == 'gpt-file' else filename
                    if task and check_name not in allowed_files and check_name != primary_file:
                        self.send_json({"error": "文件不属于该任务"}, 403)
                        return

                if item_type == 'gpt-file':
                    file_path = resolve_editable_file(raw_output_file)
                elif archive_rel_path:
                    file_path = _resolve_archive_image_file(archive_rel_path)
                elif item_type in ('gpt', 'gpt-edit'):
                    file_path = Path(DIRECTORY) / 'gpt_outputs' / filename
                elif item_type == 'comfy':
                    params = task.get('params') if task else {}
                    comfy_image = params.get('comfy_image') if isinstance(params, dict) else None
                    if not isinstance(comfy_image, dict) or not comfy_image.get('filename'):
                        self.send_json({"error": "ComfyUI 原图信息不存在"}, 404)
                        return

                    comfy_filename = safe_basename(comfy_image.get('filename'))
                    if comfy_filename != filename:
                        self.send_json({"error": "文件不属于该任务"}, 403)
                        return

                    image_bytes, _ = _fetch_comfy_binary(
                        comfy_filename,
                        comfy_image.get('subfolder', ''),
                        comfy_image.get('type', 'output'),
                    )
                    suffix = Path(comfy_filename).suffix or '.png'
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(image_bytes)
                        temp_path = tmp.name
                    file_path = Path(temp_path)
                else:
                    file_path = _resolve_download_image(filename)

            if not file_path or not Path(file_path).exists():
                self.send_json({"error": "原图文件不存在"}, 404)
                return

            caption = '📎 File' if item_type == 'gpt-file' else '📸 Original'
            if item_type:
                caption += f' | {item_type}'
            if prompt:
                trimmed_prompt = prompt[:420] + ('...' if len(prompt) > 420 else '')
                caption += f'\n{trimmed_prompt}'

            sent = send_telegram(None, str(file_path), caption[:900])
            if not sent:
                raise RuntimeError('Telegram 发送失败')

            self.send_json({"ok": True, "message": "原图已发送到 Telegram"})
        except Exception as e:
            print(f"❌ history export_tg failed: {e}")
            self.send_json({"error": str(e)}, 500)
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass

    def handle_delete_history_item(self):
        """删除单条历史记录，兼容新任务和旧 history.jsonl 记录"""
        try:
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            task_id = query.get('task_id', [''])[0].strip()
            timestamp_raw = query.get('timestamp', [''])[0].strip()
            deleted = 0

            if task_id and not task_id.startswith('old_'):
                deleted += delete_task(task_id)
            elif timestamp_raw:
                try:
                    timestamp = int(timestamp_raw)
                except ValueError:
                    self.send_json({"error": "timestamp 非法"}, 400)
                    return

                history_path = os.path.join(DIRECTORY, 'history.jsonl')
                if os.path.exists(history_path):
                    with open(history_path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                    kept = []
                    removed = 0
                    for line in lines:
                        try:
                            item = json.loads(line)
                        except Exception:
                            kept.append(line)
                            continue
                        if int(item.get('timestamp', -1)) == timestamp:
                            removed += 1
                            continue
                        kept.append(line)
                    if removed:
                        with open(history_path, 'w', encoding='utf-8') as f:
                            f.writelines(kept)
                        deleted += removed
                if deleted == 0:
                    import sqlite3
                    conn = sqlite3.connect(str(get_database_path()))
                    cur = conn.cursor()
                    cur.execute('DELETE FROM tasks WHERE created_at=?', (timestamp,))
                    conn.commit()
                    deleted += conn.total_changes
                    conn.close()
            else:
                self.send_json({"error": "缺少 task_id 或 timestamp"}, 400)
                return

            self.send_json({"deleted": deleted})
        except Exception as e:
            print(f"❌ 删除单条历史失败：{e}")
            self.send_json({"error": str(e)}, 500)
    
    def handle_delete_failed(self):
        """删除所有失败任务"""
        try:
            import sqlite3
            conn = sqlite3.connect(str(get_database_path()))
            c = conn.cursor()
            
            # 统计失败任务数量
            c.execute('SELECT COUNT(*) FROM tasks WHERE status="failed"')
            count = c.fetchone()[0]
            
            # 删除失败任务
            c.execute('DELETE FROM tasks WHERE status="failed"')
            conn.commit()
            conn.close()
            
            print(f"✅ 删除 {count} 条失败任务")
            self.send_json({"deleted": count})
            
        except Exception as e:
            print(f"❌ 删除失败任务出错：{e}")
            self.send_json({"error": str(e)}, 500)
    
    def handle_history(self):
        """处理历史查询（支持分页，兼容旧前端格式）"""
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)

        limit = _history_page_int(query.get('limit', [50])[0], 50, minimum=1, maximum=500)
        offset = _history_page_int(query.get('offset', [0])[0], 0, minimum=0, maximum=100000)

        all_tasks = _collect_renderable_history_tasks()
        page_tasks = all_tasks[offset:offset + limit]
        formatted_tasks = [_format_history_task(task) for task in page_tasks]

        self.send_json({
            "history": formatted_tasks,
            "total": len(all_tasks),
            "has_more": offset + len(page_tasks) < len(all_tasks),
        })
    
    def handle_image(self, filename):
        """处理图片请求（archive directory, with legacy fallback）"""
        filepath = _resolve_download_file(filename)
        
        if filepath and os.path.exists(filepath):
            content_type = mimetypes.guess_type(str(filepath))[0] or 'application/octet-stream'
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self._apply_cors_headers()
            self.end_headers()
            with open(filepath, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404, "Image not found")

    def handle_archive_image(self, rel_path):
        """按 Obsidian 归档相对路径读取图片，避免同名文件冲突。"""
        filepath = _resolve_archive_image_file(rel_path)

        if filepath and filepath.exists():
            content_type = mimetypes.guess_type(str(filepath))[0] or 'application/octet-stream'
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self._apply_cors_headers()
            self.end_headers()
            with open(filepath, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404, "Image not found")

    def handle_editable_file(self, rel_path):
        """读取 PPT/PSD 文件产物目录下的文件。"""
        filepath = resolve_editable_file(rel_path)

        if filepath and filepath.exists():
            content_type = mimetypes.guess_type(str(filepath))[0] or 'application/octet-stream'
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self._apply_cors_headers()
            if filepath.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp', '.pdf'):
                self.send_header('Content-Disposition', f'attachment; filename="{filepath.name}"')
            self.end_headers()
            with open(filepath, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404, "File not found")

    def handle_editable_files(self, parsed):
        """列出 PPT/PSD 文件产物，用于图库文件管理页。"""
        try:
            params = urllib.parse.parse_qs(parsed.query or '')
            limit = int((params.get('limit') or ['200'])[0] or 200)
            query = (params.get('query') or [''])[0]
            kind = (params.get('kind') or [''])[0]
            include_local = _coerce_bool((params.get('include_local') or ['1'])[0], True)
            self.send_json(list_editable_files(limit=limit, query=query, kind=kind, include_local=include_local))
        except Exception as e:
            print(f"❌ editable files list failed: {e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_editable_file_send(self):
        """发送一个已生成的 PPT/PSD 主文件到 Telegram。"""
        try:
            data = self.read_json_body()
            rel_path = str(data.get('relative_path') or data.get('result_file') or data.get('file') or '').strip()
            filepath = resolve_editable_file(rel_path)
            if not filepath:
                self.send_json({"ok": False, "error": "文件不存在"}, 404)
                return
            caption = str(data.get('caption') or '📎 File').strip() or '📎 File'
            sent = send_telegram(None, str(filepath), caption[:900])
            if not sent:
                raise RuntimeError('Telegram 发送失败')
            self.send_json({"ok": True, "message": "文件已发送到 Telegram"})
        except Exception as e:
            print(f"❌ editable file send failed: {e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_editable_file_delete(self):
        """删除一个 PPT/PSD 文件产物目录。前端会先二次确认。"""
        try:
            data = self.read_json_body()
            rel_path = str(data.get('directory_relative') or data.get('relative_path') or data.get('manifest') or '').strip()
            if not rel_path:
                self.send_json({"ok": False, "error": "缺少文件目录"}, 400)
                return
            self.send_json(delete_editable_item(rel_path))
        except FileNotFoundError as e:
            self.send_json({"ok": False, "error": str(e)}, 404)
        except Exception as e:
            print(f"❌ editable file delete failed: {e}")
            self.send_json({"ok": False, "error": str(e)}, 500)

    def handle_source_image(self, rel_path):
        """读取 Source_Image 下的远程源本地图片。"""
        filepath = resolve_source_image(rel_path)

        if filepath and filepath.exists():
            content_type = mimetypes.guess_type(str(filepath))[0] or 'application/octet-stream'
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self._apply_cors_headers()
            self.end_headers()
            with open(filepath, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404, "Source image not found")

    def handle_thumb(self, parsed):
        """Generate and serve an authenticated WebP thumbnail for local media."""
        try:
            params = urllib.parse.parse_qs(parsed.query or "")
            size = int((params.get("w") or params.get("size") or ["420"])[0] or 420)
        except Exception:
            size = 420
        media_path = parse_thumb_request(parsed.path)
        filepath = resolve_media_path(media_path, {
            "archive": _resolve_archive_image_file,
            "source": resolve_source_image,
            "image": _resolve_download_file,
        })
        if not filepath:
            self.send_error(404, "Thumbnail source not found")
            return
        try:
            thumb_path = ensure_webp_thumbnail(filepath, size=size)
        except Exception as exc:
            print(f"⚠️ WebP 缩略图生成失败：{exc}")
            self.send_error(500, "Thumbnail generation failed")
            return

        self.send_response(200)
        self.send_header('Content-Type', 'image/webp')
        self.send_header('Content-Length', str(thumb_path.stat().st_size))
        self.send_header('Cache-Control', 'public, max-age=31536000, immutable')
        self._apply_cors_headers()
        self.end_headers()
        with open(thumb_path, 'rb') as f:
            shutil.copyfileobj(f, self.wfile)
    
    def handle_google_output(self, filename):
        """处理 google_outputs 目录的图片请求"""
        filepath = os.path.join(DIRECTORY, 'google_outputs', filename)
        
        if os.path.exists(filepath):
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self._apply_cors_headers()
            self.end_headers()
            with open(filepath, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404, "Image not found")
    
    def handle_gpt_output(self, filename):
        """处理 gpt_outputs 目录的图片请求"""
        safe_name = safe_basename(filename)
        preview_path = ensure_gpt_preview_image(safe_name)
        filepath = str(preview_path) if preview_path else os.path.join(DIRECTORY, 'gpt_outputs', safe_name)
        
        if os.path.exists(filepath):
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self._apply_cors_headers()
            self.send_header('Cache-Control', 'public, max-age=31536000, immutable')
            self.end_headers()
            with open(filepath, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404, "Image not found")
    
    def log_message(self, format, *args):
        """自定义日志格式"""
        request_line = str(args[0]) if args else ''
        request_line = re.sub(r'([?&](?:miniappAuth|authToken|auth_token)=)[^&\s]+', r'\1***', request_line)
        print(f"[{time.strftime('%H:%M:%S')}] {request_line}")

def send_status_notification(task_id, message, icon='🔄'):
    """发送状态通知到 Telegram"""
    session = None
    try:
        bot_token, chat_id, proxy_url = _load_telegram_notify_config()
        if not bot_token or not chat_id:
            return False

        url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
        text = f'{icon} {message}'.strip()[:4000]
        session = requests.Session()
        session.trust_env = False
        session.proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else {}
        response = session.post(
            url,
            data={'chat_id': chat_id, 'text': text},
            timeout=20,
        )
        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                return True
            print(f"⚠️ Telegram 状态通知返回错误：{result}")
        else:
            print(f"⚠️ Telegram 状态通知 HTTP {response.status_code}: {response.text[:200]}")
    except Exception as e:
        print(f"⚠️ 发送状态通知失败：{e}")
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
    return False

def _is_retryable_generation_error(error_msg):
    """判断是否属于可托底错误（网络/超时/服务暂时不可用）"""
    text = (error_msg or "").lower()

    non_retryable_markers = [
        '内容安全', '安全过滤', '服务端拒绝', 'invalid prompt',
        'invalid api key', 'api key is required', 'missing prompt',
        'http 错误 401', 'http 错误 403', 'unauthorized', 'forbidden',
    ]
    if any(m in text for m in non_retryable_markers):
        return False

    retryable_markers = [
        'timeout', '超时', 'connection', '连接', 'network', '网络',
        'remote end closed', 'connection reset', 'socket',
        'temporarily unavailable', 'service unavailable',
        'http 错误 500', 'http 错误 502', 'http 错误 503', 'http 错误 504',
    ]
    return any(m in text for m in retryable_markers)


def _map_quality_to_gpt_resolution(quality):
    q = (quality or '2k').strip().lower()
    if q in ('hd', '4k'):
        return '4k'
    if q in ('1k', 'low', 'normal'):
        return '1k'
    return '2k'


def _should_fallback_to_gpt(params, primary_error_msg):
    """skill 调用时是否触发 GPT 托底"""
    caller = str((params or {}).get('caller', 'webapp')).lower()
    if caller != 'skill':
        return False

    fallback_cfg = (params or {}).get('fallback') if isinstance((params or {}).get('fallback'), dict) else {}
    enabled = fallback_cfg.get('enabled', True)
    target = str(fallback_cfg.get('target', 'gpt')).lower()
    retryable_only = fallback_cfg.get('retryable_only', True)
    force = fallback_cfg.get('force', False)

    if not enabled or target != 'gpt':
        return False

    if force or (not retryable_only):
        return True

    return _is_retryable_generation_error(primary_error_msg)


def process_task(task_id, prompt, params):
    """后台线程：处理任务（skill 调用支持 GPT 托底）"""
    def progress_cb(stage=None, progress_text=None, heartbeat=False, **extra):
        payload = {}
        if stage is not None:
            payload['stage'] = stage
        if progress_text is not None:
            payload['progress_text'] = progress_text
        if heartbeat:
            payload['heartbeat_at'] = int(time.time())
        payload.update({k: v for k, v in extra.items() if v is not None})
        if payload:
            update_task_fields(task_id, **payload)

    run_id = ''
    task_kind = 'google-gen'
    task_provider = 'google'
    task_route = 'google_gen'
    try:
        print(f"🎨 开始处理任务：{task_id}")

        model = params.get('model', DEFAULT_GOOGLE_IMAGE_MODEL)
        task_kind = 'gpt' if 'gpt' in str(model).lower() else 'google-gen'
        task_provider = 'chatgpt_pool' if task_kind == 'gpt' else 'google'
        task_route = 'gpt_pool' if task_kind == 'gpt' else 'google_gen'
        run_id = _start_generation_audit(
            task_id,
            task_kind,
            prompt,
            params,
            provider=task_provider,
            route=task_route,
            stage='preparing',
        )

        send_status_notification(task_id, '已提交图片生成任务，请等待...', '✅')
        update_task_status(task_id, 'preparing', '正在准备生成...', stage='preparing')
        update_task_status(task_id, 'processing', '生成中...', stage='queued')

        aspect_ratio = params.get('ratio', '1:1')
        quality = params.get('quality', 'hd')
        max_tokens = _coerce_google_max_tokens(params.get('max_tokens'))
        temperature = params.get('temperature')
        style = params.get('style', 'raw')
        caller = str(params.get('caller', 'webapp')).lower()
        archive_enabled, telegram_enabled = _coerce_google_output_controls(params)
        params['archive_enabled'] = archive_enabled
        params['telegram_enabled'] = telegram_enabled
        _merge_task_params(task_id, {
            'archive_enabled': archive_enabled,
            'telegram_enabled': telegram_enabled,
        })

        # 拼接风格提示词
        final_prompt = prompt
        if style == 'king_hu':
            final_prompt += ", Cinematic Wuxia Aesthetic (King Hu Style), Moon-white & Pale Cyan palette, high-class grey tones. Tyndall morning light piercing through heavy mist, golden backlight halo. Ancient temple gate, mossy stone steps, bamboo forest. Cold porcelain glass skin, jet black ink-like hair with wet dew texture. Ink wash painting negative space, film grain, wide shot, 1970s martial arts masterpiece."
        elif style == 'shadow':
            final_prompt += ", Shadow-play Aesthetic (Ying Style), Teal and Ink scheme, low saturation, high contrast between deep blacks and wet highlights. Cold-toned porcelain skin, high slanted Duo-ma bun, ebony hairpin. Rembrandt lighting, cold side light & golden rim light. Minimalist Zen space, giant translucent rice paper screens, wet ink brushstrokes, rainy atmosphere. Cinnabar dot, Song-style layered silk gauze texture."
        elif style == 'dunhuang':
            final_prompt += ", Dunhuang Mural (Rock Color Aesthetic), Opulent Gold & Lapis Lazuli palette, high contrast warm shadows. Radiant Tang-style porcelain skin, double-loop Wang-xian bun, gold filigree hairpins. Rock color texture, weathered mural surface. Divine god rays in cavern, amber candlelight. Ancient grotto atmosphere, flying ribbons, golden clover huadian, epic religious solemnity."
        elif style == 'candlelight':
            final_prompt += ", Cinematic candlelight portrait: Sony A7R IV with 50mm f/1.2 lens, multiple white candles as natural light source, dramatic chiaroscuro lighting with strong side light contouring, deep layered shadows. Ultra-realistic digital art, photorealistic with Unreal Engine 5 CG cinematic rendering. Extremely detailed skin texture with visible pores, subtle sheen of sweat/oil on skin surface, realistic subsurface scattering (SSS) translucency. 8K ultra-high resolution, ray-traced lighting quality, hyper-detailed micro textures including knitted fabric fibers, velvet plush texture, light scattering on different materials. Classical, mysterious, elegant atmosphere with suppressed luxury, warm brown candlelight interwoven with deep purple and ash grey shadows."
        elif style == 'real':
            final_prompt += ", photorealistic, 8k, highly detailed, sharp focus, cinematic lighting, photography, masterpiece"
        elif style == '3d_info':
            final_prompt += ", 3D infographic poster, C4D claymorphism style, vertical layout, centered composition, matte plastic and soft clay texture, soft diffuse lighting, no harsh highlights, 3D infographic aesthetic, pop art influence, soft glowing 3d icons, similar to Behance 3D illustrations and Apple skeuomorphic icons"
        elif style == 'sketchnote':
            final_prompt = f"请根据以下输入内容，生成一张手绘涂鸦风格的读书笔记信息图，并严格遵循以下风格：1. 整体风格与媒介：采用充满活力的手绘涂鸦笔记 (Sketchnote) 风格，专业知识笔记的学霸风格，不要太卡通。黑色使用深棕、橙黄或海军蓝，轻微水彩进行填色，并搭配柔和的黑色或深棕色细线等勾勒轮廓。竖版 (3:4) 构图。2. 配色方案（关键）：整张图都应该是彩色的，采用明亮、清新、和谐的色彩组合（海军蓝#1E3A8A、浅蓝#60A5FA、金色#F59E0B、奶油色背景#FEFCE8）。背景应有淡淡纸张纹理的米色，或者直接留白，但画面主体必须是五彩斑斓的。颜色填充应模仿彩铅或水彩的质感，带有自然的笔触感，而不是均匀的数字平涂。3. 线条特征：所有轮廓线都必须是不完美、略带抖动的手绘线条，给人一种柔软、亲切的感觉。4. 字体风格：所有文字都必须是彩色的手写体，绝对不要使用任何电脑字体。标题和关键词使用加粗的、或带有简单边框的手写艺术字来突出。正文和注释使用清晰、自然的个人笔记手写体。5. 插图与图标：所有图形元素必须是充满色彩的、简单的涂鸦/简笔画（colorful doodle/stick figure）风格。使用手绘的彩色箭头、框线、项目符号和分割线来组织信息。6. 内容处理：信息精炼，通过关键词加粗、手绘框等方式突出重点。如有故事人物，用此风格的可爱彩色涂鸦形象替代。话语与输入内容保持一致。7. 绘制使用中文绘制成为完整的信息卡输出，尽可能使用 PINCH 的展示方式，将所有内容排版在一页，需要清晰可读，所有中文必须孤立文字图层处理，输出高分辨率 4k。输入内容：{prompt}"
            aspect_ratio = "3:4"

        print(f"📡 调用 API...")
        print(f"   - caller: {caller}")
        print(f"   - ratio: {aspect_ratio}")
        print(f"   - quality: {quality}")
        print(f"   - model: {model}")
        print(f"   - max_tokens: {max_tokens}")
        if temperature is not None:
            print(f"   - temperature: {temperature}")
        print(f"   - style: {style}")

        if 'gpt' in str(model).lower():
            update_task_status(task_id, 'processing', '正在调用 GPT 生成...', stage='calling_gpt')
            send_status_notification(task_id, '生成中... 正在调用 GPT...', '🤖')

            gpt_resolution = params.get('resolution') or _map_quality_to_gpt_resolution(quality)
            _record_generation_event(task_id, 'provider_call_started', '开始调用 GPT 账号池生成图片', stage='calling_gpt', payload={'provider': 'chatgpt_pool', 'route': 'gpt_pool'})
            result = generate_image_gpt_pool(
                prompt,
                aspect_ratio,
                gpt_resolution,
                quality,
                image_count=1,
                prompt_mode='smart',
            )
            if not result.get('success'):
                raise RuntimeError(result.get('error', 'GPT 生成失败'))

            telegram_success = False
            if telegram_enabled:
                update_task_status(task_id, 'processing', '正在发送到 Telegram...', stage='sending_telegram')
                send_status_notification(task_id, '生成中... 正在发送图片...', '📤')
                _record_generation_event(task_id, 'telegram_send_started', '开始发送图片到 Telegram', stage='sending_telegram')
                telegram_success = send_telegram_result(
                    result['image_path'],
                    prompt,
                    aspect_ratio,
                    gpt_resolution,
                    image_paths=result.get('image_paths'),
                )
            else:
                update_task_status(task_id, 'processing', 'Telegram 已关闭，正在整理结果...', stage='saving')
                _record_generation_event(task_id, 'telegram_send_skipped', '已按节点开关跳过 Telegram', stage='saving')

            result_files = _result_image_filenames(result)
            image_count = len(result_files) or len(result.get('image_paths') or [result.get('image_path')])
            filename = result_files[0] if result_files else os.path.basename(result['image_path'])
            if telegram_success:
                ok_text = f'GPT 图片生成成功（共 {image_count} 张）' if image_count > 1 else 'GPT 图片生成成功'
                _finalize_generation_task(
                    task_id,
                    'succeeded',
                    run_id=run_id,
                    provider='chatgpt_pool',
                    route='gpt_pool',
                    task_type=task_kind,
                    result_file=filename,
                    stage='done',
                    progress_text=ok_text,
                    result_files=result_files,
                    image_count=image_count,
                )
                _record_generation_event(task_id, 'run_succeeded', ok_text, stage='done', payload={'provider': 'chatgpt_pool', 'route': 'gpt_pool', 'image_count': image_count})
                send_status_notification(task_id, '✅ GPT 图片生成成功！', '🎉')
            else:
                progress_text = 'GPT 图片已生成，已按节点开关跳过 Telegram' if not telegram_enabled else 'GPT 图片已生成，但 Telegram 发送失败'
                _finalize_generation_task(
                    task_id,
                    'succeeded_no_telegram',
                    run_id=run_id,
                    provider='chatgpt_pool',
                    route='gpt_pool',
                    task_type=task_kind,
                    result_file=filename,
                    stage='done',
                    progress_text=progress_text,
                    result_files=result_files,
                    image_count=image_count,
                )
                _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload={'provider': 'chatgpt_pool', 'route': 'gpt_pool', 'image_count': image_count, 'telegram_enabled': telegram_enabled})
            return

        update_task_status(task_id, 'processing', '正在调用 AI 模型...', stage='calling_api')
        send_status_notification(task_id, '生成中... 正在调用 AI 模型...', '🤖')
        _record_generation_event(task_id, 'provider_call_started', '开始调用 Google 图像生成', stage='calling_api', payload={'provider': 'google', 'route': 'google_gen'})

        image_data = None
        response_meta = {}
        primary_error = None
        try:
            image_data, response_meta = generate_image(
                final_prompt,
                aspect_ratio,
                quality,
                model,
                max_tokens=max_tokens,
                temperature=temperature,
                progress_cb=progress_cb,
            )
        except Exception as e:
            primary_error = str(e)
            print(f"⚠️ 主路由失败：{primary_error}")

            if _should_fallback_to_gpt(params, primary_error):
                update_task_status(task_id, 'fallback_running', '主路由失败，切换 GPT 托底...', stage='fallback_running')
                send_status_notification(task_id, '主路由失败，切换 GPT 托底中...', '🛟')
                _record_generation_event(task_id, 'fallback_started', 'Google 主路由失败，切换 GPT 托底', stage='fallback_running', severity='warning', payload={'primary_error': primary_error})

                gpt_resolution = params.get('fallback_resolution') or _map_quality_to_gpt_resolution(quality)
                fallback_result = generate_image_gpt_pool(
                    prompt,
                    aspect_ratio,
                    gpt_resolution,
                    quality,
                    image_count=1,
                    prompt_mode='smart',
                )
                if not fallback_result.get('success'):
                    fallback_error = fallback_result.get('error', 'unknown')
                    raise RuntimeError(
                        f"主路由失败：{primary_error} | GPT 托底失败：{fallback_error}"
                    )

                telegram_success = False
                if telegram_enabled:
                    update_task_status(task_id, 'processing', '托底成功，正在发送到 Telegram...', stage='sending_telegram')
                    send_status_notification(task_id, '托底成功，正在发送图片...', '📤')
                    _record_generation_event(task_id, 'telegram_send_started', '托底成功后开始发送到 Telegram', stage='sending_telegram')
                    telegram_success = send_telegram_result(
                        fallback_result['image_path'],
                        prompt,
                        aspect_ratio,
                        gpt_resolution,
                        image_paths=fallback_result.get('image_paths'),
                    )
                else:
                    update_task_status(task_id, 'processing', 'Telegram 已关闭，正在整理结果...', stage='saving')
                    _record_generation_event(task_id, 'telegram_send_skipped', '托底成功后按节点开关跳过 Telegram', stage='saving')

                result_files = _result_image_filenames(fallback_result)
                image_count = len(result_files) or len(fallback_result.get('image_paths') or [fallback_result.get('image_path')])
                filename = result_files[0] if result_files else os.path.basename(fallback_result['image_path'])
                if telegram_success or not telegram_enabled:
                    ok_text = f'托底生成成功（共 {image_count} 张）' if image_count > 1 else '托底生成成功'
                    progress_text = ok_text if telegram_enabled else '托底生成成功，已按节点开关跳过 Telegram'
                    _finalize_generation_task(
                        task_id,
                        'succeeded' if telegram_enabled else 'succeeded_no_telegram',
                        run_id=run_id,
                        provider='chatgpt_pool',
                        route='gpt_pool_fallback',
                        task_type=task_kind,
                        result_file=filename,
                        stage='done',
                        progress_text=progress_text,
                        result_files=result_files,
                        image_count=image_count,
                        extra={'fallback_source': 'chatgpt_pool', 'primary_error': primary_error},
                    )
                    _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload={'provider': 'chatgpt_pool', 'route': 'gpt_pool_fallback', 'fallback_source': 'chatgpt_pool', 'image_count': image_count})
                    send_status_notification(task_id, '✅ 托底生成成功！', '🎉')
                    print(f"✅ 托底成功：{task_id} -> {filename}")
                else:
                    progress_text = '托底生成成功，但 Telegram 发送失败'
                    _finalize_generation_task(
                        task_id,
                        'succeeded_no_telegram',
                        run_id=run_id,
                        provider='chatgpt_pool',
                        route='gpt_pool_fallback',
                        task_type=task_kind,
                        result_file=filename,
                        stage='done',
                        progress_text=progress_text,
                        result_files=result_files,
                        image_count=image_count,
                        extra={'fallback_source': 'chatgpt_pool', 'primary_error': primary_error},
                    )
                    _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload={'provider': 'chatgpt_pool', 'route': 'gpt_pool_fallback', 'fallback_source': 'chatgpt_pool', 'image_count': image_count, 'telegram_enabled': telegram_enabled})
                    print(f"⚠️ 托底成功但 Telegram 发送失败：{task_id}")
                return

            raise

        update_task_status(
            task_id,
            'processing',
            '正在保存图片...',
            stage='saving',
            bytes_received=response_meta.get('bytes_received'),
            first_byte_at=response_meta.get('first_byte_at'),
            ttfb_ms=response_meta.get('ttfb_ms'),
        )
        send_status_notification(task_id, '生成中... 正在保存图片...', '💾')

        from datetime import datetime
        now = datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        model_name = str(model).replace("gemini-", "").replace("-image-preview", "").replace("-image", "").replace(".", "")
        filename_base = f"{model_name}_{timestamp}"

        download_dir = daily_output_dir(now)
        download_dir.mkdir(parents=True, exist_ok=True)

        filename_with_ext = f"{filename_base}.png"
        filepath = str(download_dir / filename_with_ext)
        filename = save_image(image_data, filepath)

        txt_path = download_dir / f"{filename_base}.txt"
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(prompt)
        try:
            write_obsidian_prompt_sidecar(Path(filepath), prompt, txt_path=txt_path)
        except Exception as exc:
            print(f"⚠️ 写入 Obsidian 提示词 md 失败: {exc}")
        print(f"💾 已保存图片：{filepath}")
        print(f"💾 已保存提示词：{txt_path}")
        save_thumbnail(filepath, filename)

        telegram_success = False
        if telegram_enabled:
            update_task_status(task_id, 'processing', '正在发送到 Telegram...', stage='sending_telegram')
            send_status_notification(task_id, '生成中... 正在发送图片...', '📤')
            _record_generation_event(task_id, 'telegram_send_started', '开始发送图片到 Telegram', stage='sending_telegram')
            try:
                print(f"📤 准备发送 Telegram: {filepath}")
                caption = prompt[:500] + "..." if len(prompt) > 500 else prompt
                telegram_success = send_telegram(None, filepath, caption)
                if telegram_success:
                    print(f"✅ Telegram 发送成功")
                else:
                    error_msg = "Telegram 发送失败：send_telegram returned False"
                    print(f"❌ {error_msg}")
                    error_info = _translate_generation_failure(task_id, error_msg, provider='telegram', route='telegram', task_type=task_kind, stage='telegram_failed')
                    _finalize_generation_task(task_id, 'telegram_failed', run_id=run_id, stage='telegram_failed', progress_text=error_info.get('display_error') or error_msg, error_info=error_info, error_type='TelegramSendFailed', provider=task_provider, route=task_route, task_type=task_kind)
                    try:
                        send_status_notification(task_id, '❌ 发送失败：请检查 bot token/网络/文件路径', '⚠️')
                    except:
                        pass
            except Exception as e:
                error_msg = f"Telegram 发送失败：{str(e)}"
                print(f"❌ {error_msg}")
                error_info = _translate_generation_failure(task_id, error_msg, provider='telegram', route='telegram', task_type=task_kind, stage='telegram_failed', exception_name=type(e).__name__)
                _finalize_generation_task(task_id, 'telegram_failed', run_id=run_id, stage='telegram_failed', progress_text=error_info.get('display_error') or error_msg, error_info=error_info, error_type=type(e).__name__, provider=task_provider, route=task_route, task_type=task_kind)
                try:
                    send_status_notification(task_id, f'❌ 发送失败：{str(e)[:100]}', '⚠️')
                except:
                    pass
        else:
            update_task_status(task_id, 'processing', 'Telegram 已关闭，正在整理结果...', stage='saving')
            _record_generation_event(task_id, 'telegram_send_skipped', '已按节点开关跳过 Telegram', stage='saving')

        if telegram_success:
            _finalize_generation_task(task_id, 'succeeded', run_id=run_id, stage='done', progress_text='图片生成成功', result_file=filename, result_files=[filename], image_count=1, provider=task_provider, route=task_route, task_type=task_kind)
            _record_generation_event(task_id, 'run_succeeded', '图片生成成功', stage='done', payload={'provider': task_provider, 'route': task_route, 'image_count': 1})
            send_status_notification(task_id, '✅ 图片生成成功！', '🎉')
            print(f"✅ 任务成功：{task_id}")
        else:
            progress_text = '图片已保存，已按节点开关跳过 Telegram' if not telegram_enabled else '图片已保存，但 Telegram 发送失败'
            _finalize_generation_task(
                task_id,
                'succeeded_no_telegram',
                run_id=run_id,
                provider=task_provider,
                route=task_route,
                task_type=task_kind,
                result_file=filename,
                stage='done',
                progress_text=progress_text,
                result_files=[filename],
                image_count=1,
            )
            _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload={'provider': task_provider, 'route': task_route, 'image_count': 1, 'telegram_enabled': telegram_enabled})
            print(f"⚠️ 任务完成但未发送 Telegram: {task_id}")

    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        error_info = _translate_generation_failure(
            task_id,
            error_msg,
            provider=task_provider,
            route=task_route,
            task_type=task_kind,
            stage='failed',
            exception_name=error_type,
        )

        print(f"")
        print(f"❌ ════════════════════════════════════════")
        print(f"❌  任务失败：{task_id}")
        print(f"❌  错误类型：{error_type}")
        print(f"❌  错误信息：{error_msg}")
        print(f"❌ ════════════════════════════════════════")
        print(f"")

        _finalize_generation_task(task_id, 'failed', run_id=run_id, stage='failed', progress_text=error_info.get('display_error') or error_msg, error_info=error_info, error_type=error_type, provider=task_provider, route=task_route, task_type=task_kind)
        send_status_notification(task_id, f"❌ 生成失败：{error_info.get('display_error') or error_msg}", '⚠️')
def process_edit_task(task_id, prompt, images, params):
    """后台线程：处理编辑任务（skill 调用支持 GPT 托底）"""
    run_id = ''
    task_kind = 'google-edit'
    task_provider = 'google'
    task_route = 'google_edit'
    try:
        print(f"✏️ 开始处理编辑任务：{task_id}")
        print(f"📋 完整 params: {json.dumps(params, ensure_ascii=False)}")

        run_id = _start_generation_audit(
            task_id,
            task_kind,
            prompt,
            params,
            provider=task_provider,
            route=task_route,
            stage='preparing',
        )

        # 发送提交通知
        send_status_notification(task_id, '已提交图片编辑任务，请等待...', '✅')

        # 状态 1: 准备中
        update_task_status(task_id, 'preparing', '正在准备编辑...')
        update_task_status(task_id, 'processing', '编辑中...')

        # 调用 API 编辑图片 - 从 params 提取参数
        aspect_ratio = params.get('ratio', '1:1')
        quality = params.get('quality', 'hd')
        model = params.get('model', DEFAULT_GOOGLE_IMAGE_MODEL)
        max_tokens = _coerce_google_max_tokens(params.get('max_tokens'))
        temperature = params.get('temperature')
        feature = params.get('feature', 'edit')
        caller = str(params.get('caller', 'webapp')).lower()
        archive_enabled, telegram_enabled = _coerce_google_output_controls(params)
        params['archive_enabled'] = archive_enabled
        params['telegram_enabled'] = telegram_enabled
        _merge_task_params(task_id, {
            'archive_enabled': archive_enabled,
            'telegram_enabled': telegram_enabled,
        })

        # 前端可能传递的是 aspectRatio 而不是 ratio
        if 'aspectRatio' in params:
            aspect_ratio = params.get('aspectRatio', '1:1')

        print(f"📡 调用 API...")
        print(f"   - caller: {caller}")
        print(f"   - aspect_ratio: {aspect_ratio}")
        print(f"   - quality: {quality}")
        print(f"   - model: {model}")
        print(f"   - max_tokens: {max_tokens}")
        if temperature is not None:
            print(f"   - temperature: {temperature}")
        print(f"   - feature: {feature}")
        print(f"   - images: {len(images)} 张")

        # 状态 2: 调用 API
        update_task_status(task_id, 'processing', '正在调用 AI 模型...')
        send_status_notification(task_id, '编辑中... 正在调用 AI 模型...', '🤖')
        _record_generation_event(task_id, 'provider_call_started', '开始调用 Google 图像编辑', stage='calling_api', payload={'provider': task_provider, 'route': task_route})

        # 主路由：编辑接口
        from .api_client import edit_image

        def progress_cb(stage=None, progress_text=None, heartbeat=False, **extra):
            payload = {}
            if stage is not None:
                payload['stage'] = stage
            if progress_text is not None:
                payload['progress_text'] = progress_text
            if heartbeat:
                payload['heartbeat_at'] = int(time.time())
            payload.update({k: v for k, v in extra.items() if v is not None})
            if payload:
                update_task_fields(task_id, **payload)

        image_data = None
        response_meta = {}
        primary_error = None
        try:
            image_data, response_meta = edit_image(
                prompt,
                images,
                aspect_ratio,
                quality,
                model,
                max_tokens=max_tokens,
                temperature=temperature,
                progress_cb=progress_cb,
            )
        except Exception as e:
            primary_error = str(e)
            print(f"⚠️ 编辑主路由失败：{primary_error}")

            if _should_fallback_to_gpt(params, primary_error):
                update_task_status(task_id, 'fallback_running', '编辑主路由失败，切换 GPT 托底...')
                send_status_notification(task_id, '编辑主路由失败，切换 GPT 托底中...', '🛟')
                _record_generation_event(task_id, 'fallback_started', 'Google 编辑主路由失败，切换 GPT 托底', stage='fallback_running', severity='warning', payload={'primary_error': primary_error})

                gpt_resolution = params.get('fallback_resolution') or _map_quality_to_gpt_resolution(quality)
                fallback_prompt = (
                    f"请基于用户编辑需求进行生成（原请求为图像编辑，当前走托底生成）：\n{prompt}"
                )
                fallback_result = generate_image_gpt_pool(
                    fallback_prompt,
                    aspect_ratio,
                    gpt_resolution,
                    quality,
                    image_count=1,
                    prompt_mode='smart',
                )
                if not fallback_result.get('success'):
                    fallback_error = fallback_result.get('error', 'unknown')
                    raise RuntimeError(
                        f"编辑主路由失败：{primary_error} | GPT 托底失败：{fallback_error}"
                    )

                telegram_success = False
                if telegram_enabled:
                    update_task_status(task_id, 'processing', '托底成功，正在发送到 Telegram...')
                    send_status_notification(task_id, '托底成功，正在发送图片...', '📤')
                    _record_generation_event(task_id, 'telegram_send_started', '托底编辑成功后开始发送到 Telegram', stage='sending_telegram')
                    telegram_success = send_telegram_result(
                        fallback_result['image_path'],
                        prompt,
                        aspect_ratio,
                        gpt_resolution,
                        image_paths=fallback_result.get('image_paths'),
                    )
                else:
                    update_task_status(task_id, 'processing', 'Telegram 已关闭，正在整理结果...', stage='saving')
                    _record_generation_event(task_id, 'telegram_send_skipped', '托底编辑成功后按节点开关跳过 Telegram', stage='saving')

                result_files = _result_image_filenames(fallback_result)
                image_count = len(result_files) or len(fallback_result.get('image_paths') or [fallback_result.get('image_path')])
                filename = result_files[0] if result_files else os.path.basename(fallback_result['image_path'])
                if telegram_success or not telegram_enabled:
                    ok_text = f'托底编辑成功（共 {image_count} 张）' if image_count > 1 else '托底编辑成功'
                    progress_text = ok_text if telegram_enabled else '托底编辑成功，已按节点开关跳过 Telegram'
                    _finalize_generation_task(
                        task_id,
                        'succeeded' if telegram_enabled else 'succeeded_no_telegram',
                        run_id=run_id,
                        provider='chatgpt_pool',
                        route='gpt_pool_fallback_edit',
                        task_type=task_kind,
                        result_file=filename,
                        stage='done',
                        progress_text=progress_text,
                        result_files=result_files,
                        image_count=image_count,
                        extra={'fallback_source': 'chatgpt_pool', 'primary_error': primary_error},
                    )
                    _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload={'provider': 'chatgpt_pool', 'route': 'gpt_pool_fallback_edit', 'image_count': image_count})
                    send_status_notification(task_id, '✅ 托底编辑成功！', '🎉')
                    print(f"✅ 编辑托底成功：{task_id} -> {filename}")
                else:
                    progress_text = '托底编辑成功，但 Telegram 发送失败'
                    _finalize_generation_task(
                        task_id,
                        'succeeded_no_telegram',
                        run_id=run_id,
                        provider='chatgpt_pool',
                        route='gpt_pool_fallback_edit',
                        task_type=task_kind,
                        result_file=filename,
                        stage='done',
                        progress_text=progress_text,
                        result_files=result_files,
                        image_count=image_count,
                        extra={'fallback_source': 'chatgpt_pool', 'primary_error': primary_error},
                    )
                    _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload={'provider': 'chatgpt_pool', 'route': 'gpt_pool_fallback_edit', 'image_count': image_count, 'telegram_enabled': telegram_enabled})
                    print(f"⚠️ 编辑托底成功但 Telegram 发送失败：{task_id}")
                return

            raise

        # 状态 3: 保存图片
        update_task_status(
            task_id,
            'processing',
            '正在保存图片...',
            stage='saving',
            bytes_received=response_meta.get('bytes_received'),
            first_byte_at=response_meta.get('first_byte_at'),
            ttfb_ms=response_meta.get('ttfb_ms'),
        )
        send_status_notification(task_id, '编辑中... 正在保存图片...', '💾')

        # 文件命名：生成模型_日期时间
        from datetime import datetime
        now = datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        model_name = model.replace("gemini-", "").replace("-image-preview", "").replace("-image", "").replace(".", "")
        filename_base = f"{model_name}_{timestamp}"

        # 确保下载目录存在
        download_dir = daily_output_dir(now)
        download_dir.mkdir(parents=True, exist_ok=True)

        # 保存图片（带扩展名）
        filename_with_ext = f"{filename_base}.png"
        filepath = str(download_dir / filename_with_ext)
        filename = save_image(image_data, filepath)

        # 保存提示词到同名 txt 文件
        txt_path = download_dir / f"{filename_base}.txt"
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(prompt)
        try:
            write_obsidian_prompt_sidecar(Path(filepath), prompt, txt_path=txt_path)
        except Exception as exc:
            print(f"⚠️ 写入 Obsidian 提示词 md 失败: {exc}")
        print(f"💾 已保存图片：{filepath}")
        print(f"💾 已保存提示词：{txt_path}")
        save_thumbnail(filepath, filename)

        telegram_success = False
        if telegram_enabled:
            # 状态 4: 发送 Telegram
            update_task_status(task_id, 'processing', '正在发送到 Telegram...', stage='sending_telegram')
            send_status_notification(task_id, '编辑中... 正在发送图片...', '📤')
            _record_generation_event(task_id, 'telegram_send_started', '开始发送编辑结果到 Telegram', stage='sending_telegram')
            try:
                print(f"📤 准备发送 Telegram: {filepath}")
                # Telegram caption 限制 1024 字符，为了安全截断到 500
                caption = prompt[:500] + "..." if len(prompt) > 500 else prompt
                telegram_success = send_telegram(None, filepath, caption)
                if telegram_success:
                    print(f"✅ Telegram 发送成功")
                else:
                    error_msg = "Telegram 发送失败：send_telegram returned False"
                    print(f"❌ {error_msg}")
                    error_info = _translate_generation_failure(task_id, error_msg, provider='telegram', route='telegram', task_type=task_kind, stage='telegram_failed')
                    _finalize_generation_task(task_id, 'telegram_failed', run_id=run_id, stage='telegram_failed', progress_text=error_info.get('display_error') or error_msg, error_info=error_info, error_type='TelegramSendFailed', provider=task_provider, route=task_route, task_type=task_kind)
                    try:
                        send_status_notification(task_id, '❌ 发送失败：请检查 bot token/网络/文件路径', '⚠️')
                    except:
                        pass
            except Exception as e:
                error_msg = f"Telegram 发送失败：{str(e)}"
                print(f"❌ {error_msg}")
                error_info = _translate_generation_failure(task_id, error_msg, provider='telegram', route='telegram', task_type=task_kind, stage='telegram_failed', exception_name=type(e).__name__)
                _finalize_generation_task(task_id, 'telegram_failed', run_id=run_id, stage='telegram_failed', progress_text=error_info.get('display_error') or error_msg, error_info=error_info, error_type=type(e).__name__, provider=task_provider, route=task_route, task_type=task_kind)
                try:
                    send_status_notification(task_id, f'❌ 发送失败：{str(e)[:100]}', '⚠️')
                except:
                    pass
        else:
            update_task_status(task_id, 'processing', 'Telegram 已关闭，正在整理结果...', stage='saving')
            _record_generation_event(task_id, 'telegram_send_skipped', '已按节点开关跳过 Telegram', stage='saving')

        # 状态 5: 完成
        if telegram_success:
            _finalize_generation_task(task_id, 'succeeded', run_id=run_id, stage='done', progress_text='图片编辑成功', result_file=filename, result_files=[filename], image_count=1, provider=task_provider, route=task_route, task_type=task_kind)
            _record_generation_event(task_id, 'run_succeeded', '图片编辑成功', stage='done', payload={'provider': task_provider, 'route': task_route, 'image_count': 1})
            send_status_notification(task_id, '✅ 图片编辑成功！', '🎉')
            print(f"✅ 编辑任务成功：{task_id}")
        else:
            progress_text = '图片已保存，已按节点开关跳过 Telegram' if not telegram_enabled else '图片已保存，但 Telegram 发送失败'
            _finalize_generation_task(
                task_id,
                'succeeded_no_telegram',
                run_id=run_id,
                provider=task_provider,
                route=task_route,
                task_type=task_kind,
                result_file=filename,
                stage='done',
                progress_text=progress_text,
                result_files=[filename],
                image_count=1,
            )
            _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload={'provider': task_provider, 'route': task_route, 'image_count': 1, 'telegram_enabled': telegram_enabled})
            print(f"⚠️ 任务完成但未发送 Telegram: {task_id}")

    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        error_info = _translate_generation_failure(task_id, error_msg, provider=task_provider, route=task_route, task_type=task_kind, stage='failed', exception_name=error_type)
        print(f"❌ 编辑任务失败：{task_id} - {error_msg}")
        _finalize_generation_task(task_id, 'failed', run_id=run_id, stage='failed', progress_text=error_info.get('display_error') or error_msg, error_info=error_info, error_type=error_type, provider=task_provider, route=task_route, task_type=task_kind)
        send_status_notification(task_id, f'❌ 编辑失败：{(error_info.get("display_error") or error_msg)[:100]}', '⚠️')

def _annotate_gpt_route_result(result, route_resolution, *, requested_route, requested_model, requested_reasoning_effort):
    actual_model = str(result.get('main_model') or route_resolution.get('model') or requested_model)
    actual_reasoning = str(result.get('reasoning_effort') or route_resolution.get('reasoning_effort') or 'none')
    result['main_model'] = actual_model
    result['requested_main_model'] = requested_model
    if actual_model != requested_model:
        result['model_fallback_from'] = requested_model
    result['reasoning_effort'] = actual_reasoning
    result['requested_reasoning_effort'] = requested_reasoning_effort
    if actual_reasoning != requested_reasoning_effort:
        result['reasoning_fallback_from'] = requested_reasoning_effort
    result['requested_gpt_provider_route'] = requested_route
    result['model_role'] = str(route_resolution.get('model_role') or '')
    result['model_catalog_source'] = str(route_resolution.get('source') or '')
    image_engine = route_resolution.get('image_engine') or {}
    result['image_engine'] = str(image_engine.get('id') or '')
    result['image_engine_label'] = str(image_engine.get('label') or image_engine.get('id') or '')
    return result


def _generate_gpt_with_pool_fallback(task_id, prompt, ratio, resolution, quality, image_count=1, moderation='auto', prompt_mode='smart', main_model=None, reasoning_effort=None, gpt_provider_route='codex'):
    """Run Codex with managed OAuth preferred, then local auth, then account-pool fallback."""
    primary_error = None
    pool_error = None
    pool_result = None
    prompt = str(prompt or '')
    prompt_mode = _coerce_prompt_mode(prompt_mode)
    prompt_meta = {}
    if prompt_mode == 'web_search':
        prompt, prompt_meta = _prepare_web_search_generation_prompt(task_id, prompt)
    requested_main_model = _coerce_gpt_main_model(main_model)
    requested_reasoning_effort = _coerce_gpt_reasoning_effort(reasoning_effort)
    gpt_provider_route = _coerce_gpt_provider_route(gpt_provider_route)
    route_model = resolve_route_model(
        gpt_provider_route,
        requested_main_model,
        reasoning_effort=requested_reasoning_effort,
    )
    main_model = route_model.get('model') or requested_main_model
    reasoning_effort = route_model.get('reasoning_effort') or requested_reasoning_effort
    provider_timeout_seconds = _coerce_gpt_provider_total_timeout(None)

    if gpt_provider_route == 'codex' and not route_model.get('available'):
        primary_error = route_model.get('warning') or '当前 Codex 账号没有可用的图片生成模型'
        _append_task_route_trace(task_id, 'codex', 'skipped', primary_error)
    elif gpt_provider_route == 'codex':
        route_started = time.monotonic()
        provider_route = gpt_provider_route
        provider_label = 'Codex provider'
        provider_trace_route = provider_route
        provider_env, codex_auth_source = _resolve_codex_provider_env()
        _append_task_route_trace(
            task_id,
            provider_trace_route,
            'started',
            f'正在调用{provider_label}',
            timeout_seconds=provider_timeout_seconds,
        )
        if route_model.get('adapted'):
            _append_task_route_trace(
                task_id,
                provider_trace_route,
                'model_adapted',
                f"模型 {requested_main_model} 当前不可用，已改用 {main_model}",
            )
        if route_model.get('reasoning_adapted'):
            _append_task_route_trace(
                task_id,
                provider_trace_route,
                'reasoning_adapted',
                f"推理强度 {requested_reasoning_effort} 不适用于 {main_model}，已改用 {reasoning_effort}",
            )
        try:
            update_task_status(task_id, 'processing', f'正在调用{provider_label}...', stage='calling_gpt')
            send_status_notification(task_id, f'生成中... 正在调用{provider_label}...', '🤖')
            result = generate_image_gpt_codex(
                prompt,
                ratio,
                resolution,
                quality,
                image_count=image_count,
                moderation=moderation,
                prompt_mode=prompt_mode,
                main_model=main_model,
                reasoning_effort=reasoning_effort,
                total_timeout_seconds=provider_timeout_seconds,
                on_image_saved=_make_gpt_image_progress_callback(task_id, image_count),
                on_provider_wait=_make_gpt_provider_wait_callback(task_id),
                should_cancel=lambda: _is_task_canceled(task_id),
                provider_env=provider_env,
            )
            if result.get('canceled'):
                _append_task_route_trace(
                    task_id,
                    provider_trace_route,
                    'canceled',
                    f'{provider_label} 已取消',
                    elapsed_seconds=int(time.monotonic() - route_started),
                )
                return result, 'canceled', None
            if result.get('success'):
                if prompt_meta:
                    result.update(prompt_meta)
                result['prompt_mode'] = prompt_mode
                result['gpt_provider_route'] = gpt_provider_route
                _annotate_gpt_route_result(
                    result,
                    route_model,
                    requested_route=gpt_provider_route,
                    requested_model=requested_main_model,
                    requested_reasoning_effort=requested_reasoning_effort,
                )
                result['codex_auth_source'] = codex_auth_source
                result['route_trace'] = (get_task(task_id) or {}).get('params', {}).get('route_trace')
                _append_task_route_trace(
                    task_id,
                    provider_trace_route,
                    'succeeded',
                    f'{provider_label} 成功返回',
                    elapsed_seconds=int(time.monotonic() - route_started),
                )
                result['route_trace'] = (get_task(task_id) or {}).get('params', {}).get('route_trace')
                return result, provider_route, None
            primary_error = result.get('error', f'{provider_label} 失败')
            _append_task_route_trace(
                task_id,
                provider_trace_route,
                'failed',
                primary_error,
                elapsed_seconds=int(time.monotonic() - route_started),
            )
            print(f"⚠️ {provider_label} 失败：{primary_error}")
        except Exception as e:
            primary_error = str(e)
            _append_task_route_trace(
                task_id,
                provider_trace_route,
                'failed',
                primary_error,
                elapsed_seconds=int(time.monotonic() - route_started),
            )
            print(f"⚠️ {provider_label} 异常：{primary_error}")
    else:
        primary_error = '已选择账号池 API 线路，跳过本地 Codex provider'
        _append_task_route_trace(task_id, 'codex', 'skipped', primary_error)

    if _is_task_canceled(task_id):
        return {"success": False, "canceled": True, "error": "canceled"}, 'canceled', primary_error

    provider_error_text = _format_gpt_provider_error(primary_error)
    pool_cfg = get_chatgpt_pool_config(ensure_auth_key=True)
    if pool_cfg.get("enabled"):
        route_started = time.monotonic()
        _append_task_route_trace(task_id, 'chatgpt_pool', 'started', '正在调用 ChatGPT 账号池 API')
        pool_text = '正在调用 ChatGPT 账号池 API...' if gpt_provider_route == 'chatgpt_pool' else f'{provider_error_text}，切换 ChatGPT 账号池托底...'
        update_task_status(task_id, 'fallback_running', pool_text, stage='fallback_running')
        if gpt_provider_route == 'chatgpt_pool':
            send_status_notification(task_id, '生成中... 正在调用 ChatGPT 账号池 API...', '🛟')
        else:
            send_status_notification(task_id, f'{provider_error_text}，切换 ChatGPT 账号池托底中...', '🛟')
        try:
            pool_model_resolution = resolve_route_model(
                'chatgpt_pool',
                requested_main_model,
                reasoning_effort=requested_reasoning_effort,
            )
            pool_main_model = pool_model_resolution.get('model') or DEFAULT_POOL_MODEL
            if pool_model_resolution.get('adapted'):
                _append_task_route_trace(
                    task_id,
                    'chatgpt_pool',
                    'model_adapted',
                    f"账号池不支持 {requested_main_model}，已改用 {pool_main_model}",
                )
            if prompt_mode == 'web_search':
                pool_prompt, pool_prompt_meta = prompt, prompt_meta
            else:
                pool_prompt, pool_prompt_meta = _prepare_chatgpt_pool_generation_prompt(task_id, prompt, prompt_mode)
            update_task_status(task_id, 'fallback_running', '正在调用 ChatGPT 账号池生成图片...', stage='fallback_running')
            pool_result = generate_image_gpt_pool(
                pool_prompt,
                ratio,
                resolution,
                quality,
                image_count=image_count,
                prompt_mode=prompt_mode,
                main_model=pool_main_model,
                on_image_saved=_make_gpt_image_progress_callback(task_id, image_count),
                on_provider_wait=_make_gpt_pool_wait_callback(task_id),
                timeout_seconds=pool_cfg.get('timeout_seconds'),
            )
        except Exception as e:
            pool_error = str(e)
            _append_task_route_trace(
                task_id,
                'chatgpt_pool',
                'failed',
                pool_error,
                elapsed_seconds=int(time.monotonic() - route_started),
            )
            print(f"⚠️ ChatGPT 账号池托底异常：{pool_error}")
        else:
            if pool_prompt_meta:
                pool_result.update(pool_prompt_meta)
            if pool_result.get('success'):
                pool_result.setdefault('requested_resolution', resolution)
                pool_result.setdefault('effective_resolution', pool_result.get('actual_resolution') or pool_result.get('requested_resolution') or resolution)
                pool_result['fallback_source'] = 'chatgpt_pool'
                pool_result['requested_image_count'] = image_count
                pool_result['prompt_mode'] = prompt_mode
                actual_pool_model = pool_result.get('main_model') or pool_main_model
                pool_result['main_model'] = actual_pool_model
                pool_result['reasoning_effort'] = pool_model_resolution.get('reasoning_effort') or 'none'
                pool_result['gpt_provider_route'] = 'chatgpt_pool'
                _annotate_gpt_route_result(
                    pool_result,
                    pool_model_resolution,
                    requested_route=gpt_provider_route,
                    requested_model=requested_main_model,
                    requested_reasoning_effort=requested_reasoning_effort,
                )
                _append_task_route_trace(
                    task_id,
                    'chatgpt_pool',
                    'succeeded',
                    'ChatGPT 账号池 API 成功返回',
                    elapsed_seconds=int(time.monotonic() - route_started),
                )
                pool_result['route_trace'] = (get_task(task_id) or {}).get('params', {}).get('route_trace')
                return pool_result, 'chatgpt_pool', primary_error
            pool_error = pool_result.get('error', 'ChatGPT 账号池托底失败')
            _append_task_route_trace(
                task_id,
                'chatgpt_pool',
                'failed',
                pool_error,
                elapsed_seconds=int(time.monotonic() - route_started),
            )
            print(f"⚠️ ChatGPT 账号池托底失败：{pool_error}")
    else:
        pool_error = 'ChatGPT account pool sidecar disabled'
        _append_task_route_trace(task_id, 'chatgpt_pool', 'skipped', pool_error)

    if _is_task_canceled(task_id):
        return {"success": False, "canceled": True, "error": "canceled"}, 'canceled', primary_error

    fallback_text = f'{provider_error_text}，切换账号池托底...'
    update_task_status(task_id, 'fallback_running', fallback_text, stage='fallback_running')
    if pool_error:
        send_status_notification(task_id, f'{_format_gpt_pool_error(pool_error)}，切换账号池托底中...', '🛟')
    else:
        send_status_notification(task_id, f'{provider_error_text}，切换账号池托底中...', '🛟')

    failure_message = f"本地 provider 失败：{primary_error} | 账号池托底失败：{pool_error}"
    if isinstance(pool_result, dict):
        raise ChatgptPoolGenerationError(failure_message, pool_result)
    raise RuntimeError(failure_message)


def _make_gpt_image_progress_callback(task_id, requested_count):
    try:
        total = max(1, int(requested_count or 1))
    except (TypeError, ValueError):
        total = 1

    def on_image_saved(partial_result, saved_count, total_count):
        if _is_task_canceled(task_id):
            return
        result_files = _result_image_filenames(partial_result)
        if not result_files:
            return
        expected_total = max(1, int(total_count or total))
        visible_count = len(result_files)
        progress_text = f'GPT 图片生成中（已完成 {visible_count}/{expected_total} 张）'
        update_task_status(
            task_id,
            'processing',
            progress_text,
            stage='generating_images',
            result_file=result_files[0],
            result_files=json.dumps(result_files, ensure_ascii=False),
        )

    return on_image_saved


def _make_gpt_provider_wait_callback(task_id):
    def on_wait(label, elapsed_seconds, remaining_seconds):
        update_task_fields(
            task_id,
            stage='calling_gpt',
            progress_text=f'正在等待本地 GPT provider 返回（已等待 {elapsed_seconds}s）...',
            heartbeat_at=int(time.time()),
        )

    return on_wait


def _make_gpt_pool_wait_callback(task_id):
    def on_wait(label, elapsed_seconds, remaining_seconds):
        update_task_fields(
            task_id,
            stage='fallback_running',
            progress_text=f'正在等待 ChatGPT 账号池返回（已等待 {elapsed_seconds}s）...',
            heartbeat_at=int(time.time()),
        )

    return on_wait


def _format_download_bytes(value):
    try:
        size = max(0, int(value or 0))
    except (TypeError, ValueError):
        size = 0
    if size >= 1024 * 1024:
        return f'{size / 1024 / 1024:.1f} MB'
    if size >= 1024:
        return f'{size / 1024:.0f} KB'
    return f'{size} B'


def _third_party_download_progress_percent(event):
    try:
        count = max(1, int(event.get('item_count') or 1))
    except (TypeError, ValueError):
        count = 1
    try:
        index = max(1, min(count, int(event.get('item_index') or 1)))
    except (TypeError, ValueError):
        index = 1
    try:
        bytes_received = max(0, int(event.get('bytes_received') or 0))
    except (TypeError, ValueError):
        bytes_received = 0
    try:
        total_bytes = max(0, int(event.get('total_bytes') or 0))
    except (TypeError, ValueError):
        total_bytes = 0

    name = str(event.get('event') or '')
    if name == 'download_complete':
        item_ratio = 1.0
    elif total_bytes > 0:
        item_ratio = max(0.0, min(0.98, bytes_received / total_bytes))
    elif bytes_received > 0:
        item_ratio = max(0.0, min(0.85, bytes_received / (12 * 1024 * 1024)))
    else:
        item_ratio = 0.0
    overall_ratio = ((index - 1) + item_ratio) / count
    return max(70, min(95, round(70 + overall_ratio * 25)))


def _make_third_party_download_progress_callback(task_id):
    recorded_events = set()

    def on_progress(event):
        if _is_task_canceled(task_id):
            return
        if not isinstance(event, dict):
            return
        name = str(event.get('event') or '').strip()
        if not name:
            return
        try:
            index = max(1, int(event.get('item_index') or 1))
        except (TypeError, ValueError):
            index = 1
        try:
            count = max(1, int(event.get('item_count') or 1))
        except (TypeError, ValueError):
            count = 1
        try:
            bytes_received = max(0, int(event.get('bytes_received') or 0))
        except (TypeError, ValueError):
            bytes_received = 0
        try:
            total_bytes = max(0, int(event.get('total_bytes') or 0))
        except (TypeError, ValueError):
            total_bytes = 0
        progress = _third_party_download_progress_percent(event)
        size_text = _format_download_bytes(bytes_received)
        total_text = _format_download_bytes(total_bytes) if total_bytes else ''
        image_suffix = f' {index}/{count}' if count > 1 else ''
        stage = 'downloading_third_party_image'
        extra = {
            'progress': progress,
            'bytes_received': bytes_received,
        }
        severity = 'info'
        event_type = ''

        if name == 'download_start':
            message = f'正在下载第三方图片{image_suffix}...'
            event_type = 'third_party_download_started'
        elif name == 'download_first_byte':
            message = f'第三方图片{image_suffix}已开始返回，正在下载...'
            extra['first_byte_at'] = int(time.time())
        elif name == 'download_progress':
            if total_text:
                message = f'正在下载第三方图片{image_suffix}：{size_text}/{total_text}'
            else:
                message = f'正在下载第三方图片{image_suffix}：已接收 {size_text}'
        elif name == 'download_retry':
            next_attempt = event.get('next_attempt') or event.get('attempt') or 1
            max_attempts = event.get('max_attempts') or 1
            message = f'第三方图片下载中断，正在重试 {next_attempt}/{max_attempts}...'
            extra['transport_error_type'] = str(event.get('error_type') or 'download_retry')
            severity = 'warning'
            event_type = 'third_party_download_retry'
        elif name == 'download_complete':
            message = f'第三方图片{image_suffix}下载完成，正在保存...'
            event_type = 'third_party_download_completed'
        else:
            return

        update_task_status(task_id, 'processing', message, stage=stage, **extra)
        if event_type:
            event_key = (event_type, index, event.get('attempt'), event.get('next_attempt'))
            if event_key not in recorded_events:
                recorded_events.add(event_key)
                payload = {
                    key: event.get(key)
                    for key in (
                        'attempt',
                        'next_attempt',
                        'max_attempts',
                        'item_index',
                        'item_count',
                        'bytes_received',
                        'total_bytes',
                        'error_type',
                    )
                    if event.get(key) is not None
                }
                _record_generation_event(task_id, event_type, message, stage=stage, severity=severity, payload=payload)

    return on_progress


def _is_task_canceled(task_id):
    task = get_task(task_id)
    return str(task.get('status') if task else '') == 'canceled'


def _finish_canceled_gpt_task(task_id, result=None):
    result = result or {}
    result_files = _result_image_filenames(result) if result.get('image_path') or result.get('image_paths') else []
    progress_text = f'任务已取消，已保留 {len(result_files)} 张图' if result_files else '任务已取消'
    route = _generation_run_route(task_id, result.get('gpt_provider_route') or result.get('fallback_source') or '')
    provider = 'chatgpt_pool'
    if 'third_party' in route:
        provider = 'third_party_image_api'
    elif 'codex' in route:
        provider = 'codex'
    _finalize_generation_task(
        task_id,
        'canceled',
        run_id=_generation_last_run_id(task_id),
        provider=provider,
        route=route,
        task_type=(get_task(task_id) or {}).get('type') or 'gpt',
        result_file=result_files[0] if result_files else None,
        stage='canceled',
        progress_text=progress_text,
        result_files=result_files,
        image_count=len(result_files),
        error_type='UserCanceled',
    )
    _record_generation_event(task_id, 'run_canceled', progress_text, stage='canceled', severity='warning', payload={'route': route, 'image_count': len(result_files)})
    send_status_notification(task_id, progress_text, '⏹')
    print(f"⏹ GPT 任务已取消：{task_id}（保留 {len(result_files)} 张）")


def process_gpt_editable_file_task(
    task_id,
    kind,
    prompt,
    base64_images=None,
    prompt_mode='smart',
    gpt_provider_route='chatgpt_pool',
    archive_enabled=True,
    telegram_enabled=True,
):
    """后台线程：处理 ChatGPT Web 可编辑 PPT/PSD 文件任务。"""
    run_id = ''
    task_kind = 'gpt-file'
    task_provider = 'chatgpt_pool'
    task_route = 'chatgpt_pool_editable'
    try:
        kind = _coerce_gpt_task_type(kind)
        if kind not in ('ppt', 'psd'):
            raise RuntimeError('不支持的可编辑文件类型')
        images = [str(item or '').strip() for item in (base64_images or []) if str(item or '').strip()]
        if kind == 'psd' and not images:
            raise RuntimeError('PSD 任务需要至少一张参考图')

        _merge_task_params(task_id, {
            'task_type': kind,
            'artifact_type': kind,
            'gpt_provider_route': 'chatgpt_pool',
            'prompt_mode': prompt_mode,
            'archive_enabled': bool(archive_enabled),
            'telegram_enabled': bool(telegram_enabled),
        })
        run_id = _start_generation_audit(
            task_id,
            task_kind,
            prompt,
            (get_task(task_id) or {}).get('params') or {},
            provider=task_provider,
            route=task_route,
            stage='preparing',
        )
        print(f"📄 开始处理 {kind.upper()} 文件任务：{task_id}")
        send_status_notification(task_id, f'已提交 {kind.upper()} 文件任务，请等待...', '✅')
        update_task_status(task_id, 'preparing', f'正在准备 {kind.upper()} 文件任务...', stage='preparing')
        update_task_status(task_id, 'processing', '正在调用 ChatGPT 账号池 Web API...', stage='calling_chatgpt_pool')
        _append_task_route_trace(task_id, 'chatgpt_pool_editable', 'started', f'正在生成 {kind.upper()} 文件')
        _record_generation_event(task_id, 'provider_call_started', f'开始调用 ChatGPT 账号池生成 {kind.upper()} 文件', stage='calling_chatgpt_pool', payload={'provider': task_provider, 'route': task_route, 'artifact_type': kind})

        result = generate_editable_file_gpt_pool(kind=kind, prompt=prompt, base64_images=images, task_id=task_id)
        if not result.get('success'):
            error = result.get('error') or 'ChatGPT 账号池可编辑文件任务失败'
            _append_task_route_trace(task_id, 'chatgpt_pool_editable', 'failed', error)
            raise RuntimeError(_format_gpt_pool_error(error))
        if _is_task_canceled(task_id):
            update_task(task_id, 'canceled', stage='canceled', progress_text='任务已取消')
            return

        update_task_status(task_id, 'processing', '正在保存文件产物...', stage='saving')
        manifest = save_editable_artifacts(
            kind=kind,
            prompt=prompt,
            primary=result.get('primary') or {},
            zip_artifact=result.get('zip') if isinstance(result.get('zip'), dict) else None,
            task_id=task_id,
            conversation_id=str(result.get('conversation_id') or ''),
            archive_enabled=bool(archive_enabled),
            strict_psd_validation=(kind == 'psd'),
        )
        _record_generation_event(task_id, 'artifact_saved', f'{kind.upper()} 文件产物已保存', stage='saving', payload={'artifact_type': kind, 'result_count': len(manifest.get("result_files") or [])})
        _append_task_route_trace(task_id, 'chatgpt_pool_editable', 'succeeded', f'{kind.upper()} 文件生成成功')
        _merge_task_params(task_id, {
            'file_manifest': manifest,
            'file_manifest_url': manifest.get('manifest_url'),
            'editable_preview_status': (manifest.get('preview') or {}).get('status'),
            'editable_artifact_type': kind,
        })

        result_files = manifest.get('result_files') or []
        primary_file = (manifest.get('primary') or {}).get('relative_path') or (result_files[0] if result_files else '')
        telegram_success = False
        primary_path = (manifest.get('primary') or {}).get('path')
        if telegram_enabled and primary_path:
            update_task_status(task_id, 'processing', '正在发送到 Telegram...', stage='sending_telegram')
            _record_generation_event(task_id, 'telegram_send_started', f'开始发送 {kind.upper()} 文件到 Telegram', stage='sending_telegram')
            caption = f"📎 {kind.upper()} 文件"
            if prompt:
                caption += "\n" + (prompt[:420] + ("..." if len(prompt) > 420 else ""))
            telegram_success = send_telegram(None, primary_path, caption[:900])
        else:
            _record_generation_event(task_id, 'telegram_send_skipped', '已按节点开关跳过 Telegram', stage='saving')

        status = 'succeeded' if (telegram_success or not telegram_enabled) else 'succeeded_no_telegram'
        if telegram_success:
            progress = f'{kind.upper()} 文件生成成功'
        elif telegram_enabled:
            progress = f'{kind.upper()} 文件已保存，Telegram 发送失败'
        else:
            progress = f'{kind.upper()} 文件生成成功，已按节点开关跳过 Telegram'
        _finalize_generation_task(
            task_id,
            status,
            run_id=run_id,
            provider=task_provider,
            route=task_route,
            task_type=task_kind,
            result_file=primary_file,
            stage='done',
            progress_text=progress,
            result_files=result_files,
            image_count=len(result_files),
            extra={'artifact_type': kind, 'conversation_id': str(result.get('conversation_id') or '')},
        )
        _record_generation_event(task_id, 'run_succeeded', progress, stage='done', payload={'provider': task_provider, 'route': task_route, 'artifact_type': kind, 'result_count': len(result_files)})
        send_status_notification(task_id, f'✅ {kind.upper()} 文件生成成功！', '🎉')
        print(f"✅ {kind.upper()} 文件任务成功：{task_id}")

    except Exception as e:
        if _is_task_canceled(task_id):
            _finalize_generation_task(
                task_id,
                'canceled',
                run_id=run_id,
                stage='canceled',
                progress_text='任务已取消',
                error_type='UserCanceled',
                provider=task_provider,
                route=task_route,
                task_type=task_kind,
                extra={'artifact_type': kind if 'kind' in locals() else ''},
            )
            return
        raw_error_msg = str(e)
        error_type = type(e).__name__
        error_info = _translate_generation_failure(
            task_id,
            raw_error_msg,
            provider=task_provider,
            route=task_route,
            task_type=task_kind,
            stage='failed',
            exception_name=error_type,
        )
        error_msg = error_info.get('display_error') or _format_gpt_failure_error(raw_error_msg)
        print(f"❌ 可编辑文件任务失败：{task_id} - {raw_error_msg}")
        _finalize_generation_task(task_id, 'failed', run_id=run_id, stage='failed', progress_text=error_msg, error_info=error_info, error_type=error_type, provider=task_provider, route=task_route, task_type=task_kind, extra={'artifact_type': kind if 'kind' in locals() else ''})
        send_status_notification(task_id, f'❌ 文件生成失败：{error_msg[:100]}', '⚠️')

def process_gpt_task(task_id, prompt, ratio, resolution, quality='auto', image_count=1, moderation='auto', prompt_mode='smart', main_model=None, reasoning_effort=None, gpt_provider_route='codex', use_third_party_api=False, archive_enabled=True, telegram_enabled=True):
    """后台线程：处理 GPT 任务（Codex 托管授权优先，再账号池托底）"""
    run_id = ''
    task_kind = 'gpt'
    task_provider = 'codex'
    task_route = 'codex'
    try:
        requested_main_model = _coerce_gpt_main_model(main_model)
        main_model = requested_main_model
        requested_reasoning_effort = _coerce_gpt_reasoning_effort(reasoning_effort)
        reasoning_effort = requested_reasoning_effort
        gpt_provider_route = _coerce_gpt_provider_route(gpt_provider_route)
        use_third_party_api = _gpt_route_uses_third_party(gpt_provider_route) or _coerce_use_third_party_api(use_third_party_api)
        archive_enabled = _coerce_bool(archive_enabled, True)
        telegram_enabled = _coerce_bool(telegram_enabled, True)
        _merge_task_params(task_id, {
            'archive_enabled': archive_enabled,
            'telegram_enabled': telegram_enabled,
        })
        task_route = 'third_party_image_api' if use_third_party_api else _coerce_gpt_provider_route(gpt_provider_route)
        task_provider = 'third_party_image_api' if use_third_party_api else ('chatgpt_pool' if task_route == 'chatgpt_pool' else 'codex')
        run_id = _start_generation_audit(
            task_id,
            task_kind,
            prompt,
            (get_task(task_id) or {}).get('params') or {},
            provider=task_provider,
            route=task_route,
            stage='preparing',
        )
        print(f"🎨 开始处理 GPT 任务：{task_id}（目标 {image_count} 张）")

        send_status_notification(task_id, '已提交 GPT 图片生成任务，请等待...', '✅')
        update_task_status(task_id, 'preparing', '正在准备生成...')
        update_task_status(task_id, 'processing', 'GPT 生成中...')

        primary_error = None
        prompt_meta = {}
        if _coerce_prompt_mode(prompt_mode) == 'web_search' and use_third_party_api:
            prompt, prompt_meta = _prepare_web_search_generation_prompt(task_id, prompt)
        if use_third_party_api:
            third_party_model = resolve_route_model(
                'third_party_image_api',
                requested_main_model,
                reasoning_effort=requested_reasoning_effort,
            )
            main_model = third_party_model.get('model') or requested_main_model
            reasoning_effort = third_party_model.get('reasoning_effort') or 'none'
            route_started = time.monotonic()
            _append_task_route_trace(task_id, 'third_party_image_api', 'started', '正在调用第三方图片 API')
            update_task_status(task_id, 'processing', '正在调用第三方图片 API...', stage='calling_third_party_image_api')
            send_status_notification(task_id, '生成中... 正在调用第三方图片 API...', '🧩')
            _record_generation_event(task_id, 'provider_call_started', '开始调用第三方图片 API', stage='calling_third_party_image_api', payload={'provider': 'third_party_image_api', 'route': 'third_party_image_api'})
            result = generate_image_third_party(
                prompt,
                ratio,
                resolution,
                quality,
                image_count=image_count,
                progress_callback=_make_third_party_download_progress_callback(task_id),
            )
            result['fallback_source'] = 'third_party_image_api'
            result['gpt_provider_route'] = 'third_party_image_api'
            result['prompt_mode'] = prompt_mode
            _annotate_gpt_route_result(
                result,
                third_party_model,
                requested_route=gpt_provider_route,
                requested_model=requested_main_model,
                requested_reasoning_effort=requested_reasoning_effort,
            )
            if prompt_meta:
                result.update(prompt_meta)
            _append_task_route_trace(
                task_id,
                'third_party_image_api',
                'succeeded',
                '第三方图片 API 成功返回',
                elapsed_seconds=int(time.monotonic() - route_started),
            )
            result['route_trace'] = (get_task(task_id) or {}).get('params', {}).get('route_trace')
            source = 'third_party_image_api'
        else:
            result, source, primary_error = _generate_gpt_with_pool_fallback(
                task_id, prompt, ratio, resolution, quality, image_count=image_count, moderation=moderation, prompt_mode=prompt_mode, main_model=main_model, reasoning_effort=requested_reasoning_effort, gpt_provider_route=gpt_provider_route
            )
        if source == 'canceled' or _is_task_canceled(task_id):
            _finish_canceled_gpt_task(task_id, result)
            return
        if _is_task_canceled(task_id):
            _finish_canceled_gpt_task(task_id, result)
            return

        resolution_meta = _augment_result_resolution_metadata(result, resolution)
        delivery_resolution = resolution_meta.get('effective_resolution') or result.get('effective_resolution') or resolution
        telegram_success = False
        if telegram_enabled:
            update_task_status(task_id, 'processing', '正在发送到 Telegram...', stage='sending_telegram')
            send_status_notification(task_id, '生成中... 正在发送图片...', '📤')
            _record_generation_event(task_id, 'telegram_send_started', '开始发送 GPT 图片到 Telegram', stage='sending_telegram')
            if _is_task_canceled(task_id):
                _finish_canceled_gpt_task(task_id, result)
                return
            telegram_success = send_telegram_result(
                result['image_path'],
                prompt,
                ratio,
                delivery_resolution,
                image_paths=result.get('image_paths'),
            )
        else:
            update_task_status(task_id, 'processing', 'Telegram 已关闭，正在整理结果...', stage='saving')
            _record_generation_event(task_id, 'telegram_send_skipped', '已按节点开关跳过 Telegram', stage='saving')

        result_files = _result_image_filenames(result)
        _merge_task_params(task_id, {
            'prompt_mode': result.get('prompt_mode') or prompt_mode,
            'gpt_provider_route': result.get('gpt_provider_route') or gpt_provider_route,
            'use_third_party_api': use_third_party_api,
            'archive_enabled': archive_enabled,
            'telegram_enabled': telegram_enabled,
            'third_party_api': bool(result.get('third_party_api')),
            'requested_resolution': result.get('requested_resolution') or resolution,
            'actual_resolution': result.get('actual_resolution'),
            'actual_resolutions': result.get('actual_resolutions'),
            'effective_resolution': result.get('effective_resolution'),
            'resolution_mismatch': result.get('resolution_mismatch'),
            'requested_size': result.get('requested_size'),
            'actual_width': result.get('actual_width'),
            'actual_height': result.get('actual_height'),
            'actual_size': result.get('actual_size'),
            'actual_megapixels': result.get('actual_megapixels'),
            'main_model': result.get('main_model') or main_model,
            'requested_main_model': result.get('requested_main_model') or requested_main_model,
            'model_fallback_from': result.get('model_fallback_from'),
            'requested_gpt_provider_route': result.get('requested_gpt_provider_route') or gpt_provider_route,
            'reasoning_effort': result.get('reasoning_effort') or reasoning_effort,
            'requested_reasoning_effort': result.get('requested_reasoning_effort') or requested_reasoning_effort,
            'reasoning_fallback_from': result.get('reasoning_fallback_from'),
            'model_role': result.get('model_role'),
            'model_catalog_source': result.get('model_catalog_source'),
            'image_engine': result.get('image_engine'),
            'image_engine_label': result.get('image_engine_label'),
            'provider_total_timeout_seconds': _coerce_gpt_provider_total_timeout(None),
            'codex_auth_source': result.get('codex_auth_source'),
            'route_trace': result.get('route_trace'),
            'revised_prompt': result.get('revised_prompt'),
            'revised_prompts': result.get('revised_prompts'),
            'fallback_source': result.get('fallback_source'),
            'prompt_optimized': result.get('prompt_optimized'),
            'prompt_optimized_by': result.get('prompt_optimized_by'),
            'prompt_skill_provider': result.get('prompt_skill_provider'),
            'prompt_skill_model': result.get('prompt_skill_model'),
            'prompt_skill': result.get('prompt_skill'),
            'prompt_skill_output': result.get('prompt_skill_output'),
            'prompt_skill_latency_seconds': result.get('prompt_skill_latency_seconds'),
            'original_prompt': result.get('original_prompt'),
            'optimized_prompt': result.get('optimized_prompt'),
            'prompt_polish_error': result.get('prompt_polish_error'),
            'web_search_answer': result.get('web_search_answer'),
            'web_search_sources': result.get('web_search_sources'),
            'web_search_conversation_id': result.get('web_search_conversation_id'),
            'web_search_model': result.get('web_search_model'),
            'actual_sizes': result.get('actual_sizes'),
            'render_contract_warnings': result.get('render_contract_warnings'),
            'partial_errors': result.get('partial_errors'),
        })
        requested_count = max(1, int(image_count or 1))
        actual_count = len(result_files) or len(result.get('image_paths') or [result.get('image_path')])
        filename = result_files[0] if result_files else os.path.basename(result['image_path'])
        if telegram_success or not telegram_enabled:
            if not telegram_enabled:
                progress_text = 'GPT 图片生成成功，已按节点开关跳过 Telegram'
            elif actual_count < requested_count:
                progress_text = f'GPT 图片生成完成（{actual_count}/{requested_count} 张）'
            elif result.get('render_contract_warnings'):
                progress_text = 'GPT 图片生成成功（注意：实际尺寸/比例与请求不完全一致）'
            else:
                progress_text = f'GPT 图片生成成功（共 {actual_count} 张）' if actual_count > 1 else 'GPT 图片生成成功'
            _finalize_generation_task(
                task_id,
                'succeeded',
                run_id=run_id,
                provider='third_party_image_api' if source == 'third_party_image_api' else ('chatgpt_pool' if source == 'chatgpt_pool' else 'codex'),
                route=result.get('gpt_provider_route') or source or task_route,
                task_type=task_kind,
                result_file=filename,
                progress_text=progress_text,
                result_files=result_files,
                image_count=actual_count,
                extra={'fallback_source': result.get('fallback_source'), 'render_contract_warnings': result.get('render_contract_warnings'), 'partial_errors': result.get('partial_errors')},
            )
            _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload={'provider': 'third_party_image_api' if source == 'third_party_image_api' else ('chatgpt_pool' if source == 'chatgpt_pool' else 'codex'), 'route': result.get('gpt_provider_route') or source or task_route, 'image_count': actual_count, 'partial_errors': result.get('partial_errors')})
            send_status_notification(task_id, '✅ GPT 图片生成成功！', '🎉')
            print(f"✅ GPT 任务成功：{task_id} ({source})")
        else:
            progress_text = 'GPT 图片已生成，但 Telegram 发送失败'
            _finalize_generation_task(
                task_id,
                'succeeded_no_telegram',
                run_id=run_id,
                provider='third_party_image_api' if source == 'third_party_image_api' else ('chatgpt_pool' if source == 'chatgpt_pool' else 'codex'),
                route=result.get('gpt_provider_route') or source or task_route,
                task_type=task_kind,
                result_file=filename,
                progress_text=progress_text,
                result_files=result_files,
                image_count=actual_count,
                extra={'fallback_source': result.get('fallback_source'), 'partial_errors': result.get('partial_errors')},
            )
            _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload={'provider': 'third_party_image_api' if source == 'third_party_image_api' else ('chatgpt_pool' if source == 'chatgpt_pool' else 'codex'), 'route': result.get('gpt_provider_route') or source or task_route, 'image_count': actual_count, 'telegram_enabled': telegram_enabled, 'partial_errors': result.get('partial_errors')})
            print(f"⚠️ GPT 任务完成但未发送 Telegram: {task_id} ({source})")

    except Exception as e:
        raw_error_msg = str(e)
        error_type = type(e).__name__
        pool_failure = _chatgpt_pool_failure_metadata(e)
        if pool_failure:
            _merge_task_params(task_id, {'provider_failure': pool_failure})
        error_info = _translate_generation_failure(
            task_id,
            raw_error_msg,
            provider=task_provider,
            route=task_route,
            task_type=task_kind,
            stage='failed',
            exception_name=error_type,
        )
        if pool_failure.get('error_code'):
            error_info['error_code'] = str(pool_failure.get('error_code'))
        if pool_failure.get('timed_out'):
            error_info['error_category'] = 'timeout'
            provider_error = getattr(e, 'provider_result', {}).get('error')
            error_info['display_error'] = _format_gpt_pool_error(provider_error)
        error_msg = error_info.get('display_error') or _format_gpt_failure_error(raw_error_msg)
        print(f"❌ GPT 任务失败：{task_id} - {raw_error_msg}")
        if error_msg != raw_error_msg:
            print(f"↪️ 用户可见错误：{error_msg}")
        _finalize_generation_task(task_id, 'failed', run_id=run_id, stage='failed', progress_text=error_msg, error_info=error_info, error_type=error_type, provider=task_provider, route=task_route, task_type=task_kind, extra={'provider_failure': pool_failure} if pool_failure else None)
        send_status_notification(task_id, f'❌ GPT 生成失败：{error_msg[:100]}', '⚠️')

def process_gpt_edit_task(task_id, prompt, images, ratio, resolution, quality='auto', moderation='auto', mask=None, prompt_mode='smart', main_model=None, reasoning_effort=None, use_third_party_api=False, gpt_provider_route='codex', archive_enabled=True, telegram_enabled=True):
    """后台线程：处理 GPT 图像编辑任务（本地 Codex provider）。"""
    run_id = ''
    task_kind = 'gpt-edit'
    task_provider = 'codex'
    task_route = 'codex_edit'
    try:
        requested_main_model = _coerce_gpt_main_model(main_model)
        requested_reasoning_effort = _coerce_gpt_reasoning_effort(reasoning_effort)
        gpt_provider_route = _coerce_gpt_provider_route(gpt_provider_route)
        use_third_party_api = _gpt_route_uses_third_party(gpt_provider_route) or _coerce_use_third_party_api(use_third_party_api)
        archive_enabled = _coerce_bool(archive_enabled, True)
        telegram_enabled = _coerce_bool(telegram_enabled, True)
        use_chatgpt_pool = (not use_third_party_api) and gpt_provider_route == 'chatgpt_pool'
        route_for_model = 'third_party_image_api' if use_third_party_api else ('chatgpt_pool' if use_chatgpt_pool else 'codex')
        model_resolution = resolve_route_model(
            route_for_model,
            requested_main_model,
            reasoning_effort=requested_reasoning_effort,
        )
        codex_unavailable_error = ''
        if route_for_model == 'codex' and not model_resolution.get('available'):
            codex_unavailable_error = model_resolution.get('warning') or '当前 Codex 账号没有可用的图片编辑模型'
            if get_chatgpt_pool_config(ensure_auth_key=True).get('enabled'):
                use_chatgpt_pool = True
                route_for_model = 'chatgpt_pool'
                model_resolution = resolve_route_model(
                    route_for_model,
                    requested_main_model,
                    reasoning_effort=requested_reasoning_effort,
                )
        main_model = model_resolution.get('model') or requested_main_model
        reasoning_effort = model_resolution.get('reasoning_effort') or requested_reasoning_effort
        source_count = len(images or [])
        task_route = 'third_party_image_api_edit' if use_third_party_api else ('chatgpt_pool_edit' if use_chatgpt_pool else 'codex_edit')
        task_provider = 'third_party_image_api' if use_third_party_api else ('chatgpt_pool' if use_chatgpt_pool else 'codex')
        _merge_task_params(task_id, {
            'archive_enabled': archive_enabled,
            'telegram_enabled': telegram_enabled,
        })
        run_id = _start_generation_audit(
            task_id,
            task_kind,
            prompt,
            (get_task(task_id) or {}).get('params') or {},
            provider=task_provider,
            route=task_route,
            stage='preparing',
        )
        print(f"✏️ 开始处理 GPT 编辑任务：{task_id}（参考图 {source_count} 张）")

        send_status_notification(task_id, '已提交 GPT 图片编辑任务，请等待...', '✅')
        update_task_status(task_id, 'preparing', '正在准备 GPT 编辑...')
        provider_timeout_seconds = _coerce_gpt_provider_total_timeout(None)
        if codex_unavailable_error:
            _append_task_route_trace(task_id, 'codex_edit', 'skipped', codex_unavailable_error)
            if not use_chatgpt_pool:
                raise RuntimeError(codex_unavailable_error)
        if use_third_party_api:
            route_started = time.monotonic()
            update_task_status(task_id, 'processing', '正在调用第三方图片编辑 API...', stage='calling_third_party_image_api')
            send_status_notification(task_id, '编辑中... 正在调用第三方图片 API...', '🧩')
            _append_task_route_trace(task_id, 'third_party_image_api_edit', 'started', '正在调用第三方图片编辑 API')
            _record_generation_event(task_id, 'provider_call_started', '开始调用第三方图片编辑 API', stage='calling_third_party_image_api', payload={'provider': 'third_party_image_api', 'route': 'third_party_image_api_edit'})
            result = edit_image_third_party(
                prompt,
                images,
                ratio=ratio,
                resolution=resolution,
                quality=quality,
                moderation=moderation,
                mask=mask,
                progress_callback=_make_third_party_download_progress_callback(task_id),
            )
            result['fallback_source'] = 'third_party_image_api'
            result['gpt_provider_route'] = 'third_party_image_api'
            _append_task_route_trace(
                task_id,
                'third_party_image_api_edit',
                'succeeded',
                '第三方图片编辑 API 成功返回',
                elapsed_seconds=int(time.monotonic() - route_started),
            )
        elif use_chatgpt_pool:
            route_started = time.monotonic()
            update_task_status(task_id, 'processing', '正在调用 ChatGPT 账号池图片编辑 API...', stage='calling_chatgpt_pool_edit')
            send_status_notification(task_id, '编辑中... 正在调用 ChatGPT 账号池 API...', '🛟')
            _append_task_route_trace(task_id, 'chatgpt_pool_edit', 'started', '正在调用 ChatGPT 账号池图片编辑 API', timeout_seconds=provider_timeout_seconds)
            _record_generation_event(task_id, 'provider_call_started', '开始调用 ChatGPT 账号池图片编辑 API', stage='calling_chatgpt_pool_edit', payload={'provider': 'chatgpt_pool', 'route': 'chatgpt_pool_edit'})
            result = edit_image_gpt_pool(
                prompt,
                images,
                ratio=ratio,
                resolution=resolution,
                quality=quality,
                moderation=moderation,
                mask=mask,
                prompt_mode=prompt_mode,
                main_model=main_model,
            )
            if not result.get('success'):
                provider_error = result.get('error', 'ChatGPT 账号池图片编辑 API 失败')
                _append_task_route_trace(
                    task_id,
                    'chatgpt_pool_edit',
                    'failed',
                    provider_error,
                    elapsed_seconds=int(time.monotonic() - route_started),
                )
                raise RuntimeError(_format_gpt_pool_error(provider_error))
            result['fallback_source'] = 'chatgpt_pool'
            result['gpt_provider_route'] = 'chatgpt_pool'
            _append_task_route_trace(
                task_id,
                'chatgpt_pool_edit',
                'succeeded',
                'ChatGPT 账号池图片编辑 API 成功返回',
                elapsed_seconds=int(time.monotonic() - route_started),
            )
        else:
            provider_env, codex_auth_source = _resolve_codex_provider_env()
            provider_label = 'Codex 编辑 provider'
            trace_route = 'codex_edit'
            update_task_status(task_id, 'processing', f'正在调用{provider_label}...', stage='calling_gpt_edit')
            send_status_notification(task_id, f'编辑中... 正在调用{provider_label}...', '🤖')
            _append_task_route_trace(task_id, trace_route, 'started', f'正在调用{provider_label}', timeout_seconds=provider_timeout_seconds)
            _record_generation_event(task_id, 'provider_call_started', '开始调用 Codex 编辑 provider', stage='calling_gpt_edit', payload={'provider': 'codex', 'route': 'codex_edit'})

            try:
                result = edit_image_gpt_codex(
                    prompt,
                    images,
                    ratio=ratio,
                    resolution=resolution,
                    quality=quality,
                    moderation=moderation,
                    mask=mask,
                    prompt_mode=prompt_mode,
                    main_model=main_model,
                    reasoning_effort=reasoning_effort,
                    total_timeout_seconds=provider_timeout_seconds,
                    on_provider_wait=_make_gpt_provider_wait_callback(task_id),
                    provider_env=provider_env,
                )
            except Exception as provider_exc:
                _append_task_route_trace(task_id, trace_route, 'failed', str(provider_exc))
                raise
            if not result.get('success'):
                provider_error = result.get('error', f'{provider_label} 失败')
                _append_task_route_trace(task_id, trace_route, 'failed', provider_error)
                raise RuntimeError(_format_gpt_provider_error(provider_error))
            result['codex_auth_source'] = codex_auth_source
        _annotate_gpt_route_result(
            result,
            model_resolution,
            requested_route=gpt_provider_route,
            requested_model=requested_main_model,
            requested_reasoning_effort=requested_reasoning_effort,
        )
        if _is_task_canceled(task_id):
            _finish_canceled_gpt_task(task_id, result)
            return
        if not use_third_party_api and not use_chatgpt_pool:
            _append_task_route_trace(task_id, trace_route, 'succeeded', f'{provider_label} 成功返回')

        resolution_meta = _augment_result_resolution_metadata(result, resolution)
        delivery_resolution = resolution_meta.get('effective_resolution') or result.get('effective_resolution') or resolution
        telegram_success = False
        if telegram_enabled:
            update_task_status(task_id, 'processing', '正在发送到 Telegram...', stage='sending_telegram')
            send_status_notification(task_id, '编辑中... 正在发送图片...', '📤')
            _record_generation_event(task_id, 'telegram_send_started', '开始发送 GPT 编辑结果到 Telegram', stage='sending_telegram')
            if _is_task_canceled(task_id):
                _finish_canceled_gpt_task(task_id, result)
                return

            telegram_success = send_telegram_result(
                result['image_path'],
                prompt,
                ratio,
                delivery_resolution,
                image_paths=result.get('image_paths'),
            )
        else:
            update_task_status(task_id, 'processing', 'Telegram 已关闭，正在整理结果...', stage='saving')
            _record_generation_event(task_id, 'telegram_send_skipped', '已按节点开关跳过 Telegram', stage='saving')

        result_files = _result_image_filenames(result)
        _merge_task_params(task_id, {
            'prompt_mode': result.get('prompt_mode') or prompt_mode,
            'gpt_provider_route': result.get('gpt_provider_route') or ('third_party_image_api' if use_third_party_api else gpt_provider_route),
            'use_third_party_api': use_third_party_api,
            'third_party_api': bool(result.get('third_party_api')),
            'requested_resolution': result.get('requested_resolution') or resolution,
            'actual_resolution': result.get('actual_resolution'),
            'actual_resolutions': result.get('actual_resolutions'),
            'effective_resolution': result.get('effective_resolution'),
            'resolution_mismatch': result.get('resolution_mismatch'),
            'requested_size': result.get('requested_size'),
            'actual_width': result.get('actual_width'),
            'actual_height': result.get('actual_height'),
            'actual_size': result.get('actual_size'),
            'actual_megapixels': result.get('actual_megapixels'),
            'main_model': result.get('main_model') or main_model,
            'requested_main_model': result.get('requested_main_model') or requested_main_model,
            'model_fallback_from': result.get('model_fallback_from'),
            'requested_gpt_provider_route': result.get('requested_gpt_provider_route') or gpt_provider_route,
            'reasoning_effort': result.get('reasoning_effort') or reasoning_effort,
            'requested_reasoning_effort': result.get('requested_reasoning_effort') or requested_reasoning_effort,
            'reasoning_fallback_from': result.get('reasoning_fallback_from'),
            'model_role': result.get('model_role'),
            'model_catalog_source': result.get('model_catalog_source'),
            'image_engine': result.get('image_engine'),
            'image_engine_label': result.get('image_engine_label'),
            'provider_total_timeout_seconds': provider_timeout_seconds,
            'codex_auth_source': result.get('codex_auth_source'),
            'revised_prompt': result.get('revised_prompt'),
            'revised_prompts': result.get('revised_prompts'),
            'actual_sizes': result.get('actual_sizes'),
            'archive_enabled': archive_enabled,
            'telegram_enabled': telegram_enabled,
        })
        image_count = len(result_files) or len(result.get('image_paths') or [result.get('image_path')])
        filename = result_files[0] if result_files else os.path.basename(result['image_path'])
        if telegram_success or not telegram_enabled:
            if not telegram_enabled:
                progress_text = 'GPT 图片编辑成功，已按节点开关跳过 Telegram'
            else:
                progress_text = f'GPT 图片编辑成功（共 {image_count} 张）' if image_count > 1 else 'GPT 图片编辑成功'
            _finalize_generation_task(
                task_id,
                'succeeded',
                run_id=run_id,
                provider=task_provider,
                route=task_route,
                task_type=task_kind,
                result_file=filename,
                progress_text=progress_text,
                result_files=result_files,
                image_count=image_count,
            )
            _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload={'provider': task_provider, 'route': task_route, 'image_count': image_count, 'telegram_enabled': telegram_enabled})
            send_status_notification(task_id, '✅ GPT 图片编辑成功！', '🎉')
            print(f"✅ GPT 编辑任务成功：{task_id}")
        else:
            progress_text = 'GPT 图片编辑已完成，但 Telegram 发送失败'
            _finalize_generation_task(
                task_id,
                'succeeded_no_telegram',
                run_id=run_id,
                provider=task_provider,
                route=task_route,
                task_type=task_kind,
                result_file=filename,
                progress_text=progress_text,
                result_files=result_files,
                image_count=image_count,
            )
            _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload={'provider': task_provider, 'route': task_route, 'image_count': image_count})
            print(f"⚠️ GPT 编辑任务完成但未发送 Telegram: {task_id}")

    except Exception as e:
        raw_error_msg = str(e)
        error_type = type(e).__name__
        error_info = _translate_generation_failure(
            task_id,
            raw_error_msg,
            provider=task_provider,
            route=task_route,
            task_type=task_kind,
            stage='failed',
            exception_name=error_type,
        )
        error_msg = error_info.get('display_error') or _format_gpt_failure_error(raw_error_msg)
        print(f"❌ GPT 编辑任务失败：{task_id} - {raw_error_msg}")
        if error_msg != raw_error_msg:
            print(f"↪️ 用户可见错误：{error_msg}")
        _finalize_generation_task(task_id, 'failed', run_id=run_id, stage='failed', progress_text=error_msg, error_info=error_info, error_type=error_type, provider=task_provider, route=task_route, task_type=task_kind)
        send_status_notification(task_id, f'❌ GPT 编辑失败：{error_msg[:100]}', '⚠️')

def process_custom_task(task_id, prompt, ratio, resolution, quality='auto', moderation='auto'):
    """兼容 custom 路由，复用 GPT provider + fallback 流程。"""
    return process_gpt_task(task_id, prompt, ratio, resolution, quality, moderation=moderation)


def run_server():
    """启动服务器"""
    _validate_public_mode_password(server_config=SERVER_CONFIG)
    # 初始化数据库
    init_db()
    print("✅ 数据库初始化完成")
    stale_count = fail_stale_processing_tasks(max_age_seconds=0)
    if stale_count:
        print(f"⚠️ 已标记 {stale_count} 个重启后遗留的生成任务为失败")
    _init_generation_semaphore()
    init_layout_draft_store()
    print("✅ 排版草稿库初始化完成")
    init_asset_store()
    print("✅ 图库资产索引初始化完成")
    init_prompt_source_store()
    orphan_prompt_runs = cancel_orphan_prompt_source_runs()
    if orphan_prompt_runs:
        print(f"⚠️ 已标记 {orphan_prompt_runs} 个重启后遗留的远程源同步任务为停止")
    init_prompt_library_store(legacy_style_presets_file=STYLE_PRESETS_FILE)
    print(f"✅ 提示词素材库初始化完成：{APP_DATA_DIR / 'prompt_library.db'}")
    _ensure_db_file_permissions()
    SOURCE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"✅ 远程源素材库初始化完成：{SOURCE_IMAGE_DIR}")
    
    class ThreadingHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        allow_reuse_address = True
        allow_reuse_port = False
        daemon_threads = True

    # 启动服务器
    with ThreadingHTTPServer((SERVER_HOST, PORT), RequestHandler) as httpd:
        print(f"🚀 服务器启动在 http://{SERVER_HOST}:{PORT}")
        print(f"🔐 公网模式：{'开启' if SERVER_CONFIG.get('public_mode') else '关闭'}")
        print(f"📝 日志输出到 stdout")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n👋 服务器关闭")

if __name__ == '__main__':
    run_server()
