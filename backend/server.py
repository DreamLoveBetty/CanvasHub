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
import gzip
import json
import time
import random
import math
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
from functools import partial
import ipaddress
import re
import copy
import queue
import io
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
    get_comfy_config,
    get_cyimg_config,
    get_managed_codex_oauth_public_config,
    get_allowed_cors_origins,
    get_max_concurrent_tasks,
    get_proxy_config,
    get_prompt_skill_config,
    get_pinterest_config,
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
    get_video_inference_config,
    get_video_inference_public_config,
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
from .services.google_pool import GooglePoolClient
from .provider_google_pool import GooglePoolProvider
from .routes.google_pool_routes import create_router as create_google_pool_router
from .audio.runtime import Runtime as AudioRuntime
from .video_control.service import VideoControlService
from .video_control.runtime import Runtime as VideoControlRuntime
from .routes.video_control_routes import create_router as create_video_control_router
from .routes.cyimg_routes import create_router as create_cyimg_router
from .services.cyimg_generation import CyimgService
from .krea2.runtime import Runtime as Krea2Runtime
from .krea2.service import Service as Krea2Service
from .routes.krea2_routes import create_router as create_krea2_router
from .qwen21.runtime import Runtime as Qwen21Runtime
from .qwen21.service import Service as Qwen21Service
from .routes.qwen21_routes import create_router as create_qwen21_router
from .qwen21.profiles import ADAPTERS as QWEN21_MANAGED_ADAPTERS
from .lora_library.service import Service as LoRALibraryService
from .lora_library.civitai import Civitai as CivitaiMetadataProvider
from .routes.lora_library_routes import create_router as create_lora_library_router
from .runtime_resources import IdleWorkerCoordinator
from .topaz_video.service import TopazVideoService
from .topaz_video.runtime import TopazVideoRuntime
from .routes.topaz_video_routes import create_router as create_topaz_video_router
from .audio.service import AudioService
from .routes.audio_routes import create_router as create_audio_router
from .api_client_gpt import send_telegram_result, send_tg_document
from .provider_gpt_codex import generate_image_gpt_codex, edit_image_gpt_codex, get_gpt_provider_auth_status
from .provider_chatgpt_pool import chat_chatgpt_pool, edit_image_gpt_pool, generate_editable_file_gpt_pool, generate_image_gpt_pool, search_chatgpt_pool
from .provider_third_party_image import generate_image_third_party, edit_image_third_party
from .provider_psd import generate_editable_psd_native
from .frontend_assets import load_frontend_assets
from .routes.asset_delete_routes import (
    handle_asset_delete as _handle_asset_delete,
    handle_asset_delete_batch as _handle_asset_delete_batch,
    handle_asset_undo_delete as _handle_asset_undo_delete,
)
from .routes.asset_meta_routes import handle_asset_meta as _handle_asset_meta
from .routes.asset_routes import (
    handle_asset_detail as _handle_asset_detail,
    handle_asset_health as _handle_asset_health,
    handle_assets as _handle_assets,
)
from .routes.asset_set_routes import (
    handle_asset_set_delete as _handle_asset_set_delete,
    handle_asset_set_post as _handle_asset_set_post,
    handle_asset_sets as _handle_asset_sets,
)
from .routes.base import ProtectedRouter
from .routes.history_routes import handle_history as _handle_history
from .routes.task_routes import (
    handle_generation_events as _handle_generation_events,
    handle_generation_runs as _handle_generation_runs,
    handle_status as _handle_status,
)
from .routes.editable_routes import (
    handle_editable_file as _handle_editable_file,
    handle_editable_file_delete as _handle_editable_file_delete,
    handle_editable_file_send as _handle_editable_file_send,
    handle_editable_files as _handle_editable_files,
)
from .services.asset_delete import delete_gallery_assets as _delete_gallery_assets_service
from .services.asset_health import collect_asset_health as _collect_asset_health_service
from .services.history_format import format_history_task as _serialize_history_task
from .services.history_policy import (
    dedupe_key as _policy_dedupe_key,
    page_int as _policy_page_int,
    task_result_files as _policy_task_result_files,
    task_should_render as _policy_task_should_render,
    task_timestamp as _policy_task_timestamp,
)
from .services.history_query import (
    collect_renderable_history_tasks as _query_renderable_history_tasks,
    load_database_history_tasks as _query_database_history_tasks,
    load_legacy_history_tasks as _query_legacy_history_tasks,
)
from .services.layout_publish import publish_layout_draft as _publish_layout_draft
from .routes.layout_routes import (
    handle_layout_draft_get as _handle_layout_draft_get,
    handle_layout_draft_list as _handle_layout_draft_list,
    handle_layout_draft_post as _handle_layout_draft_post,
    handle_layout_font_file as _handle_layout_font_file,
    handle_layout_fonts as _handle_layout_fonts,
)
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
    analyze_prompt_video,
    assistant_chat,
    assistant_chat_stream,
    discover_prompt_models,
    extract_reusable_prompt_blocks,
    extract_reusable_prompt_blocks_from_image,
    extract_style_preset,
    generic_19_prompt_block_split_rule,
    list_prompt_providers,
    polish_prompt,
    safe_rewrite_prompt,
)
from .h3_prompt_compiler import H3PromptCompileError, compile_h3_prompt
from .storage_paths import IMAGE_ARCHIVE_DIR, SOURCE_IMAGE_DIR, archive_scan_roots, daily_output_dir, image_lookup_roots, source_image_roots, write_obsidian_prompt_sidecar
from .upscale_runtime import (
    UpscaleRuntimeError,
    default_upscale_model_dir,
)
from .topaz.runtime import Runtime as TopazRuntime
from .topaz import routes as topaz_routes, service as topaz_service
from .services.upscale_backends import (
    MODELS as UPSCALE_MODELS, normalize_model as normalize_upscale_model,
    available_models as _available_upscale_models, execute as _execute_upscale,
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
    invalidate_asset_index_cache,
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
    ColorSchemeNotFoundError,
    delete_color_scheme,
    delete_prompt_block,
    delete_prompt_template,
    init_prompt_library_store,
    list_color_schemes,
    list_prompt_blocks,
    list_prompt_templates,
    mark_prompt_block_used,
    migrate_legacy_color_schemes,
    resolve_prompt_template,
    save_color_scheme,
    save_prompt_block,
    save_prompt_template,
    set_color_scheme_favorite,
)
from .pinterest_auth import (
    browser_login_capability as get_pinterest_browser_login_capability,
    cancel_browser_login as cancel_pinterest_browser_login,
    complete_browser_login as complete_pinterest_browser_login,
    delete_saved_auth as delete_pinterest_auth,
    ensure_pinterest_auth_storage,
    import_cookie_header as import_pinterest_cookie_header,
    start_browser_login as start_pinterest_browser_login,
    verify_saved_auth as verify_pinterest_saved_auth,
)
from .pinterest_gallery import get_pinterest_library, get_pinterest_sync_status
from .pinterest_storage import (
    download_pinterest_pin,
    get_pinterest_board_download,
    save_pinterest_pin_prompt,
    start_pinterest_board_sync,
)
from .thumb_cache import (
    THUMB_MAX_SIDE,
    ensure_video_webp_thumbnail,
    ensure_webp_thumbnail,
    parse_thumb_request,
    resolve_media_path,
    thumb_url_for_media_url,
)
from .pose_service import pose_assets_status
from .app_updates import get_app_update_status
from .agent_store import init_agent_store
from .agent_runtime import (
    AgentRunConflict,
    AgentRunNotFound,
    AgentRuntimeError,
    get_agent_runtime,
)
from .video_runtime import (
    cancel_runtime_job as cancel_video_runtime_job,
    collect_component_status as collect_video_runtime_component_status,
    collect_runtime_capabilities as collect_video_runtime_capabilities,
    collect_runtime_status as collect_video_runtime_status,
    collect_supervisor_status as collect_video_supervisor_status,
    download_runtime_result as download_video_runtime_result,
    get_runtime_job as get_video_runtime_job,
    normalize_runtime_base_url,
    normalize_supervisor_base_url,
    start_local_runtime as start_local_video_runtime,
    submit_runtime_job as submit_video_runtime_job,
)

from .services import asset_files as _domain_services_asset_files
from .routes import asset_maintenance_routes as _domain_routes_asset_maintenance_routes

from .services import media_lookup as _domain_services_media_lookup
from .services import archive_sidecars as _domain_services_archive_sidecars
from .services import archive_video as _domain_services_archive_video
from .services import image_import as _domain_services_image_import
from .routes import media_routes as _domain_routes_media_routes

from .services import auth_policy as _domain_services_auth_policy
from .services import system_settings as _domain_services_system_settings
from .routes import system_routes as _domain_routes_system_routes
from .routes import auth_routes as _domain_routes_auth_routes

from .services import provider_accounts as _domain_services_provider_accounts
from .routes import provider_account_routes as _domain_routes_provider_account_routes

from .services import prompt_presets as _domain_services_prompt_presets
from .services import prompt_enrichment as _domain_services_prompt_enrichment
from .routes import prompt_routes as _domain_routes_prompt_routes

from .routes import remote_source_routes as _domain_routes_remote_source_routes
from .routes import agent_routes as _domain_routes_agent_routes

from .services import task_tracking as _domain_services_task_tracking
from .routes import task_control_routes as _domain_routes_task_control_routes

from .services import task_retry as _domain_services_task_retry
from .services import task_batch as _domain_services_task_batch
from .services import task_execution as _domain_services_task_execution

from .services import generation_policy as _domain_services_generation_policy
from .services import provider_errors as _domain_services_provider_errors
from .services import provider_routing as _domain_services_provider_routing
from .services import generation_progress as _domain_services_generation_progress

from .services import gpt_generation as _domain_services_gpt_generation
from .services import editable_generation as _domain_services_editable_generation
from .routes import gpt_generation_routes as _domain_routes_gpt_generation_routes

from .services import google_generation as _domain_services_google_generation
from .services import telegram_notifications as _domain_services_telegram_notifications
from .routes import google_generation_routes as _domain_routes_google_generation_routes

from .services import upscale_generation as _domain_services_upscale_generation
from .services import video_generation as _domain_services_video_generation
from .services import comfy_workflows as _domain_services_comfy_workflows
from .services import comfy_gateway as _domain_services_comfy_gateway
from .services import comfy_generation as _domain_services_comfy_generation
from .services import comfy_transport as _domain_services_comfy_transport
from .routes import runtime_generation_routes as _domain_routes_runtime_generation_routes

from .routes import http_responses as _domain_routes_http_responses
from .services import server_lifecycle as _domain_services_server_lifecycle

SERVER_CONFIG = get_server_config()
SERVER_HOST = SERVER_CONFIG["host"]
PORT = SERVER_CONFIG["port"]
PROJECT_ROOT = BASE_DIR
BACKEND_ROOT = Path(__file__).resolve().parent
FRONTEND_ROOT, FRONTEND_STATIC_ROOT, IMMUTABLE_FRONTEND_PATHS = load_frontend_assets(PROJECT_ROOT)
DIRECTORY = str(APP_DATA_DIR)
PROMPT_DATA_DIR = APP_DATA_DIR / 'data'
STYLE_PRESETS_FILE = PROMPT_DATA_DIR / 'style_presets.json'
PROMPT_VERSIONS_FILE = PROMPT_DATA_DIR / 'prompt_versions.json'
MAX_GPT_IMAGE_COUNT = 8


def _coerce_gpt_image_count(data, prompt=''):
    """Accept frontend count aliases, with a light prompt fallback."""
    return _domain_services_generation_policy._coerce_gpt_image_count(data, prompt, MAX_GPT_IMAGE_COUNT=MAX_GPT_IMAGE_COUNT, re=re)


def _coerce_gpt_quality(value):
    return _domain_services_generation_policy._coerce_gpt_quality(value)


def _coerce_gpt_moderation(value):
    return _domain_services_generation_policy._coerce_gpt_moderation(value)


def _coerce_prompt_mode(value):
    return _domain_services_generation_policy._coerce_prompt_mode(value)


GENERIC_19_FIDELITY_MARKER = '【同图忠实复现｜高保真模块】'
GENERIC_19_LEGACY_FIDELITY_MARKERS = ('【同图忠实复现｜19模块】',)


def _is_generic_19_fidelity_prompt(prompt):
    return _domain_services_generation_policy._is_generic_19_fidelity_prompt(
        prompt, GENERIC_19_FIDELITY_MARKER=GENERIC_19_FIDELITY_MARKER, GENERIC_19_LEGACY_FIDELITY_MARKERS=GENERIC_19_LEGACY_FIDELITY_MARKERS,
    )


def _effective_prompt_mode(prompt, value):
    return _domain_services_generation_policy._effective_prompt_mode(
        prompt, value, _coerce_prompt_mode=_coerce_prompt_mode,
        _is_generic_19_fidelity_prompt=_is_generic_19_fidelity_prompt,
    )


def _coerce_gpt_task_type(value):
    return _domain_services_generation_policy._coerce_gpt_task_type(value)


def _coerce_bool(value, default=True):
    return _domain_services_generation_policy._coerce_bool(value, default)


def _coerce_use_third_party_api(*values):
    return _domain_services_generation_policy._coerce_use_third_party_api(*values, _coerce_bool=_coerce_bool)


def _coerce_gpt_provider_route(value):
    return _domain_services_generation_policy._coerce_gpt_provider_route(value)


def _gpt_route_uses_third_party(route):
    return _domain_services_generation_policy._gpt_route_uses_third_party(route, _coerce_gpt_provider_route=_coerce_gpt_provider_route)


def _resolve_codex_provider_env() -> tuple[dict | None, str]:
    """Prefer project-managed Codex OAuth, then fall back to local Codex auth."""
    return _domain_services_generation_policy._resolve_codex_provider_env(
        get_managed_codex_oauth_status=get_managed_codex_oauth_status, get_managed_codex_provider_env=get_managed_codex_provider_env,
    )


VALID_GPT_MAIN_MODELS = set(GPT_IMAGE_MAIN_MODELS)
VALID_GPT_REASONING_EFFORTS = set(GPT_REASONING_EFFORTS)
VALID_GPT_TRANSPORT_MODES = set(GPT_TRANSPORT_MODES)


def _coerce_gpt_main_model(value):
    return _domain_services_generation_policy._coerce_gpt_main_model(
        value, DEFAULT_GPT_IMAGE_MAIN_MODEL=DEFAULT_GPT_IMAGE_MAIN_MODEL, get_gpt_provider_config=get_gpt_provider_config,
        normalize_model_id=normalize_model_id,
    )


def _coerce_gpt_reasoning_effort(value):
    return _domain_services_generation_policy._coerce_gpt_reasoning_effort(
        value, DEFAULT_GPT_REASONING_EFFORT=DEFAULT_GPT_REASONING_EFFORT, VALID_GPT_REASONING_EFFORTS=VALID_GPT_REASONING_EFFORTS,
        get_gpt_provider_config=get_gpt_provider_config,
    )


def _coerce_gpt_transport_mode(value):
    return _domain_services_generation_policy._coerce_gpt_transport_mode(
        value, DEFAULT_GPT_TRANSPORT_MODE=DEFAULT_GPT_TRANSPORT_MODE, VALID_GPT_TRANSPORT_MODES=VALID_GPT_TRANSPORT_MODES,
        get_gpt_provider_config=get_gpt_provider_config,
    )


def _coerce_gpt_provider_total_timeout(value):
    return _domain_services_generation_policy._coerce_gpt_provider_total_timeout(
        value, DEFAULT_GPT_PROVIDER_TOTAL_TIMEOUT_SECONDS=DEFAULT_GPT_PROVIDER_TOTAL_TIMEOUT_SECONDS, get_gpt_provider_config=get_gpt_provider_config,
    )


def _merge_task_params(task_id, patch):
    return _domain_services_task_tracking._merge_task_params(task_id, patch, get_task=get_task, json=json, update_task_fields=update_task_fields)


def _append_task_route_trace(task_id, route, status, message='', **extra):
    return _domain_services_task_tracking._append_task_route_trace(
        task_id, route, status,
        message, extra=extra, _classify_route_error=_classify_route_error,
        _record_generation_event=_record_generation_event, get_task=get_task, json=json,
        time=time, update_task_fields=update_task_fields,
    )


def _classify_route_error(route, message=''):
    """Coarse failure labels for route trace UI; never include secrets."""
    return _domain_services_task_tracking._classify_route_error(route, message)


def _generation_run_task(task_id):
    return _domain_services_task_tracking._generation_run_task(task_id, get_task=get_task)


def _generation_last_run_id(task_id):
    return _domain_services_task_tracking._generation_last_run_id(task_id, _generation_run_task=_generation_run_task)


def _record_generation_event(task_id, event_type, message='', stage='', severity='info', payload=None):
    return _domain_services_task_tracking._record_generation_event(
        task_id, event_type, message,
        stage, severity, payload,
        _generation_last_run_id=_generation_last_run_id, record_generation_event=record_generation_event,
    )


def _generation_run_route(task_id, fallback=''):
    return _domain_services_task_tracking._generation_run_route(task_id, fallback, _generation_run_task=_generation_run_task)


def _start_generation_audit(task_id, task_type, prompt, params, *, provider='', route='', stage='preparing', parent_run_id=''):
    return _domain_services_task_tracking._start_generation_audit(
        task_id, task_type, prompt,
        params, provider=provider, route=route,
        stage=stage, parent_run_id=parent_run_id, _record_generation_event=_record_generation_event,
        start_generation_run=start_generation_run,
    )


def _translate_generation_failure(task_id, raw_error, *, provider='', route='', task_type='', stage='', exception_name=''):
    return _domain_services_task_tracking._translate_generation_failure(
        task_id, raw_error, provider=provider,
        route=route, task_type=task_type, stage=stage,
        exception_name=exception_name, _record_generation_event=_record_generation_event, translate_generation_error=translate_generation_error,
    )


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
    return _domain_services_task_tracking._finalize_generation_task(
        task_id, status, run_id=run_id,
        stage=stage, progress_text=progress_text, result_file=result_file,
        result_files=result_files, image_count=image_count, error_info=error_info,
        error_type=error_type, provider=provider, route=route,
        task_type=task_type, extra=extra, finish_generation_run=finish_generation_run,
        json=json, update_task=update_task,
    )


def _status_response_task(task):
    task = _domain_services_task_tracking._status_response_task(
        task, H3_VIDEO_TASK_TYPE=H3_VIDEO_TASK_TYPE, _history_task_result_files=_history_task_result_files,
        _public_h3_task_params=_public_h3_task_params, safe_basename=safe_basename, urllib=urllib,
    )
    task.setdefault('progress', 100 if task.get('status') in ('succeeded', 'success', 'failed', 'telegram_failed', 'canceled') else 0)
    return task


VALID_IMAGE_RATIOS = {
    '1:1', '2:3', '3:2', '3:4', '4:3', '4:5', '5:4',
    '9:16', '16:9', '9:21', '21:9'
}


def _coerce_image_ratio(value, default='1:1'):
    return _domain_services_generation_policy._coerce_image_ratio(value, default, VALID_IMAGE_RATIOS=VALID_IMAGE_RATIOS)


def _effective_image_ratio(prompt, value, default='1:1'):
    """Honor the source ratio embedded by a complete generic_19 bundle."""
    return _domain_services_generation_policy._effective_image_ratio(
        prompt, value, default,
        VALID_IMAGE_RATIOS=VALID_IMAGE_RATIOS, _coerce_image_ratio=_coerce_image_ratio, _is_generic_19_fidelity_prompt=_is_generic_19_fidelity_prompt,
        re=re,
    )


def _coerce_gpt_resolution(value):
    return _domain_services_generation_policy._coerce_gpt_resolution(value)


def _result_path_dimensions(path_value):
    return _domain_services_generation_policy._result_path_dimensions(path_value, Image=Image, PROJECT_ROOT=PROJECT_ROOT, Path=Path)


def _result_actual_sizes(result):
    return _domain_services_generation_policy._result_actual_sizes(
        result, _result_path_dimensions=_result_path_dimensions, normalize_actual_sizes=normalize_actual_sizes,
    )


def _augment_result_resolution_metadata(result, requested_resolution):
    return _domain_services_generation_policy._augment_result_resolution_metadata(
        result, requested_resolution, _result_actual_sizes=_result_actual_sizes,
        build_resolution_metadata=build_resolution_metadata,
    )


def _coerce_google_quality(value, default='2k'):
    return _domain_services_generation_policy._coerce_google_quality(value, default)


def _coerce_google_edit_quality(value):
    return _domain_services_generation_policy._coerce_google_edit_quality(value)


DEFAULT_GOOGLE_IMAGE_MODEL = 'gemini-3.1-flash-image'
DEFAULT_GOOGLE_MAX_TOKENS = 4096


def _coerce_model(value, default=DEFAULT_GOOGLE_IMAGE_MODEL):
    return _domain_services_generation_policy._coerce_model(value, default)


def _coerce_google_max_tokens(value, default=DEFAULT_GOOGLE_MAX_TOKENS):
    return _domain_services_generation_policy._coerce_google_max_tokens(value, default)


def _coerce_google_temperature(value):
    return _domain_services_generation_policy._coerce_google_temperature(value)


def _coerce_google_output_controls(params):
    return _domain_services_generation_policy._coerce_google_output_controls(params, _coerce_bool=_coerce_bool)


def _short_text(value, limit=500):
    return _domain_services_generation_policy._short_text(value, limit)


def _stable_lineage_url(value):
    return _domain_services_generation_policy._stable_lineage_url(value)


def _normalize_lineage_reference(item, index=0):
    return _domain_services_generation_policy._normalize_lineage_reference(item, index, _short_text=_short_text, _stable_lineage_url=_stable_lineage_url)


def _extract_lineage_payload(data):
    return _domain_services_generation_policy._extract_lineage_payload(data, _normalize_lineage_reference=_normalize_lineage_reference)


def _attach_lineage_params(params, data):
    return _domain_services_generation_policy._attach_lineage_params(params, data, _extract_lineage_payload=_extract_lineage_payload)


def _format_gpt_provider_error(error):
    """Turn common local provider failures into user-readable status text."""
    return _domain_services_provider_errors._format_gpt_provider_error(error, re=re, time=time)


def _first_user_error_line(error):
    return _domain_services_provider_errors._first_user_error_line(error, re=re)


def _format_gpt_pool_error(error):
    """Turn account-pool sidecar failures into user-readable status text."""
    return _domain_services_provider_errors._format_gpt_pool_error(error, _first_user_error_line=_first_user_error_line, datetime=datetime, re=re)


class ChatgptPoolGenerationError(RuntimeError):
    def __init__(self, message, provider_result):
        super().__init__(message)
        self.provider_result = dict(provider_result) if isinstance(provider_result, dict) else {}


def _chatgpt_pool_failure_metadata(error):
    return _domain_services_provider_errors._chatgpt_pool_failure_metadata(error)


def _prepare_chatgpt_pool_generation_prompt(task_id, prompt, prompt_mode):
    """Use the configured prompt skill before Web-conversation image generation."""
    return _domain_services_prompt_enrichment._prepare_chatgpt_pool_generation_prompt(
        task_id, prompt, prompt_mode,
        _coerce_prompt_mode=_coerce_prompt_mode, _is_generic_19_fidelity_prompt=_is_generic_19_fidelity_prompt, _prepare_chatgpt_pool_generation_prompt_with_chat=_prepare_chatgpt_pool_generation_prompt_with_chat,
        get_prompt_skill_config=get_prompt_skill_config, polish_prompt=polish_prompt, update_task_status=update_task_status,
    )


def _extract_json_object_from_text(text):
    return _domain_services_prompt_enrichment._extract_json_object_from_text(text, json=json, re=re)


def _chatgpt_pool_chat_content(result):
    return _domain_services_prompt_enrichment._chatgpt_pool_chat_content(result)


def _prompt_polish_chat_messages(original):
    return _domain_services_prompt_enrichment._prompt_polish_chat_messages(original)


def _polish_prompt_with_chatgpt_pool_chat(prompt, polish_error):
    return _domain_services_prompt_enrichment._polish_prompt_with_chatgpt_pool_chat(
        prompt, polish_error, _chatgpt_pool_chat_content=_chatgpt_pool_chat_content,
        _extract_json_object_from_text=_extract_json_object_from_text, _prompt_polish_chat_messages=_prompt_polish_chat_messages, chat_chatgpt_pool=chat_chatgpt_pool,
        time=time,
    )


def _prepare_chatgpt_pool_generation_prompt_with_chat(task_id, prompt, polish_error):
    return _domain_services_prompt_enrichment._prepare_chatgpt_pool_generation_prompt_with_chat(
        task_id, prompt, polish_error,
        _polish_prompt_with_chatgpt_pool_chat=_polish_prompt_with_chatgpt_pool_chat, get_prompt_skill_config=get_prompt_skill_config, update_task_status=update_task_status,
    )


def _source_summary_list(sources, limit=5):
    return _domain_services_prompt_enrichment._source_summary_list(sources, limit)


def _prepare_web_search_generation_prompt(task_id, prompt):
    return _domain_services_prompt_enrichment._prepare_web_search_generation_prompt(
        task_id, prompt, _append_task_route_trace=_append_task_route_trace,
        _chatgpt_pool_chat_content=_chatgpt_pool_chat_content, _extract_json_object_from_text=_extract_json_object_from_text, _source_summary_list=_source_summary_list,
        chat_chatgpt_pool=chat_chatgpt_pool, get_prompt_skill_config=get_prompt_skill_config, json=json,
        search_chatgpt_pool=search_chatgpt_pool, update_task_status=update_task_status,
    )


def _format_gpt_failure_error(error):
    """Format final GPT task failures without leaking raw stack traces to users."""
    return _domain_services_provider_errors._format_gpt_failure_error(
        error, _first_user_error_line=_first_user_error_line, _format_gpt_pool_error=_format_gpt_pool_error,
        _format_gpt_provider_error=_format_gpt_provider_error, re=re,
    )


def _result_image_filenames(result):
    return _domain_services_generation_policy._result_image_filenames(result, os=os)


def _missing_task_payload(task_id):
    return _domain_services_task_tracking._missing_task_payload(task_id, time=time)


def _history_task_should_render(status, result_files):
    return _policy_task_should_render(status, result_files)


def _history_page_int(raw_value, default, minimum=0, maximum=500):
    return _policy_page_int(raw_value, default, minimum=minimum, maximum=maximum)


def _history_task_result_files(task):
    return _policy_task_result_files(task)


def _history_task_timestamp(task):
    return _policy_task_timestamp(task)


def _history_dedupe_key(task):
    return _policy_dedupe_key(
        task,
        task_result_files=_history_task_result_files,
        task_timestamp=_history_task_timestamp,
        safe_basename=safe_basename,
    )


def _load_database_history_tasks():
    return _query_database_history_tasks(get_all_tasks=get_all_tasks)


def _load_legacy_history_tasks():
    return _query_legacy_history_tasks(directory=DIRECTORY, safe_basename=safe_basename)


def _collect_renderable_history_tasks():
    return _query_renderable_history_tasks(
        load_database_tasks=_load_database_history_tasks,
        load_legacy_tasks=_load_legacy_history_tasks,
        task_timestamp=_history_task_timestamp,
        task_result_files=_history_task_result_files,
        should_render=_history_task_should_render,
        dedupe_key=_history_dedupe_key,
    )


def _format_history_task(task):
    return _serialize_history_task(
        task,
        task_result_files=_history_task_result_files,
        h3_task_type=H3_VIDEO_TASK_TYPE,
        public_h3_params=_public_h3_task_params,
        safe_basename=safe_basename,
    )


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
    return _domain_services_task_retry._retry_task_id_prefix(task_type, params)


def _make_retry_task_id(task_type, params=None):
    return _domain_services_task_retry._make_retry_task_id(task_type, params, _retry_task_id_prefix=_retry_task_id_prefix, random=random, time=time)


def _copy_retry_params(original_task, new_task_id):
    return _domain_services_task_retry._copy_retry_params(
        original_task, new_task_id, RETRY_PARAM_RESULT_KEYS=RETRY_PARAM_RESULT_KEYS,
        copy=copy, time=time,
    )


def _is_gpt_image_retry(task_type, params):
    return _domain_services_task_retry._is_gpt_image_retry(task_type, params)


def _validate_retry_payload(task_type, params):
    return _domain_services_task_retry._validate_retry_payload(task_type, params, TaskRetryError=TaskRetryError, _coerce_gpt_task_type=_coerce_gpt_task_type)


def _start_retry_thread(task_type, task_id, prompt, params):
    return _domain_services_task_retry._start_retry_thread(
        task_type, task_id, prompt,
        params, GenerationQueueFullError=GenerationQueueFullError, TaskRetryError=TaskRetryError,
        _coerce_bool=_coerce_bool, _coerce_gpt_image_count=_coerce_gpt_image_count, _coerce_gpt_main_model=_coerce_gpt_main_model,
        _coerce_gpt_moderation=_coerce_gpt_moderation, _coerce_gpt_provider_route=_coerce_gpt_provider_route, _coerce_gpt_quality=_coerce_gpt_quality,
        _coerce_gpt_reasoning_effort=_coerce_gpt_reasoning_effort, _coerce_gpt_resolution=_coerce_gpt_resolution, _coerce_gpt_task_type=_coerce_gpt_task_type,
        _coerce_image_ratio=_coerce_image_ratio, _coerce_prompt_mode=_coerce_prompt_mode, _coerce_use_third_party_api=_coerce_use_third_party_api,
        _generation_busy_message=_generation_busy_message, _is_gpt_image_retry=_is_gpt_image_retry, _start_generation_thread=_start_generation_thread,
        process_custom_task=process_custom_task, process_gpt_editable_file_task=process_gpt_editable_file_task, process_gpt_task=process_gpt_task,
        process_task=process_task, update_task=update_task,
    )


def retry_failed_task(original_task):
    return _domain_services_task_retry.retry_failed_task(
        original_task, FAILED_RETRY_STATUSES=FAILED_RETRY_STATUSES, RETRYABLE_TASK_TYPES=RETRYABLE_TASK_TYPES,
        TaskRetryError=TaskRetryError, _copy_retry_params=_copy_retry_params, _make_retry_task_id=_make_retry_task_id,
        _start_retry_thread=_start_retry_thread, _validate_retry_payload=_validate_retry_payload, create_task=create_task,
        get_task=get_task,
    )


def _batch_prompt_items(data):
    return _domain_services_task_batch._batch_prompt_items(data, re=re)


def _batch_task_id(provider, params, index):
    return _domain_services_task_batch._batch_task_id(
        provider, params, index,
        _batch_task_type=_batch_task_type, _retry_task_id_prefix=_retry_task_id_prefix, random=random,
        time=time,
    )


def _batch_task_type(provider, params):
    return _domain_services_task_batch._batch_task_type(provider, params, _coerce_gpt_task_type=_coerce_gpt_task_type)


def _make_batch_task_params(provider, incoming_params, prompt, batch_id, index, total, lineage=None):
    return _domain_services_task_batch._make_batch_task_params(
        provider, incoming_params, prompt,
        batch_id, index, total,
        lineage, DEFAULT_GOOGLE_IMAGE_MODEL=DEFAULT_GOOGLE_IMAGE_MODEL, TaskRetryError=TaskRetryError,
        _coerce_bool=_coerce_bool, _coerce_google_max_tokens=_coerce_google_max_tokens, _coerce_google_quality=_coerce_google_quality,
        _coerce_google_temperature=_coerce_google_temperature, _coerce_gpt_image_count=_coerce_gpt_image_count, _coerce_gpt_main_model=_coerce_gpt_main_model,
        _coerce_gpt_moderation=_coerce_gpt_moderation, _coerce_gpt_provider_route=_coerce_gpt_provider_route, _coerce_gpt_quality=_coerce_gpt_quality,
        _coerce_gpt_reasoning_effort=_coerce_gpt_reasoning_effort, _coerce_gpt_resolution=_coerce_gpt_resolution, _coerce_gpt_task_type=_coerce_gpt_task_type,
        _coerce_model=_coerce_model, _coerce_prompt_mode=_coerce_prompt_mode, _coerce_use_third_party_api=_coerce_use_third_party_api,
        _effective_image_ratio=_effective_image_ratio, _gpt_route_uses_third_party=_gpt_route_uses_third_party, time=time,
    )


def _create_batch_tasks(provider, prompts, params, lineage=None):
    return _domain_services_task_batch._create_batch_tasks(
        provider, prompts, params,
        lineage, TaskRetryError=TaskRetryError, _batch_task_id=_batch_task_id,
        _batch_task_type=_batch_task_type, _coerce_gpt_task_type=_coerce_gpt_task_type, _make_batch_task_params=_make_batch_task_params,
        create_task=create_task, random=random, time=time,
    )


def _run_batch_task(task):
    return _domain_services_task_batch._run_batch_task(
        task, _coerce_bool=_coerce_bool, _coerce_gpt_image_count=_coerce_gpt_image_count,
        _coerce_gpt_main_model=_coerce_gpt_main_model, _coerce_gpt_moderation=_coerce_gpt_moderation, _coerce_gpt_provider_route=_coerce_gpt_provider_route,
        _coerce_gpt_quality=_coerce_gpt_quality, _coerce_gpt_reasoning_effort=_coerce_gpt_reasoning_effort, _coerce_gpt_resolution=_coerce_gpt_resolution,
        _coerce_gpt_task_type=_coerce_gpt_task_type, _coerce_image_ratio=_coerce_image_ratio, _coerce_prompt_mode=_coerce_prompt_mode,
        _coerce_use_third_party_api=_coerce_use_third_party_api, process_gpt_editable_file_task=process_gpt_editable_file_task, process_gpt_task=process_gpt_task,
        process_task=process_task, update_task=update_task,
    )


def _batch_task_uses_chatgpt_pool(task):
    return _domain_services_task_batch._batch_task_uses_chatgpt_pool(
        task, _coerce_gpt_provider_route=_coerce_gpt_provider_route, _coerce_use_third_party_api=_coerce_use_third_party_api,
    )


def _batch_task_requested_image_count(task):
    return _domain_services_task_batch._batch_task_requested_image_count(task, _coerce_gpt_image_count=_coerce_gpt_image_count)


def _batch_chatgpt_pool_parallel_limit(tasks):
    return _domain_services_task_batch._batch_chatgpt_pool_parallel_limit(
        tasks, _batch_task_requested_image_count=_batch_task_requested_image_count, _batch_task_uses_chatgpt_pool=_batch_task_uses_chatgpt_pool,
        _collect_chatgpt_pool_status=_collect_chatgpt_pool_status, _current_generation_limit=_current_generation_limit,
    )


def _wait_acquire_generation_slot_for_batch(batch_id):
    return _domain_services_task_batch._wait_acquire_generation_slot_for_batch(
        batch_id, _GENERATION_SEMAPHORE=_GENERATION_SEMAPHORE, get_batch_control=get_batch_control,
        time=time,
    )


def _run_batch_task_guarded(batch_id, task):
    return _domain_services_task_batch._run_batch_task_guarded(
        batch_id, task, _run_batch_task=_run_batch_task,
        get_batch_control=get_batch_control, get_task=get_task, time=time,
        update_task=update_task,
    )


def _run_batch_tasks_parallel(batch_id, tasks, parallel_limit):
    return _domain_services_task_batch._run_batch_tasks_parallel(
        batch_id, tasks, parallel_limit,
        _release_generation_slot=_release_generation_slot, _run_batch_task_guarded=_run_batch_task_guarded, _wait_acquire_generation_slot_for_batch=_wait_acquire_generation_slot_for_batch,
        queue=queue, threading=threading,
    )


def process_batch_tasks(batch_id, tasks):
    return _domain_services_task_batch.process_batch_tasks(
        batch_id, tasks, _batch_chatgpt_pool_parallel_limit=_batch_chatgpt_pool_parallel_limit,
        _run_batch_task_guarded=_run_batch_task_guarded, _run_batch_tasks_parallel=_run_batch_tasks_parallel, cancel_batch_queued_tasks=cancel_batch_queued_tasks,
        get_batch_control=get_batch_control,
    )


def _batch_tasks(batch_id):
    return _domain_services_task_batch._batch_tasks(batch_id, get_all_tasks=get_all_tasks)


def get_batch_control(batch_id):
    return _domain_services_task_batch.get_batch_control(batch_id, _batch_tasks=_batch_tasks)


def set_batch_control(batch_id, control):
    return _domain_services_task_batch.set_batch_control(
        batch_id, control, _batch_tasks=_batch_tasks,
        copy=copy, json=json, time=time,
        update_task_fields=update_task_fields,
    )


def cancel_batch_queued_tasks(batch_id):
    return _domain_services_task_batch.cancel_batch_queued_tasks(batch_id, _batch_tasks=_batch_tasks, time=time, update_task_fields=update_task_fields)


def get_batch_summary(batch_id):
    return _domain_services_task_batch.get_batch_summary(
        batch_id, FAILED_RETRY_STATUSES=FAILED_RETRY_STATUSES, _batch_tasks=_batch_tasks,
        _format_history_task=_format_history_task, get_batch_control=get_batch_control,
    )


def _prompt_chat_english_feed(text):
    return _domain_services_prompt_presets._prompt_chat_english_feed(text)


def _prompt_chat_style_enhanced(text, style):
    return _domain_services_prompt_presets._prompt_chat_style_enhanced(text, style)


def _prompt_version_candidates(base, message="", style=None, polished=None):
    """Build formal prompt candidates for the text-node assistant, excluding Original."""
    return _domain_services_prompt_presets._prompt_version_candidates(
        base, message, style,
        polished, _prompt_chat_english_feed=_prompt_chat_english_feed, _prompt_chat_style_enhanced=_prompt_chat_style_enhanced,
        _short_text=_short_text, time=time,
    )


def _read_versioned_json(path, root_key):
    return _domain_services_prompt_presets._read_versioned_json(path, root_key, json=json)


def _write_versioned_json(path, root_key, items):
    return _domain_services_prompt_presets._write_versioned_json(path, root_key, items, PROMPT_DATA_DIR=PROMPT_DATA_DIR, json=json)


def list_style_presets():
    return _domain_services_prompt_presets.list_style_presets(STYLE_PRESETS_FILE=STYLE_PRESETS_FILE, _read_versioned_json=_read_versioned_json)


def save_style_preset(data):
    return _domain_services_prompt_presets.save_style_preset(
        data, STYLE_PRESETS_FILE=STYLE_PRESETS_FILE, _write_versioned_json=_write_versioned_json,
        list_style_presets=list_style_presets, random=random, time=time,
    )


def list_prompt_versions(limit=200):
    return _domain_services_prompt_presets.list_prompt_versions(limit, PROMPT_VERSIONS_FILE=PROMPT_VERSIONS_FILE, _read_versioned_json=_read_versioned_json)


def save_prompt_version(data):
    return _domain_services_prompt_presets.save_prompt_version(
        data, PROMPT_VERSIONS_FILE=PROMPT_VERSIONS_FILE, _read_versioned_json=_read_versioned_json,
        _write_versioned_json=_write_versioned_json, random=random, time=time,
    )
COMFY_CLIENT_ID = os.environ.get('COMFY_CLIENT_ID', f"tg-mini-app-{uuid.uuid4().hex[:12]}")
COMFY_WORKFLOW_DIR = PROJECT_ROOT / 'workflows'
COMFY_PREVIEW_DIR = APP_DATA_DIR / 'data' / 'comfy' / 'previews'
UPSCALE_MODEL_DIR = Path(
    os.environ.get('UPSCALE_MODEL_DIR')
    or (APP_DATA_DIR / 'components' / 'upscale' / 'current' / 'models' if os.environ.get('CANVASHUB_DATA_DIR') else default_upscale_model_dir(PROJECT_ROOT))
).expanduser()
_topaz_runtime = TopazRuntime(APP_DATA_DIR / 'components' / 'topaz')
available_upscale_models = _available_upscale_models
upscale_image_file = _execute_upscale
COMFY_RATIO_SIZES = {
    '1:1': (1024, 1024),
    '2:3': (832, 1216),
    '3:2': (1216, 832),
    '16:9': (1344, 768),
    '9:16': (768, 1344),
    '4:3': (1152, 864),
    '3:4': (864, 1152),
    '4:5': (896, 1120),
    '5:4': (1120, 896),
    '9:21': (640, 1472),
    '21:9': (1472, 640),
}
COMFY_RESOLUTION_LONG_EDGES = {'1k': 0, '2k': 2048, '4k': 4096}

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
    return _domain_services_auth_policy._load_auth_password(get_miniapp_access_password=get_miniapp_access_password)


AUTH_PASSWORD = _load_auth_password()


def _effective_access_password_configured(settings=None):
    return _domain_services_auth_policy._effective_access_password_configured(settings, AUTH_PASSWORD=AUTH_PASSWORD, _settings_dict=_settings_dict, os=os)


def _validate_public_mode_password(settings=None, *, server_config=None):
    return _domain_services_auth_policy._validate_public_mode_password(
        settings, server_config=server_config, _effective_access_password_configured=_effective_access_password_configured,
        get_server_config=get_server_config,
    )


def _server_config_from_settings_snapshot(settings):
    return _domain_services_auth_policy._server_config_from_settings_snapshot(settings, _coerce_bool=_coerce_bool, _settings_dict=_settings_dict, os=os)

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
    return _domain_services_task_execution._current_generation_limit(
        _GENERATION_CONCURRENCY_LIMIT=_GENERATION_CONCURRENCY_LIMIT, get_max_concurrent_tasks=get_max_concurrent_tasks,
    )


def _generation_busy_message():
    return _domain_services_task_execution._generation_busy_message(_current_generation_limit=_current_generation_limit)


def _generation_busy_payload():
    return _domain_services_task_execution._generation_busy_payload(
        _current_generation_limit=_current_generation_limit, _generation_busy_message=_generation_busy_message,
    )


def _acquire_generation_slot():
    """Try to acquire a generation slot. Returns False (no slot) without blocking."""
    return _domain_services_task_execution._acquire_generation_slot(_GENERATION_SEMAPHORE=_GENERATION_SEMAPHORE)


def _release_generation_slot():
    """Release a generation slot. Safe to call even if semaphore is unset."""
    return _domain_services_task_execution._release_generation_slot(_GENERATION_SEMAPHORE=_GENERATION_SEMAPHORE)


def _run_generation_target(target, args, kwargs):
    return _domain_services_task_execution._run_generation_target(target, args, kwargs, _release_generation_slot=_release_generation_slot)


def _start_generation_thread(target, args=(), kwargs=None):
    return _domain_services_task_execution._start_generation_thread(
        target, args, kwargs,
        _acquire_generation_slot=_acquire_generation_slot, _release_generation_slot=_release_generation_slot, _run_generation_target=_run_generation_target,
        threading=threading,
    )


def _auth_enabled():
    return _domain_services_auth_policy._auth_enabled(AUTH_PASSWORD=AUTH_PASSWORD)


def _request_client_ip(headers, client_address):
    return _domain_services_auth_policy._request_client_ip(headers, client_address)


def _login_lock_state(client_ip, now=None):
    return _domain_services_auth_policy._login_lock_state(
        client_ip, now, _LOGIN_FAILURES=_LOGIN_FAILURES,
        _LOGIN_FAILURE_LIMIT=_LOGIN_FAILURE_LIMIT, _LOGIN_FAILURE_LOCK=_LOGIN_FAILURE_LOCK, _LOGIN_FAILURE_WINDOW_SECONDS=_LOGIN_FAILURE_WINDOW_SECONDS,
        _LOGIN_LOCKOUT_SECONDS=_LOGIN_LOCKOUT_SECONDS, time=time,
    )


def _record_login_failure(client_ip, now=None):
    return _domain_services_auth_policy._record_login_failure(
        client_ip, now, _LOGIN_FAILURES=_LOGIN_FAILURES,
        _LOGIN_FAILURE_LIMIT=_LOGIN_FAILURE_LIMIT, _LOGIN_FAILURE_LOCK=_LOGIN_FAILURE_LOCK, _LOGIN_FAILURE_WINDOW_SECONDS=_LOGIN_FAILURE_WINDOW_SECONDS,
        _LOGIN_LOCKOUT_SECONDS=_LOGIN_LOCKOUT_SECONDS, time=time,
    )


def _clear_login_failures(client_ip):
    return _domain_services_auth_policy._clear_login_failures(client_ip, _LOGIN_FAILURES=_LOGIN_FAILURES, _LOGIN_FAILURE_LOCK=_LOGIN_FAILURE_LOCK)


def _login_locked_payload(retry_after):
    return _domain_services_auth_policy._login_locked_payload(retry_after)


def _sensitive_db_base_paths():
    return _domain_services_auth_policy._sensitive_db_base_paths(
        DIRECTORY=DIRECTORY, Path=Path, get_chatgpt_pool_config=get_chatgpt_pool_config,
        get_database_path=get_database_path,
    )


def _ensure_db_file_permissions():
    return _domain_services_auth_policy._ensure_db_file_permissions(Path=Path, _sensitive_db_base_paths=_sensitive_db_base_paths)


def _load_telegram_auth_config():
    return _domain_services_auth_policy._load_telegram_auth_config(get_telegram_auth_config=get_telegram_auth_config)


TELEGRAM_AUTH_BOT_TOKEN, TELEGRAM_AUTH_ALLOWED_IDS = _load_telegram_auth_config()


def _verify_telegram_init_data(init_data):
    return _domain_services_auth_policy._verify_telegram_init_data(
        init_data, TELEGRAM_AUTH_ALLOWED_IDS=TELEGRAM_AUTH_ALLOWED_IDS, TELEGRAM_AUTH_BOT_TOKEN=TELEGRAM_AUTH_BOT_TOKEN,
        hashlib=hashlib, hmac=hmac, json=json,
        os=os, time=time, urllib=urllib,
    )


def _auth_secret():
    return _domain_services_auth_policy._auth_secret(AUTH_PASSWORD=AUTH_PASSWORD, DIRECTORY=DIRECTORY, hashlib=hashlib)


def _build_auth_cookie_value(issued_at=None):
    return _domain_services_auth_policy._build_auth_cookie_value(issued_at, _auth_secret=_auth_secret, hashlib=hashlib, hmac=hmac, time=time)


def _verify_auth_cookie_value(cookie_value):
    return _domain_services_auth_policy._verify_auth_cookie_value(
        cookie_value, AUTH_COOKIE_MAX_AGE=AUTH_COOKIE_MAX_AGE, _auth_enabled=_auth_enabled,
        _auth_secret=_auth_secret, hashlib=hashlib, hmac=hmac,
        time=time,
    )


def _new_comfy_session():
    return _domain_services_comfy_workflows._new_comfy_session(requests=requests)


def _comfy_workflow_catalog_settings():
    return _domain_services_comfy_workflows._comfy_workflow_catalog_settings(load_app_settings=load_app_settings)


def _comfy_workflow_preview_path(workflow_name):
    return _domain_services_comfy_workflows._comfy_workflow_preview_path(workflow_name, COMFY_PREVIEW_DIR=COMFY_PREVIEW_DIR, Path=Path, hashlib=hashlib)


def _comfy_workflow_uses_token(path, token):
    return _domain_services_comfy_workflows._comfy_workflow_uses_token(path, token)


def _default_comfy_workflow_label(filename):
    return _domain_services_comfy_workflows._default_comfy_workflow_label(filename, Path=Path)


COMFY_PARAMETER_LABELS = {
    'seed': '随机种子',
    'noise_seed': '噪声种子',
    'steps': '采样步数',
    'cfg': '引导强度（CFG）',
    'sampler_name': '采样器',
    'scheduler': '调度器',
    'denoise': '降噪强度',
    'strength_model': '模型强度',
    'strength_clip': 'CLIP 强度',
    'upscale_method': '缩放算法',
    'scale_by': '缩放倍数',
    'batch_size': '批次数量',
    'resolution': '目标分辨率',
    'max_resolution': '最大分辨率',
    'resolution_steps': '分辨率步进',
    'color_correction': '色彩校正',
    'input_noise_scale': '输入噪声强度',
    'latent_noise_scale': '潜空间噪声强度',
    'temporal_overlap': '时序重叠',
    'temporal_size': '时序块尺寸',
    'prepend_frames': '前置帧数',
    'uniform_batch_size': '统一批次',
    'encode_tiled': '编码分块',
    'decode_tiled': '解码分块',
    'encode_tile_size': '编码块尺寸',
    'decode_tile_size': '解码块尺寸',
    'encode_tile_overlap': '编码块重叠',
    'decode_tile_overlap': '解码块重叠',
    'blocks_to_swap': '交换区块数',
    'swap_io_components': '交换 I/O 组件',
    'attention_mode': '注意力模式',
    'enable_debug': '调试输出',
    'tile_size': '分块尺寸',
    'overlap': '分块重叠',
    'aspect_ratio': '画面比例',
    'proportional_width': '比例宽度',
    'proportional_height': '比例高度',
    'fit': '适配方式',
    'method': '处理方式',
    'round_to_multiple': '对齐倍数',
    'scale_to_side': '缩放基准边',
    'scale_to_length': '缩放目标长度',
    'background_color': '背景颜色',
    'value': '数值',
    'instruction': '模型指令',
    'to_ref': '使用参考图',
    'ref_main_image': '主参考图',
    'ref_longest_edge': '参考图最长边',
    'ref_crop': '裁剪参考图',
    'ref_upscale': '放大参考图',
    'ref_resize_mode': '参考图缩放方式',
    'image_output': '图像输出方式',
    'save_prefix': '保存前缀',
}
COMFY_PARAMETER_OPTIONS = {
    'sampler_name': ['euler', 'euler_ancestral', 'heun', 'dpm_2', 'dpm_2_ancestral', 'lms', 'dpmpp_2m', 'dpmpp_2m_sde', 'dpmpp_3m_sde', 'ddim', 'uni_pc'],
    'scheduler': ['normal', 'karras', 'exponential', 'sgm_uniform', 'simple', 'ddim_uniform', 'beta'],
    'upscale_method': ['nearest-exact', 'bilinear', 'area', 'bicubic', 'bislerp'],
    'color_correction': ['none', 'wavelet', 'adain', 'lab'],
}
COMFY_PARAMETER_EXCLUDED_INPUTS = {
    'width', 'height', 'image', 'images', 'prompt', 'text',
    'positive', 'negative', 'positive_prompt', 'negative_prompt', 'filename_prefix',
    'device', 'offload_device', 'cache_model', 'tile_debug', 'type', 'weight_dtype',
    'clip_name', 'vae_name', 'unet_name', 'lora_name', 'ckpt_name', 'model',
}

COMFY_DIMENSION_MIN = 64
COMFY_DIMENSION_MAX = 8192
COMFY_DIMENSION_STEP = 8


def _comfy_parameter_label(name):
    return _domain_services_comfy_workflows._comfy_parameter_label(name, COMFY_PARAMETER_LABELS=COMFY_PARAMETER_LABELS)


def _normalize_comfy_dimension(value, fallback=1024):
    return _domain_services_comfy_workflows._normalize_comfy_dimension(
        value, fallback, COMFY_DIMENSION_MAX=COMFY_DIMENSION_MAX,
        COMFY_DIMENSION_MIN=COMFY_DIMENSION_MIN, COMFY_DIMENSION_STEP=COMFY_DIMENSION_STEP,
    )


def _extract_comfy_workflow_default_size(workflow, fallback=(1024, 1024)):
    return _domain_services_comfy_workflows._extract_comfy_workflow_default_size(workflow, fallback, _normalize_comfy_dimension=_normalize_comfy_dimension)


def _comfy_workflow_has_image_input(workflow):
    return _domain_services_comfy_workflows._comfy_workflow_has_image_input(workflow)


def _comfy_ratio_from_size(width, height):
    return _domain_services_comfy_workflows._comfy_ratio_from_size(width, height, _normalize_comfy_dimension=_normalize_comfy_dimension, math=math)


def _comfy_parameter_number_bounds(name, value):
    return _domain_services_comfy_workflows._comfy_parameter_number_bounds(name, value)


def _extract_comfy_workflow_parameters(workflow):
    return _domain_services_comfy_workflows._extract_comfy_workflow_parameters(
        workflow, COMFY_PARAMETER_EXCLUDED_INPUTS=COMFY_PARAMETER_EXCLUDED_INPUTS, COMFY_PARAMETER_OPTIONS=COMFY_PARAMETER_OPTIONS,
        _comfy_parameter_label=_comfy_parameter_label, _comfy_parameter_number_bounds=_comfy_parameter_number_bounds,
    )


def _coerce_comfy_parameter_value(parameter, value):
    return _domain_services_comfy_workflows._coerce_comfy_parameter_value(parameter, value, _coerce_bool=_coerce_bool)


def _apply_comfy_parameter_overrides(workflow, overrides):
    return _domain_services_comfy_workflows._apply_comfy_parameter_overrides(
        workflow, overrides, _coerce_comfy_parameter_value=_coerce_comfy_parameter_value,
        _extract_comfy_workflow_parameters=_extract_comfy_workflow_parameters,
    )


def _collect_comfy_workflows(include_disabled=False):
    return _domain_services_comfy_gateway._collect_comfy_workflows(
        include_disabled, COMFY_WORKFLOW_DIR=COMFY_WORKFLOW_DIR, _coerce_bool=_coerce_bool,
        _comfy_workflow_catalog_settings=_comfy_workflow_catalog_settings, _comfy_workflow_has_image_input=_comfy_workflow_has_image_input, _comfy_workflow_preview_path=_comfy_workflow_preview_path,
        _comfy_workflow_uses_token=_comfy_workflow_uses_token, _default_comfy_workflow_label=_default_comfy_workflow_label, _extract_comfy_workflow_default_size=_extract_comfy_workflow_default_size,
        _extract_comfy_workflow_parameters=_extract_comfy_workflow_parameters, _normalize_comfy_dimension=_normalize_comfy_dimension, _resolve_comfy_size=_resolve_comfy_size,
        json=json, urllib=urllib,
    )


def _save_comfy_workflow_config(data):
    return _domain_services_comfy_gateway._save_comfy_workflow_config(
        data, COMFY_PREVIEW_DIR=COMFY_PREVIEW_DIR, COMFY_WORKFLOW_DIR=COMFY_WORKFLOW_DIR,
        Image=Image, Path=Path, _coerce_bool=_coerce_bool,
        _collect_comfy_workflows=_collect_comfy_workflows, _comfy_workflow_preview_path=_comfy_workflow_preview_path, _decode_data_uri_image=_decode_data_uri_image,
        _normalize_comfy_dimension=_normalize_comfy_dimension, load_app_settings=load_app_settings, save_app_settings=save_app_settings,
    )


def _normalize_comfy_base_url(value):
    return _domain_services_comfy_gateway._normalize_comfy_base_url(value, urllib=urllib)


def _collect_comfy_health(overrides=None):
    return _domain_services_comfy_gateway._collect_comfy_health(
        overrides, _new_comfy_session=_new_comfy_session, _normalize_comfy_base_url=_normalize_comfy_base_url,
        get_comfy_config=get_comfy_config, time=time,
    )


def _load_comfy_workflow(workflow_name):
    return _domain_services_comfy_gateway._load_comfy_workflow(workflow_name, COMFY_WORKFLOW_DIR=COMFY_WORKFLOW_DIR, Path=Path, json=json)


def _resolve_comfy_size(ratio, resolution='1k'):
    return _domain_services_comfy_gateway._resolve_comfy_size(
        ratio, resolution, COMFY_RATIO_SIZES=COMFY_RATIO_SIZES,
        COMFY_RESOLUTION_LONG_EDGES=COMFY_RESOLUTION_LONG_EDGES,
    )


def _replace_comfy_tokens(value, replacements):
    return _domain_services_comfy_gateway._replace_comfy_tokens(value, replacements, _replace_comfy_tokens=_replace_comfy_tokens)


def _decode_data_uri_image(data):
    return _domain_services_comfy_gateway._decode_data_uri_image(data, base64=base64)


def _upload_comfy_image(image_data):
    return _domain_services_comfy_gateway._upload_comfy_image(
        image_data, _decode_data_uri_image=_decode_data_uri_image, _new_comfy_session=_new_comfy_session,
        get_comfy_config=get_comfy_config, random=random, time=time,
    )


def _prepare_comfy_workflow(
    workflow,
    prompt,
    ratio,
    uploaded_image_name=None,
    uploaded_image_names=None,
    resolution='1k',
    width=None,
    height=None,
):
    return _domain_services_comfy_gateway._prepare_comfy_workflow(
        workflow, prompt, ratio,
        uploaded_image_name, uploaded_image_names, resolution,
        width, height, _normalize_comfy_dimension=_normalize_comfy_dimension,
        _replace_comfy_tokens=_replace_comfy_tokens, _resolve_comfy_size=_resolve_comfy_size, json=json,
        random=random,
    )


def _proxy_comfy_json(method, path, *, params=None, payload=None):
    return _domain_services_comfy_gateway._proxy_comfy_json(
        method, path, params=params,
        payload=payload, _new_comfy_session=_new_comfy_session, get_comfy_config=get_comfy_config,
    )


def _fetch_comfy_binary(filename, subfolder='', file_type='output'):
    return _domain_services_comfy_gateway._fetch_comfy_binary(
        filename, subfolder, file_type,
        _new_comfy_session=_new_comfy_session, get_comfy_config=get_comfy_config,
    )


def _find_comfy_images(outputs):
    return _domain_services_comfy_gateway._find_comfy_images(outputs)


def _find_best_comfy_image(outputs):
    return _domain_services_comfy_gateway._find_best_comfy_image(outputs, _find_comfy_images=_find_comfy_images)


def _save_task_params(task_id, params):
    return _domain_services_comfy_gateway._save_task_params(task_id, params, json=json, update_task_fields=update_task_fields)


def _extract_comfy_error(entry):
    return _domain_services_comfy_gateway._extract_comfy_error(entry)


def _sync_comfy_task(prompt_id, entry):
    return _domain_services_comfy_gateway._sync_comfy_task(
        prompt_id, entry, _extract_comfy_error=_extract_comfy_error,
        _find_comfy_images=_find_comfy_images, get_task=get_task, json=json,
        update_task=update_task, update_task_status=update_task_status,
    )


def _fetch_comfy_history_entry(prompt_id):
    return _domain_services_comfy_gateway._fetch_comfy_history_entry(prompt_id, _proxy_comfy_json=_proxy_comfy_json, urllib=urllib)


def _wait_for_comfy_websocket(
    prompt_id, client_id, *, base_url, deadline, is_cancelled,
    on_event=None, completion_probe=None, probe_interval=15.0, receive_timeout=1.0,
):
    return _domain_services_comfy_transport.wait_for_comfy_websocket(
        prompt_id, client_id, base_url=base_url, deadline=deadline,
        is_cancelled=is_cancelled, on_event=on_event, completion_probe=completion_probe,
        probe_interval=probe_interval, receive_timeout=receive_timeout,
    )


def _coerce_upscale_tile(value, fallback=256, minimum=64, maximum=2048):
    return _domain_services_upscale_generation._coerce_upscale_tile(value, fallback, minimum, maximum)


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
    return _domain_services_upscale_generation._write_upscale_sidecar(
        output_path, prompt, params,
        result_meta, Path=Path, write_obsidian_prompt_sidecar=write_obsidian_prompt_sidecar,
    )


def _process_image_enhancement_task(task_id, prompt, image_data, params, engine=None):
    """后台线程：本地高清放大任务。"""
    return _domain_services_upscale_generation.process_upscale_task(
        task_id, prompt, image_data,
        params, Path=Path, UPSCALE_MODELS=UPSCALE_MODELS,
        UPSCALE_MODEL_DIR=UPSCALE_MODEL_DIR, UpscaleRuntimeError=UpscaleRuntimeError, _coerce_bool=_coerce_bool,
        _coerce_upscale_tile=_coerce_upscale_tile, _decode_data_uri_image=_decode_data_uri_image, _finalize_generation_task=_finalize_generation_task,
        _merge_task_params=_merge_task_params, _record_generation_event=_record_generation_event, _start_generation_audit=_start_generation_audit,
        _translate_generation_failure=_translate_generation_failure, _upscale_progress_callback=_upscale_progress_callback, _write_upscale_sidecar=_write_upscale_sidecar,
        daily_output_dir=daily_output_dir, datetime=datetime, normalize_upscale_model=normalize_upscale_model,
        os=os, random=random, re=re,
        save_thumbnail=save_thumbnail, send_status_notification=send_status_notification, send_tg_document=send_tg_document,
        tempfile=tempfile, update_task_status=update_task_status, upscale_image_file=upscale_image_file,
        is_task_canceled=_is_task_canceled, engine=engine,
    )


def process_upscale_task(task_id, prompt, image_data, params):
    return _process_image_enhancement_task(task_id, prompt, image_data, params)


def process_topaz_task(task_id, prompt, image_data, params):
    return _process_image_enhancement_task(task_id, prompt, image_data, params,
                                          topaz_service.engine(_topaz_runtime, params))


H3_VIDEO_TASK_TYPE = 'minimax-h3-video'


def _sanitize_h3_prompt_metadata(value):
    return _domain_services_video_generation._sanitize_h3_prompt_metadata(value)
H3_VIDEO_MAX_REFERENCE_BYTES = 64 * 1024 * 1024
H3_VIDEO_DEFAULT_TASK_TIMEOUT_SECONDS = 6 * 60 * 60
_H3_PUBLIC_TASK_PARAM_KEYS = frozenset({
    'provider',
    'mode',
    'aspect_ratio',
    'pixel_budget_mp',
    'actual_megapixels',
    'width',
    'height',
    'duration_seconds',
    'steps',
    'denoise',
    'crf',
    'seed',
    'acceleration_mode',
    'first_block_cache_threshold',
    'archive_enabled',
    'telegram_enabled',
    'runtime_capability_source',
    'dimension_multiple',
    'max_pixels',
    'runtime_job_id',
    'runtime_mode',
    'runtime_version',
    'video_filename',
    'video_url',
    'video_size_bytes',
    'fps',
    'frame_count',
    'elapsed_seconds',
    'acceleration',
    'archive_date',
    'sidecar_files',
    'reference_image_filename',
})
_H3_PUBLIC_RUNTIME_OUTPUT_KEYS = (
    'width',
    'height',
    'fps',
    'frame_count',
    'duration_seconds',
    'seed',
    'elapsed_seconds',
)
_H3_PUBLIC_ACCELERATION_KEYS = frozenset({
    'mode',
    'first_block_cache',
    'first_block_cache_threshold',
    'sol_attn',
    'sol_attn_enabled',
    'cache_hits',
    'cache_misses',
    'cached_steps',
    'skipped_steps',
    'total_steps',
})


def _public_h3_acceleration(value):
    return _domain_services_video_generation._public_h3_acceleration(value, _H3_PUBLIC_ACCELERATION_KEYS=_H3_PUBLIC_ACCELERATION_KEYS)


def _public_h3_runtime_output(runtime_job):
    return _domain_services_video_generation._public_h3_runtime_output(
        runtime_job, _H3_PUBLIC_RUNTIME_OUTPUT_KEYS=_H3_PUBLIC_RUNTIME_OUTPUT_KEYS, _public_h3_acceleration=_public_h3_acceleration,
    )


def _public_h3_task_params(params):
    return _domain_services_video_generation._public_h3_task_params(
        params, _H3_PUBLIC_TASK_PARAM_KEYS=_H3_PUBLIC_TASK_PARAM_KEYS, _public_h3_acceleration=_public_h3_acceleration,
        safe_basename=safe_basename,
    )


def _write_text_atomic(path, content):
    return _domain_services_video_generation._write_text_atomic(path, content, Path=Path, os=os, uuid=uuid)


def _decode_h3_reference_image(data):
    return _domain_services_video_generation._decode_h3_reference_image(
        data, H3_VIDEO_MAX_REFERENCE_BYTES=H3_VIDEO_MAX_REFERENCE_BYTES, Image=Image,
        _decode_data_uri_image=_decode_data_uri_image, io=io,
    )


def _h3_phase_label(phase, fallback=''):
    return _domain_services_video_generation._h3_phase_label(phase, fallback)


def _archive_h3_reference_image(output_path, upload):
    """Persist the verified H3 input image beside a new output when available."""
    return _domain_services_video_generation._archive_h3_reference_image(
        output_path, upload, Path=Path,
        _ARCHIVE_IMAGE_EXTENSIONS=_ARCHIVE_IMAGE_EXTENSIONS, os=os, uuid=uuid,
    )


def _write_h3_video_sidecars(output_path, prompt, params, runtime_job, task_id='', reference_image_name=''):
    return _domain_services_video_generation._write_h3_video_sidecars(
        output_path, prompt, params,
        runtime_job, task_id, reference_image_name,
        H3_VIDEO_TASK_TYPE=H3_VIDEO_TASK_TYPE, Path=Path, _public_h3_runtime_output=_public_h3_runtime_output,
        _sanitize_h3_prompt_metadata=_sanitize_h3_prompt_metadata, _write_text_atomic=_write_text_atomic, json=json,
        re=re,
    )


def process_h3_video_task(task_id, prompt, upload, params):
    """Background bridge from the main task system to H3_Runtime_Server."""
    return _domain_services_video_generation.process_h3_video_task(
        task_id, prompt, upload,
        params, H3_VIDEO_DEFAULT_TASK_TIMEOUT_SECONDS=H3_VIDEO_DEFAULT_TASK_TIMEOUT_SECONDS, H3_VIDEO_TASK_TYPE=H3_VIDEO_TASK_TYPE,
        Path=Path, _archive_h3_reference_image=_archive_h3_reference_image, _coerce_bool=_coerce_bool,
        _finalize_generation_task=_finalize_generation_task, _h3_phase_label=_h3_phase_label, _is_task_canceled=_is_task_canceled,
        _merge_task_params=_merge_task_params, _public_h3_runtime_output=_public_h3_runtime_output, _record_generation_event=_record_generation_event,
        _start_generation_audit=_start_generation_audit, _translate_generation_failure=_translate_generation_failure, _write_h3_video_sidecars=_write_h3_video_sidecars,
        cancel_video_runtime_job=cancel_video_runtime_job, daily_output_dir=daily_output_dir, datetime=datetime,
        download_video_runtime_result=download_video_runtime_result, get_video_runtime_job=get_video_runtime_job, random=random,
        re=re, send_tg_document=send_tg_document, submit_video_runtime_job=submit_video_runtime_job,
        time=time, update_task_status=update_task_status, urllib=urllib,
    )


_COMFY_ARCHIVE_MANIFEST_VERSION = 1
_COMFY_TELEGRAM_STATES = frozenset(('pending', 'sending', 'sent', 'failed'))


def _comfy_archive_date(params):
    return _domain_services_comfy_generation._comfy_archive_date(params, datetime=datetime)


def _comfy_archive_source_key(task_id, item):
    return _domain_services_comfy_generation._comfy_archive_source_key(task_id, item, hashlib=hashlib, json=json)


def _comfy_archive_filename(task_id, item, source_key):
    return _domain_services_comfy_generation._comfy_archive_filename(task_id, item, source_key, Path=Path, hashlib=hashlib, re=re)


def _comfy_archive_file_ready(path):
    return _domain_services_comfy_generation._comfy_archive_file_ready(path)


def _build_comfy_archive_manifest(task_id, params, comfy_images, archive_date):
    return _domain_services_comfy_generation._build_comfy_archive_manifest(
        task_id, params, comfy_images,
        archive_date, _COMFY_ARCHIVE_MANIFEST_VERSION=_COMFY_ARCHIVE_MANIFEST_VERSION, _COMFY_TELEGRAM_STATES=_COMFY_TELEGRAM_STATES,
        _comfy_archive_filename=_comfy_archive_filename, _comfy_archive_source_key=_comfy_archive_source_key,
    )


def _atomic_write_comfy_text(path, text):
    return _domain_services_comfy_generation._atomic_write_comfy_text(path, text, os=os, tempfile=tempfile)


def _send_comfy_result(task_id, prompt, workflow, ratio, comfy_image, params):
    return _domain_services_comfy_generation._send_comfy_result(
        task_id, prompt, workflow,
        ratio, comfy_image, params,
        Path=Path, _atomic_write_comfy_text=_atomic_write_comfy_text, _build_comfy_archive_manifest=_build_comfy_archive_manifest,
        _coerce_bool=_coerce_bool, _comfy_archive_date=_comfy_archive_date, _comfy_archive_file_ready=_comfy_archive_file_ready,
        _fetch_comfy_binary=_fetch_comfy_binary, _is_task_canceled=_is_task_canceled, _normalize_comfy_dimension=_normalize_comfy_dimension,
        _save_task_params=_save_task_params, daily_output_dir=daily_output_dir, datetime=datetime,
        json=json, os=os, save_thumbnail=save_thumbnail,
        send_status_notification=send_status_notification, send_telegram=send_telegram, tempfile=tempfile,
        time=time, update_task=update_task, update_task_status=update_task_status,
        write_obsidian_prompt_sidecar=write_obsidian_prompt_sidecar,
    )


def process_comfy_task(task_id, prompt, workflow, ratio, client_id=None):
    return _domain_services_comfy_generation.process_comfy_task(
        task_id, prompt, workflow,
        ratio, client_id, _fetch_comfy_history_entry=_fetch_comfy_history_entry, _is_task_canceled=_is_task_canceled,
        _send_comfy_result=_send_comfy_result, _sync_comfy_task=_sync_comfy_task, get_comfy_config=get_comfy_config,
        _wait_for_comfy_websocket=_wait_for_comfy_websocket,
        send_status_notification=send_status_notification, time=time, update_task=update_task,
        update_task_status=update_task_status,
    )


def _resolve_download_file(filename):
    return _domain_services_media_lookup._resolve_download_file(filename, image_lookup_roots=image_lookup_roots, time=time)


_ARCHIVE_IMAGE_EXTENSIONS = frozenset({'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff'})
_ARCHIVE_VIDEO_EXTENSIONS = frozenset({'.mp4', '.webm', '.mov', '.m4v'})
_ARCHIVE_VIDEO_TEXT_EXTENSIONS = frozenset({'.txt', '.md'})
_ARCHIVE_VIDEO_SOURCE_TYPES = frozenset({'generated', 'imported', 'all'})
_ARCHIVE_VIDEO_SOURCE_LABELS = {
    'generated': '生成视频',
    'imported': '导入素材',
}
_ARCHIVE_VIDEO_SIDECAR_MAX_BYTES = 1024 * 1024
_ARCHIVE_VIDEO_METADATA_CACHE = {}
_ARCHIVE_VIDEO_METADATA_CACHE_LOCK = threading.Lock()
_ARCHIVE_VIDEO_METADATA_CACHE_LIMIT = 512


def _resolve_archive_resource_file(rel_path, extensions):
    """Resolve a regular archive file while rejecting traversal and symlink hops."""
    return _domain_services_media_lookup._resolve_archive_resource_file(rel_path, extensions, archive_scan_roots=archive_scan_roots, urllib=urllib)


def _resolve_archive_image_file(rel_path):
    return _domain_services_media_lookup._resolve_archive_image_file(
        rel_path, _ARCHIVE_IMAGE_EXTENSIONS=_ARCHIVE_IMAGE_EXTENSIONS, _resolve_archive_resource_file=_resolve_archive_resource_file,
    )


def _coerce_archive_video_source(value, default='generated'):
    return _domain_services_archive_sidecars._coerce_archive_video_source(value, default, _ARCHIVE_VIDEO_SOURCE_TYPES=_ARCHIVE_VIDEO_SOURCE_TYPES)


def _read_archive_video_sidecar(path):
    """Read a bounded, regular sibling sidecar without following symlinks."""
    return _domain_services_archive_sidecars._read_archive_video_sidecar(path, Path=Path, _ARCHIVE_VIDEO_SIDECAR_MAX_BYTES=_ARCHIVE_VIDEO_SIDECAR_MAX_BYTES)


def _decode_archive_sidecar_value(value):
    return _domain_services_archive_sidecars._decode_archive_sidecar_value(value, json=json)


def _parse_archive_markdown_frontmatter(content):
    return _domain_services_archive_sidecars._parse_archive_markdown_frontmatter(content, _decode_archive_sidecar_value=_decode_archive_sidecar_value)


def _archive_markdown_section(content, title):
    return _domain_services_archive_sidecars._archive_markdown_section(content, title, re=re)


def _strip_archive_markdown_fence(content):
    return _domain_services_archive_sidecars._strip_archive_markdown_fence(content, re=re)


def _extract_archive_json_object(content, preferred_task_type=''):
    return _domain_services_archive_sidecars._extract_archive_json_object(content, preferred_task_type, json=json, re=re)


def _parse_archive_video_text_sidecar(video_path):
    return _domain_services_archive_sidecars._parse_archive_video_text_sidecar(
        video_path, H3_VIDEO_TASK_TYPE=H3_VIDEO_TASK_TYPE, Path=Path,
        _extract_archive_json_object=_extract_archive_json_object, _read_archive_video_sidecar=_read_archive_video_sidecar, _strip_archive_markdown_fence=_strip_archive_markdown_fence,
    )


def _parse_archive_video_markdown_sidecar(video_path):
    return _domain_services_archive_sidecars._parse_archive_video_markdown_sidecar(
        video_path, H3_VIDEO_TASK_TYPE=H3_VIDEO_TASK_TYPE, Path=Path,
        _archive_markdown_section=_archive_markdown_section, _extract_archive_json_object=_extract_archive_json_object, _parse_archive_markdown_frontmatter=_parse_archive_markdown_frontmatter,
        _read_archive_video_sidecar=_read_archive_video_sidecar, _strip_archive_markdown_fence=_strip_archive_markdown_fence, re=re,
    )


def _parse_archive_video_sidecars(video_path):
    return _domain_services_archive_sidecars._parse_archive_video_sidecars(
        video_path, H3_VIDEO_TASK_TYPE=H3_VIDEO_TASK_TYPE, _parse_archive_video_markdown_sidecar=_parse_archive_video_markdown_sidecar,
        _parse_archive_video_text_sidecar=_parse_archive_video_text_sidecar,
    )


def _archive_video_markdown_is_generated(video_path):
    return _domain_services_archive_sidecars._archive_video_markdown_is_generated(video_path, _parse_archive_video_sidecars=_parse_archive_video_sidecars)


def _archive_video_text_is_generated(video_path):
    return _domain_services_archive_sidecars._archive_video_text_is_generated(video_path, _parse_archive_video_sidecars=_parse_archive_video_sidecars)


def _classify_archive_video_source(video_path, sidecar_data=None):
    return _domain_services_archive_sidecars._classify_archive_video_source(
        video_path, sidecar_data, _ARCHIVE_VIDEO_SOURCE_LABELS=_ARCHIVE_VIDEO_SOURCE_LABELS,
        _parse_archive_video_sidecars=_parse_archive_video_sidecars,
    )


_ARCHIVE_REFERENCE_PARAM_KEYS = frozenset({
    'first_frame',
    'first_frame_image',
    'input_image',
    'reference_image',
    'reference_images',
    'reference_file',
    'reference_files',
    'source_image',
    'source_images',
})
_ARCHIVE_ASSOCIATED_IMAGE_TOKENS = frozenset({
    'reference',
    'reference_image',
    'first_frame',
    'source',
    'input',
    'poster',
    'thumbnail',
    'cover',
})


def _archive_resource_url(resource_type, public_path):
    return _domain_services_archive_sidecars._archive_resource_url(resource_type, public_path, urllib=urllib)


def _archive_resource_entry(filepath, root_key, root, resource_type, role, label):
    return _domain_services_archive_sidecars._archive_resource_entry(
        filepath, root_key, root,
        resource_type, role, label,
        Path=Path, _archive_resource_url=_archive_resource_url, datetime=datetime,
        hashlib=hashlib, mimetypes=mimetypes,
    )


def _iter_archive_reference_values(value, key=''):
    yield from _domain_services_archive_sidecars._iter_archive_reference_values(
        value, key, _ARCHIVE_REFERENCE_PARAM_KEYS=_ARCHIVE_REFERENCE_PARAM_KEYS,
        _iter_archive_reference_values=_iter_archive_reference_values, re=re,
    )


def _resolve_same_directory_archive_image(reference, video_path):
    """Resolve an explicitly referenced image and require the video's directory."""
    return _domain_services_archive_sidecars._resolve_same_directory_archive_image(
        reference, video_path, Path=Path,
        _ARCHIVE_IMAGE_EXTENSIONS=_ARCHIVE_IMAGE_EXTENSIONS, _resolve_archive_resource_file=_resolve_archive_resource_file, urllib=urllib,
    )


def _archive_image_name_looks_associated(video_stem, image_name):
    return _domain_services_archive_sidecars._archive_image_name_looks_associated(
        video_stem, image_name, Path=Path,
        _ARCHIVE_ASSOCIATED_IMAGE_TOKENS=_ARCHIVE_ASSOCIATED_IMAGE_TOKENS,
    )


def _archive_video_folder_info(root_key, relative_path):
    return _domain_services_archive_sidecars._archive_video_folder_info(root_key, relative_path, Path=Path, hashlib=hashlib)


def _collect_archive_video_resources(filepath, root_key, relative_path, sidecar_data):
    return _domain_services_archive_sidecars._collect_archive_video_resources(
        filepath, root_key, relative_path,
        sidecar_data, Path=Path, _ARCHIVE_IMAGE_EXTENSIONS=_ARCHIVE_IMAGE_EXTENSIONS,
        _archive_image_name_looks_associated=_archive_image_name_looks_associated, _archive_resource_entry=_archive_resource_entry, _iter_archive_reference_values=_iter_archive_reference_values,
        _resolve_same_directory_archive_image=_resolve_same_directory_archive_image, archive_scan_roots=archive_scan_roots,
    )


def _resolve_ffprobe_executable():
    return _domain_services_archive_video._resolve_ffprobe_executable(BASE_DIR=BASE_DIR, Path=Path, os=os, shutil=shutil, sys=sys)


def _resolve_archive_video_file(rel_path):
    """Resolve a public archive-relative video path without escaping its root."""
    return _domain_services_archive_video._resolve_archive_video_file(
        rel_path, _ARCHIVE_VIDEO_EXTENSIONS=_ARCHIVE_VIDEO_EXTENSIONS, _resolve_archive_resource_file=_resolve_archive_resource_file,
    )


def _parse_video_frame_rate(value):
    return _domain_services_archive_video._parse_video_frame_rate(value, math=math)


def _positive_archive_media_number(value, integer=False):
    return _domain_services_archive_video._positive_archive_media_number(value, integer, math=math)


def _probe_archive_video_metadata(filepath, stat_result=None):
    """Read video metadata when ffprobe is available; failures are non-fatal."""
    return _domain_services_archive_video._probe_archive_video_metadata(
        filepath, stat_result, Path=Path,
        _ARCHIVE_VIDEO_METADATA_CACHE=_ARCHIVE_VIDEO_METADATA_CACHE, _ARCHIVE_VIDEO_METADATA_CACHE_LIMIT=_ARCHIVE_VIDEO_METADATA_CACHE_LIMIT, _ARCHIVE_VIDEO_METADATA_CACHE_LOCK=_ARCHIVE_VIDEO_METADATA_CACHE_LOCK,
        _parse_video_frame_rate=_parse_video_frame_rate, _resolve_ffprobe_executable=_resolve_ffprobe_executable, json=json,
        math=math, subprocess=subprocess,
    )


def _archive_video_task_map():
    """Map archived H3 result basenames to an unambiguous persisted task."""
    return _domain_services_archive_video._archive_video_task_map(H3_VIDEO_TASK_TYPE=H3_VIDEO_TASK_TYPE, Path=Path, get_all_tasks=get_all_tasks)


_ARCHIVE_VIDEO_PUBLIC_PARAMETER_KEYS = (
    'mode',
    'aspect_ratio',
    'pixel_budget_mp',
    'actual_megapixels',
    'width',
    'height',
    'duration_seconds',
    'steps',
    'denoise',
    'crf',
    'seed',
    'acceleration_mode',
    'first_block_cache_threshold',
    'fps',
    'frame_count',
    'elapsed_seconds',
)


def _public_archive_video_parameters(sidecar_parameters, task=None, metadata=None):
    """Return only generation controls and measured media values to the UI."""
    return _domain_services_archive_video._public_archive_video_parameters(
        sidecar_parameters, task, metadata,
        _ARCHIVE_VIDEO_PUBLIC_PARAMETER_KEYS=_ARCHIVE_VIDEO_PUBLIC_PARAMETER_KEYS, re=re,
    )


def _list_archive_videos(limit=200, offset=0, query='', source='generated'):
    """List archived videos using only public root-relative path information."""
    return _domain_services_archive_video._list_archive_videos(
        limit, offset, query,
        source, Path=Path, _ARCHIVE_VIDEO_EXTENSIONS=_ARCHIVE_VIDEO_EXTENSIONS,
        _ARCHIVE_VIDEO_SOURCE_LABELS=_ARCHIVE_VIDEO_SOURCE_LABELS, _archive_video_folder_info=_archive_video_folder_info, _archive_video_task_map=_archive_video_task_map,
        _classify_archive_video_source=_classify_archive_video_source, _coerce_archive_video_source=_coerce_archive_video_source, _collect_archive_video_resources=_collect_archive_video_resources,
        _parse_archive_video_sidecars=_parse_archive_video_sidecars, _positive_archive_media_number=_positive_archive_media_number, _probe_archive_video_metadata=_probe_archive_video_metadata,
        _public_archive_video_parameters=_public_archive_video_parameters, archive_scan_roots=archive_scan_roots, datetime=datetime,
        hashlib=hashlib, json=json, mimetypes=mimetypes,
        os=os, thumb_url_for_media_url=thumb_url_for_media_url, urllib=urllib,
    )


def _resolve_download_image(filename):
    """Compatibility wrapper for history original-image export."""
    return _domain_services_media_lookup._resolve_download_image(filename, _resolve_download_file=_resolve_download_file)


def _load_telegram_notify_config():
    return _domain_services_telegram_notifications._load_telegram_notify_config(get_telegram_config=get_telegram_config)


def _path_diagnostics(path_value, expect_dir=False):
    return _domain_services_system_settings._path_diagnostics(path_value, expect_dir, Path=Path, os=os)


def _collect_chatgpt_pool_status():
    """Return safe sidecar health/config without exposing the Bearer auth key."""
    return _domain_services_provider_accounts._collect_chatgpt_pool_status(
        get_chatgpt_pool_config=get_chatgpt_pool_config, get_chatgpt_pool_public_config=get_chatgpt_pool_public_config, requests=requests,
    )


def _chatgpt_pool_request(method, path, payload=None, timeout=None):
    return _domain_services_provider_accounts._chatgpt_pool_request(
        method, path, payload,
        timeout, get_chatgpt_pool_config=get_chatgpt_pool_config, requests=requests,
    )


def _chatgpt_pool_safe_auth_candidates():
    """Return local Codex auth files that diagnostics already considers valid."""
    return _domain_services_provider_accounts._chatgpt_pool_safe_auth_candidates(Path=Path, get_gpt_provider_auth_status=get_gpt_provider_auth_status)


def _chatgpt_pool_build_local_auth_account(requested_path=""):
    """Load one safe local Codex auth file and normalize it for sidecar import."""
    return _domain_services_provider_accounts._chatgpt_pool_build_local_auth_account(
        requested_path, Path=Path, _chatgpt_pool_safe_auth_candidates=_chatgpt_pool_safe_auth_candidates,
        json=json,
    )


def _chatgpt_pool_open_authorize_url_clean(authorize_url):
    """Open an OpenAI authorize URL in an isolated Chrome profile."""
    return _domain_services_provider_accounts._chatgpt_pool_open_authorize_url_clean(authorize_url, Path=Path, subprocess=subprocess, tempfile=tempfile, urllib=urllib)


def _chatgpt_pool_account_by_id(account_id):
    return _domain_services_provider_accounts._chatgpt_pool_account_by_id(account_id, _chatgpt_pool_request=_chatgpt_pool_request)


def _chatgpt_pool_verification_profile_dir(account_or_id):
    return _domain_services_provider_accounts._chatgpt_pool_verification_profile_dir(account_or_id, APP_DATA_DIR=APP_DATA_DIR, re=re)


def _chatgpt_pool_find_free_port():
    return _domain_services_provider_accounts._chatgpt_pool_find_free_port(socket=socket)


def _chatgpt_pool_complete_account_verification(account_id, debug_port=None):
    return _domain_services_provider_accounts._chatgpt_pool_complete_account_verification(
        account_id, debug_port, _chatgpt_pool_account_by_id=_chatgpt_pool_account_by_id,
        _chatgpt_pool_request=_chatgpt_pool_request, _chatgpt_pool_verification_profile_dir=_chatgpt_pool_verification_profile_dir,
    )


def _collect_system_diagnostics():
    return _domain_services_system_settings._collect_system_diagnostics(
        PORT=PORT, SERVER_HOST=SERVER_HOST, TELEGRAM_AUTH_ALLOWED_IDS=TELEGRAM_AUTH_ALLOWED_IDS,
        TELEGRAM_AUTH_BOT_TOKEN=TELEGRAM_AUTH_BOT_TOKEN, _auth_enabled=_auth_enabled, _collect_chatgpt_pool_status=_collect_chatgpt_pool_status,
        _collect_comfy_workflows=_collect_comfy_workflows, _path_diagnostics=_path_diagnostics, archive_scan_roots=archive_scan_roots,
        collect_video_runtime_component_status=collect_video_runtime_component_status, get_comfy_config=get_comfy_config, get_cyimg_config=get_cyimg_config, get_database_path=get_database_path,
        get_gpt_provider_auth_status=get_gpt_provider_auth_status, get_managed_codex_oauth_status=get_managed_codex_oauth_status, get_miniapp_access_password=get_miniapp_access_password,
        get_nano_banana_api_base_url=get_nano_banana_api_base_url, get_nano_banana_api_key=get_nano_banana_api_key, get_prompt_skill_config=get_prompt_skill_config,
        get_server_config=get_server_config, get_storage_config=get_storage_config, get_telegram_config=get_telegram_config,
        get_third_party_image_config=get_third_party_image_config, get_video_inference_public_config=get_video_inference_public_config, get_yunwu_api_base_url=get_yunwu_api_base_url,
        get_yunwu_api_key=get_yunwu_api_key, source_image_roots=source_image_roots,
    )


def _collect_gpt_runtime_config():
    return _domain_services_system_settings._collect_gpt_runtime_config(
        DEFAULT_GPT_IMAGE_MAIN_MODEL=DEFAULT_GPT_IMAGE_MAIN_MODEL, DEFAULT_GPT_PROVIDER_TOTAL_TIMEOUT_SECONDS=DEFAULT_GPT_PROVIDER_TOTAL_TIMEOUT_SECONDS, DEFAULT_GPT_REASONING_EFFORT=DEFAULT_GPT_REASONING_EFFORT,
        DEFAULT_GPT_TRANSPORT_MODE=DEFAULT_GPT_TRANSPORT_MODE, VALID_GPT_MAIN_MODELS=VALID_GPT_MAIN_MODELS, VALID_GPT_REASONING_EFFORTS=VALID_GPT_REASONING_EFFORTS,
        VALID_GPT_TRANSPORT_MODES=VALID_GPT_TRANSPORT_MODES, get_gpt_provider_config=get_gpt_provider_config,
    )


def _collect_system_settings():
    """Return editable settings without exposing secret values."""
    return _domain_services_system_settings._collect_system_settings(
        PORT=PORT, SERVER_HOST=SERVER_HOST, TELEGRAM_AUTH_ALLOWED_IDS=TELEGRAM_AUTH_ALLOWED_IDS,
        archive_scan_roots=archive_scan_roots, ensure_pinterest_auth_storage=ensure_pinterest_auth_storage, get_chatgpt_pool_public_config=get_chatgpt_pool_public_config,
        get_comfy_config=get_comfy_config, get_cyimg_config=get_cyimg_config, get_database_path=get_database_path, get_gpt_provider_config=get_gpt_provider_config,
        get_managed_codex_oauth_public_config=get_managed_codex_oauth_public_config, get_miniapp_access_password=get_miniapp_access_password, get_nano_banana_api_base_url=get_nano_banana_api_base_url,
        get_nano_banana_api_key=get_nano_banana_api_key, get_pinterest_browser_login_capability=get_pinterest_browser_login_capability, get_pinterest_config=get_pinterest_config,
        get_prompt_skill_config=get_prompt_skill_config, get_proxy_config=get_proxy_config, get_server_config=get_server_config,
        get_storage_config=get_storage_config, get_telegram_config=get_telegram_config, get_third_party_image_config=get_third_party_image_config,
        get_video_inference_public_config=get_video_inference_public_config, get_yunwu_api_base_url=get_yunwu_api_base_url, get_yunwu_api_key=get_yunwu_api_key,
        source_image_roots=source_image_roots,
    )


def _settings_dict(value):
    return _domain_services_system_settings._settings_dict(value)


def _clean_text(value, max_len=4096):
    return _domain_services_system_settings._clean_text(value, max_len)


def _clean_text_list(value):
    return _domain_services_system_settings._clean_text_list(value, _clean_text=_clean_text, re=re)


def _patch_text(target, source, key, max_len=4096, allow_empty=True):
    return _domain_services_system_settings._patch_text(target, source, key, max_len, allow_empty, _clean_text=_clean_text)


def _patch_secret(target, source, key, clear_key=None, max_len=8192):
    return _domain_services_system_settings._patch_secret(target, source, key, clear_key, max_len, _clean_text=_clean_text, _coerce_bool=_coerce_bool)


def _normalize_pinterest_profile_url(value):
    return _domain_services_system_settings._normalize_pinterest_profile_url(value, _clean_text=_clean_text, re=re, urllib=urllib)


def _normalize_pinterest_cookie_header(value):
    return _domain_services_system_settings._normalize_pinterest_cookie_header(value, re=re)


def _sanitize_system_settings_patch(payload):
    return _domain_services_system_settings._sanitize_system_settings_patch(
        payload, _clean_text=_clean_text, _clean_text_list=_clean_text_list,
        _coerce_bool=_coerce_bool, _coerce_gpt_main_model=_coerce_gpt_main_model, _coerce_gpt_provider_total_timeout=_coerce_gpt_provider_total_timeout,
        _coerce_gpt_reasoning_effort=_coerce_gpt_reasoning_effort, _coerce_gpt_transport_mode=_coerce_gpt_transport_mode, _normalize_comfy_base_url=_normalize_comfy_base_url,
        _normalize_pinterest_profile_url=_normalize_pinterest_profile_url, _patch_secret=_patch_secret, _patch_text=_patch_text,
        _server_config_from_settings_snapshot=_server_config_from_settings_snapshot, _settings_dict=_settings_dict, _validate_public_mode_password=_validate_public_mode_password,
        load_app_settings=load_app_settings, normalize_runtime_base_url=normalize_runtime_base_url, normalize_supervisor_base_url=normalize_supervisor_base_url,
    )


def _sanitize_gpt_provider_patch(data):
    return _domain_services_system_settings._sanitize_gpt_provider_patch(
        data, GPT_TRANSPORT_MODES=GPT_TRANSPORT_MODES, _coerce_gpt_provider_total_timeout=_coerce_gpt_provider_total_timeout,
    )


def _collect_prompt_skill_runtime_config(provider_id=None):
    return _domain_services_system_settings._collect_prompt_skill_runtime_config(
        provider_id, discover_prompt_models=discover_prompt_models, get_prompt_skill_config=get_prompt_skill_config,
        list_prompt_providers=list_prompt_providers,
    )


def _sanitize_prompt_skill_patch(data):
    return _domain_services_system_settings._sanitize_prompt_skill_patch(data, GPT_REASONING_EFFORTS=GPT_REASONING_EFFORTS)


def save_thumbnail(image_path, output_filename):
    """为历史记录生成缩略图到 google_outputs/thumb_*.png"""
    return _domain_services_media_lookup.save_thumbnail(
        image_path, output_filename, DIRECTORY=DIRECTORY,
        Image=Image, THUMB_MAX_SIDE=THUMB_MAX_SIDE, os=os,
    )

def safe_basename(filename):
    return _domain_services_media_lookup.safe_basename(filename, os=os)


REMOTE_IMAGE_IMPORT_MAX_BYTES = 32 * 1024 * 1024
REMOTE_IMAGE_IMPORT_MAX_REDIRECTS = 4
REMOTE_IMAGE_IMPORT_TIMEOUT = (10, 35)
REMOTE_IMAGE_PROXY_FAKE_NETWORK = ipaddress.ip_network('198.18.0.0/15')
_REMOTE_IMAGE_FORMAT_MIME = {
    'PNG': 'image/png',
    'JPEG': 'image/jpeg',
    'WEBP': 'image/webp',
    'GIF': 'image/gif',
    'BMP': 'image/bmp',
    'ICO': 'image/x-icon',
    'AVIF': 'image/avif',
}
_REMOTE_IMAGE_MIME_EXTENSION = {
    'image/png': '.png',
    'image/jpeg': '.jpg',
    'image/webp': '.webp',
    'image/gif': '.gif',
    'image/bmp': '.bmp',
    'image/x-icon': '.ico',
    'image/avif': '.avif',
    'image/svg+xml': '.svg',
}


def _validated_remote_image_url(value):
    """Allow public HTTP(S) image sources while blocking local-network fetches."""
    return _domain_services_image_import._validated_remote_image_url(
        value, REMOTE_IMAGE_PROXY_FAKE_NETWORK=REMOTE_IMAGE_PROXY_FAKE_NETWORK, ipaddress=ipaddress,
        socket=socket, urllib=urllib,
    )


def _sniff_remote_image_mime(image_bytes):
    return _domain_services_image_import._sniff_remote_image_mime(image_bytes, Image=Image, _REMOTE_IMAGE_FORMAT_MIME=_REMOTE_IMAGE_FORMAT_MIME, io=io)


def _remote_image_filename(url, mime_type):
    return _domain_services_image_import._remote_image_filename(
        url, mime_type, Path=Path,
        _REMOTE_IMAGE_MIME_EXTENSION=_REMOTE_IMAGE_MIME_EXTENSION, re=re, safe_basename=safe_basename,
        urllib=urllib,
    )


def _download_remote_image_for_import(url):
    return _domain_services_image_import._download_remote_image_for_import(
        url, REMOTE_IMAGE_IMPORT_MAX_BYTES=REMOTE_IMAGE_IMPORT_MAX_BYTES, REMOTE_IMAGE_IMPORT_MAX_REDIRECTS=REMOTE_IMAGE_IMPORT_MAX_REDIRECTS,
        REMOTE_IMAGE_IMPORT_TIMEOUT=REMOTE_IMAGE_IMPORT_TIMEOUT, _remote_image_filename=_remote_image_filename, _sniff_remote_image_mime=_sniff_remote_image_mime,
        _validated_remote_image_url=_validated_remote_image_url, get_proxy_config=get_proxy_config, requests=requests,
        urllib=urllib,
    )

def ensure_gpt_preview_image(filename, max_side=2048):
    """为 GPT 原图生成查看页用 2K 预览图，并缓存到 gpt_outputs。"""
    return _domain_services_media_lookup.ensure_gpt_preview_image(filename, max_side, DIRECTORY=DIRECTORY, Image=Image, Path=Path, safe_basename=safe_basename)


def _path_is_inside(path: Path, root: Path) -> bool:
    return _domain_services_asset_files._path_is_inside(
        path, root,
    )


def _allowed_asset_delete_roots():
    return _domain_services_asset_files._allowed_asset_delete_roots(
        DIRECTORY=DIRECTORY, Path=Path, image_lookup_roots=image_lookup_roots,
    )


def _unique_trash_path(filename):
    return _domain_services_asset_files._unique_trash_path(
        filename, Path=Path, safe_basename=safe_basename,
        time=time, uuid=uuid,
    )


def _move_asset_file_to_trash(path, deleted, missing, skipped, moves=None):
    return _domain_services_asset_files._move_asset_file_to_trash(
        path, deleted, missing,
        skipped, moves, Path=Path,
        _allowed_asset_delete_roots=_allowed_asset_delete_roots, _path_is_inside=_path_is_inside, _unique_trash_path=_unique_trash_path,
        shutil=shutil,
    )


def _asset_delete_candidates(asset):
    return _domain_services_asset_files._asset_delete_candidates(
        asset, DIRECTORY=DIRECTORY, Path=Path,
        _resolve_archive_image_file=_resolve_archive_image_file, _resolve_download_file=_resolve_download_file, safe_basename=safe_basename,
        urllib=urllib,
    )


def _asset_filename(asset):
    return _domain_services_asset_files._asset_filename(
        asset, safe_basename=safe_basename, urllib=urllib,
    )


def _asset_url_file_exists(url):
    return _domain_services_asset_files._asset_url_file_exists(
        url, DIRECTORY=DIRECTORY, Path=Path,
        _resolve_archive_image_file=_resolve_archive_image_file, _resolve_download_file=_resolve_download_file, safe_basename=safe_basename,
        urllib=urllib,
    )


def _asset_file_exists(asset):
    return _domain_services_asset_files._asset_file_exists(
        asset, DIRECTORY=DIRECTORY, Path=Path,
        _asset_filename=_asset_filename, _asset_url_file_exists=_asset_url_file_exists, _resolve_archive_image_file=_resolve_archive_image_file,
        _resolve_download_file=_resolve_download_file,
    )


def _remove_old_history_asset(asset, filename, removed_lines=None):
    return _domain_services_asset_files._remove_old_history_asset(
        asset, filename, removed_lines,
        DIRECTORY=DIRECTORY, Path=Path, json=json,
        re=re, safe_basename=safe_basename,
    )


def _restore_old_history_lines(lines):
    return _domain_services_asset_files._restore_old_history_lines(
        lines, DIRECTORY=DIRECTORY, Path=Path,
    )


def _remove_asset_from_task(asset, removed_history=None):
    return _domain_services_asset_files._remove_asset_from_task(
        asset, removed_history, _asset_filename=_asset_filename,
        _remove_old_history_asset=_remove_old_history_asset, get_task=get_task, json=json,
        update_task_fields=update_task_fields,
    )


def _remove_assets_from_tasks(assets, removed_history=None):
    return _domain_services_asset_files._remove_assets_from_tasks(
        assets, removed_history, _asset_filename=_asset_filename,
        _remove_old_history_asset=_remove_old_history_asset, get_task=get_task, json=json,
        safe_basename=safe_basename, update_task_fields=update_task_fields,
    )


def _delete_gallery_assets(asset_ids):
    return _delete_gallery_assets_service(
        asset_ids,
        list_assets=list_gallery_assets,
        get_asset=get_gallery_asset,
        get_task=get_task,
        snapshot_sets=snapshot_sets_for_asset,
        delete_candidates=_asset_delete_candidates,
        move_to_trash=_move_asset_file_to_trash,
        remove_from_tasks=_remove_assets_from_tasks,
        update_meta=update_asset_meta,
        remove_from_sets=remove_asset_from_sets,
        record_batch=record_delete_batch,
    )


def _collect_asset_health():
    return _collect_asset_health_service(
        list_assets=list_gallery_assets,
        list_sets=list_asset_sets,
        list_tasks=get_all_tasks,
        asset_exists=_asset_file_exists,
        should_render_history=_history_task_should_render,
    )


def _cleanup_lineage_refs(valid_asset_ids):
    return _domain_services_asset_files._cleanup_lineage_refs(
        valid_asset_ids, get_all_tasks=get_all_tasks, json=json,
        update_task_fields=update_task_fields,
    )


def _cleanup_no_image_history():
    return _domain_services_asset_files._cleanup_no_image_history(
        DIRECTORY=DIRECTORY, Path=Path, _history_task_should_render=_history_task_should_render,
        delete_task=delete_task, get_all_tasks=get_all_tasks, json=json,
        safe_basename=safe_basename,
    )


def _restore_trash_move(move):
    return _domain_services_asset_files._restore_trash_move(
        move, Path=Path, _allowed_asset_delete_roots=_allowed_asset_delete_roots,
        _path_is_inside=_path_is_inside, shutil=shutil,
    )


# Keep compatibility entrypoints on RequestHandler while moving their bodies.
# This table only consumes explicitly migrated, authenticated endpoints.
_google_pool_client = GooglePoolClient(get_chatgpt_pool_config)
_google_pool_provider = GooglePoolProvider(
    _google_pool_client, is_cancelled=lambda task_id: (get_task(task_id) or {}).get("status") in {"canceled", "cancelled"})
_GOOGLE_POOL_ROUTES = create_google_pool_router(_google_pool_client)
_CYIMG_SERVICE = CyimgService(
    get_config=get_cyimg_config, create_task=create_task, get_task=get_task,
    get_all_tasks=get_all_tasks, update_task=update_task, update_task_status=update_task_status,
    update_task_fields=update_task_fields, daily_output_dir=daily_output_dir,
    send_document=send_tg_document)
_CYIMG_ROUTES = create_cyimg_router(_CYIMG_SERVICE)
_KREA2_SERVICE = Krea2Service(
    APP_DATA_DIR / 'data' / 'krea2', APP_DATA_DIR / 'components' / 'krea2',
    Krea2Runtime(APP_DATA_DIR / 'components' / 'krea2'),
    create_task=create_task, get_task=get_task, get_all_tasks=get_all_tasks,
    update_task=update_task, update_task_status=update_task_status,
    update_task_fields=update_task_fields, daily_output_dir=daily_output_dir,
    write_prompt_sidecar=write_obsidian_prompt_sidecar, send_document=send_tg_document)
_KREA2_ROUTES = create_krea2_router(_KREA2_SERVICE)
_QWEN21_SERVICE = Qwen21Service(
    APP_DATA_DIR / 'data' / 'qwen21', APP_DATA_DIR / 'components' / 'qwen21',
    Qwen21Runtime(APP_DATA_DIR / 'components' / 'qwen21'),
    create_task=create_task, get_task=get_task, get_all_tasks=get_all_tasks,
    update_task=update_task, update_task_status=update_task_status,
    update_task_fields=update_task_fields, daily_output_dir=daily_output_dir,
    write_prompt_sidecar=write_obsidian_prompt_sidecar, send_document=send_tg_document)
_QWEN21_ROUTES = create_qwen21_router(_QWEN21_SERVICE)
_LORA_LIBRARY = LoRALibraryService(
    APP_DATA_DIR / 'data' / 'lora_library',
    catalogs={'krea2': _KREA2_SERVICE.loras.library_snapshot,
              'qwen21': _QWEN21_SERVICE.loras.library_snapshot},
    resolvers={'krea2': _KREA2_SERVICE.loras.resolve, 'qwen21': _QWEN21_SERVICE.loras.resolve},
    deleters={'krea2': _KREA2_SERVICE.delete_lora, 'qwen21': _QWEN21_SERVICE.delete_lora},
    excluded_ids=[item['sha256'] for item in QWEN21_MANAGED_ADAPTERS.values()],
    provider=CivitaiMetadataProvider(APP_DATA_DIR / 'data' / 'lora_library'))
_LORA_LIBRARY_ROUTES = create_lora_library_router(_LORA_LIBRARY)
_LOCAL_IMAGE_MEMORY = IdleWorkerCoordinator({
    'krea2': _KREA2_SERVICE.runtime.close, 'qwen21': _QWEN21_SERVICE.runtime.close})
_KREA2_SERVICE.runtime.before_load = lambda: _LOCAL_IMAGE_MEMORY.release_other('krea2')
_QWEN21_SERVICE.runtime.before_load = lambda: _LOCAL_IMAGE_MEMORY.release_other('qwen21')
_topaz_runtime.before_load = _LOCAL_IMAGE_MEMORY.release_all
_VIDEO_CONTROL_ROUTES = create_video_control_router(VideoControlService(
    APP_DATA_DIR / 'data' / 'video-control', VideoControlRuntime(
        APP_DATA_DIR / 'components' / 'reshot', before_load=_LOCAL_IMAGE_MEMORY.release_all)))
_TOPAZ_VIDEO_ROUTES = create_topaz_video_router(TopazVideoService(
    APP_DATA_DIR / 'data' / 'topaz-video', TopazVideoRuntime(
        APP_DATA_DIR / 'components' / 'topaz-video', before_load=_LOCAL_IMAGE_MEMORY.release_all)))
_AUDIO_ROUTES = create_audio_router(AudioService(
    APP_DATA_DIR / 'data' / 'audio', AudioRuntime(
        APP_DATA_DIR / 'components' / 'audio-yue', before_load=_LOCAL_IMAGE_MEMORY.release_all)))

_MIGRATED_ROUTES = ProtectedRouter({
    ("GET", "/api/history"): lambda handler: handler.handle_history(),
    ("GET", "/api/layout/fonts"): lambda handler: handler.handle_layout_fonts(),
    ("GET", "/api/layout/drafts"): lambda handler: handler.handle_layout_draft_list(
        urllib.parse.urlparse(handler.path)),
    ("GET", "/api/editable-files"): lambda handler: handler.handle_editable_files(
        urllib.parse.urlparse(handler.path)),
})


def _reload_auth_state():
    """Refresh the process-owned auth bindings after a successful settings save."""
    global AUTH_PASSWORD, TELEGRAM_AUTH_BOT_TOKEN, TELEGRAM_AUTH_ALLOWED_IDS
    AUTH_PASSWORD = _load_auth_password()
    TELEGRAM_AUTH_BOT_TOKEN, TELEGRAM_AUTH_ALLOWED_IDS = _load_telegram_auth_config()


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
            return str(FRONTEND_STATIC_ROOT.joinpath(*parts[1:]))
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
            elif path in IMMUTABLE_FRONTEND_PATHS:
                self.send_header('Cache-Control', 'public, max-age=31536000, immutable')
            elif path.startswith(('/scripts/', '/styles/')):
                if 'v=' in query:
                    self.send_header('Cache-Control', 'public, max-age=31536000, immutable')
                else:
                    self.send_header('Cache-Control', 'public, max-age=3600')
        except Exception:
            pass
        super().end_headers()

    def _get_cookie_value(self, name):
        return _domain_routes_auth_routes._get_cookie_value(self, name, SimpleCookie=SimpleCookie)

    def is_authenticated(self):
        return _domain_routes_auth_routes.is_authenticated(
            self, AUTH_COOKIE_NAME=AUTH_COOKIE_NAME, AUTH_HEADER_NAME=AUTH_HEADER_NAME,
            TELEGRAM_INIT_DATA_ENCODED_HEADER_NAME=TELEGRAM_INIT_DATA_ENCODED_HEADER_NAME, TELEGRAM_INIT_DATA_HEADER_NAME=TELEGRAM_INIT_DATA_HEADER_NAME, _auth_enabled=_auth_enabled,
            _verify_auth_cookie_value=_verify_auth_cookie_value, _verify_telegram_init_data=_verify_telegram_init_data, urllib=urllib,
        )

    def require_auth(self):
        return _domain_routes_auth_routes.require_auth(self)

    def _apply_cors_headers(self):
        return _domain_routes_http_responses._apply_cors_headers(self, get_allowed_cors_origins=get_allowed_cors_origins)

    def start_generation_task(self, task_id, target, args=(), task_ids=None):
        return _domain_routes_task_control_routes.start_generation_task(
            self, task_id, target,
            args, task_ids, _generation_busy_message=_generation_busy_message,
            _generation_busy_payload=_generation_busy_payload, _start_generation_thread=_start_generation_thread, update_task=update_task,
        )

    def do_OPTIONS(self):
        """处理 CORS 预检请求"""
        self.send_response(200)
        self._apply_cors_headers()
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, PATCH, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', f'Content-Type, {TELEGRAM_INIT_DATA_HEADER_NAME}, {TELEGRAM_INIT_DATA_ENCODED_HEADER_NAME}, {AUTH_HEADER_NAME}')
        self.end_headers()

    def do_HEAD(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith('/font/'):
            if not self.require_auth():
                return
            self.handle_layout_font_file(path[len('/font/'):])
            return
        super().do_HEAD()

    def do_GET(self):
        """处理 GET 请求"""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == '/v' or path.startswith('/v=') or path.lower().startswith('/%3f'):
            self.path = '/'
            super().do_GET()
            return

        if _VIDEO_CONTROL_ROUTES.dispatch(self, 'GET', path):
            return
        if _CYIMG_ROUTES.dispatch(self, 'GET', path):
            return
        if _KREA2_ROUTES.dispatch(self, 'GET', path):
            return
        if _QWEN21_ROUTES.dispatch(self, 'GET', path):
            return
        if _LORA_LIBRARY_ROUTES.dispatch(self, 'GET', path):
            return
        if _TOPAZ_VIDEO_ROUTES.dispatch(self, 'GET', path):
            return
        if _AUDIO_ROUTES.dispatch(self, 'GET', path):
            return
        if _GOOGLE_POOL_ROUTES.dispatch(self, 'GET', path):
            return
        if _MIGRATED_ROUTES.dispatch(self, 'GET', path):
            return

        # API 路由
        if path == '/api/assets':
            if not self.require_auth():
                return
            self.handle_assets(parsed)
        elif path == '/api/assets/videos':
            if not self.require_auth():
                return
            self.handle_asset_videos(parsed)
        elif path == '/api/assets/detail':
            if not self.require_auth():
                return
            self.handle_asset_detail(parsed)
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
        elif path == '/api/video/runtime/status':
            if not self.require_auth():
                return
            self.handle_video_runtime_status(parsed)
        elif path == '/api/video/supervisor/status':
            if not self.require_auth():
                return
            self.handle_video_supervisor_status(parsed)
        elif path == '/api/video/capabilities':
            if not self.require_auth():
                return
            self.handle_video_runtime_capabilities()
        elif path == '/api/pinterest/library':
            if not self.require_auth():
                return
            self.handle_pinterest_library(parsed)
        elif path == '/api/pinterest/download-status':
            if not self.require_auth():
                return
            self.handle_pinterest_download_status(parsed)
        elif path == '/api/pinterest/sync-status':
            if not self.require_auth():
                return
            self.handle_pinterest_sync_status(parsed)
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
        elif path == '/api/prompt/color-schemes':
            if not self.require_auth():
                return
            self.handle_prompt_color_schemes()
        elif path == '/api/prompt-library/blocks/list':
            if not self.require_auth():
                return
            self.handle_prompt_library_blocks_list(parsed)
        elif path == '/api/prompt-library/templates/list':
            if not self.require_auth():
                return
            self.handle_prompt_library_templates_list()
        elif path == '/api/agent/runs':
            if not self.require_auth():
                return
            self.handle_agent_runs(parsed)
        elif path.startswith('/api/agent/runs/'):
            if not self.require_auth():
                return
            self.handle_agent_run_get(parsed)
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
        elif path == '/api/topaz/models':
            if not self.require_auth():
                return
            topaz_routes.models(self, _topaz_runtime)
        elif path == '/api/upscale/models':
            if not self.require_auth():
                return
            self.handle_upscale_models()
        elif path == '/api/upscale/component/status':
            if not self.require_auth():
                return
            self.handle_upscale_component_status()
        elif path.startswith('/font/'):
            if not self.require_auth():
                return
            self.handle_layout_font_file(path[len('/font/'):])
        elif path.startswith('/image/'):
            if not self.require_auth():
                return
            filename = urllib.parse.unquote(path.split('/')[-1])
            self.handle_image(filename)
        elif path.startswith('/video/'):
            if not self.require_auth():
                return
            rel_path = path[len('/video/'):]
            self.handle_video(rel_path)
        elif path.startswith('/archive_image/'):
            if not self.require_auth():
                return
            rel_path = path[len('/archive_image/'):]
            self.handle_archive_image(rel_path)
        elif path.startswith('/archive_resource/'):
            if not self.require_auth():
                return
            rel_path = path[len('/archive_resource/'):]
            self.handle_archive_resource(rel_path)
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
        elif path == '/api/comfy/health':
            if not self.require_auth():
                return
            self.handle_comfy_health(parsed)
        elif path == '/api/comfy/workflow-thumbnail':
            if not self.require_auth():
                return
            self.handle_comfy_workflow_thumbnail(parsed)
        elif path == '/api/comfy/history':
            if not self.require_auth():
                return
            self.handle_comfy_history()
        elif path == '/api/comfy/image':
            if not self.require_auth():
                return
            self.handle_comfy_image()
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
        elif path.startswith('/api/agent/runs/'):
            if not self.require_auth():
                return
            self.handle_agent_run_delete(parsed)
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
        if _VIDEO_CONTROL_ROUTES.dispatch(self, 'POST', path):
            return
        if _CYIMG_ROUTES.dispatch(self, 'POST', path):
            return
        if _KREA2_ROUTES.dispatch(self, 'POST', path):
            return
        if _QWEN21_ROUTES.dispatch(self, 'POST', path):
            return
        if _LORA_LIBRARY_ROUTES.dispatch(self, 'POST', path):
            return
        if _TOPAZ_VIDEO_ROUTES.dispatch(self, 'POST', path):
            return
        if _AUDIO_ROUTES.dispatch(self, 'POST', path):
            return
        if _GOOGLE_POOL_ROUTES.dispatch(self, 'POST', path):
            return

        
        # API 路由
        if path == '/api/images/import-url':
            if not self.require_auth():
                return
            self.handle_image_import_url()
        elif path == '/generate':
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
        elif path == '/api/topaz/run':
            if not self.require_auth():
                return
            topaz_routes.submit(self, runtime=_topaz_runtime, create_task=create_task,
                process_task=process_topaz_task, attach_lineage=_attach_lineage_params)
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
        elif path == '/api/video/runtime/test':
            if not self.require_auth():
                return
            self.handle_video_runtime_test()
        elif path == '/api/video/supervisor/test':
            if not self.require_auth():
                return
            self.handle_video_supervisor_test()
        elif path == '/api/video/runtime/start':
            if not self.require_auth():
                return
            self.handle_video_runtime_start()
        elif path == '/api/video/prompt-compile':
            if not self.require_auth():
                return
            self.handle_video_prompt_compile()
        elif path == '/api/video/generate':
            if not self.require_auth():
                return
            self.handle_video_generate()
        elif path == '/api/pinterest/auth/start':
            if not self.require_auth():
                return
            self.handle_pinterest_auth_start()
        elif path == '/api/pinterest/auth/complete':
            if not self.require_auth():
                return
            self.handle_pinterest_auth_complete()
        elif path == '/api/pinterest/auth/cancel':
            if not self.require_auth():
                return
            self.handle_pinterest_auth_cancel()
        elif path == '/api/pinterest/auth/verify':
            if not self.require_auth():
                return
            self.handle_pinterest_auth_verify()
        elif path == '/api/pinterest/auth/logout':
            if not self.require_auth():
                return
            self.handle_pinterest_auth_logout()
        elif path == '/api/pinterest/download-pin':
            if not self.require_auth():
                return
            self.handle_pinterest_download_pin()
        elif path == '/api/pinterest/prompt':
            if not self.require_auth():
                return
            self.handle_pinterest_prompt_save()
        elif path == '/api/pinterest/download-board':
            if not self.require_auth():
                return
            self.handle_pinterest_download_board()
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
        elif path == '/api/prompt/video-analysis':
            if not self.require_auth():
                return
            self.handle_prompt_video_analysis()
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
        elif path == '/api/prompt/color-schemes/save':
            if not self.require_auth():
                return
            self.handle_prompt_color_scheme_save()
        elif path == '/api/prompt/color-schemes/delete':
            if not self.require_auth():
                return
            self.handle_prompt_color_scheme_delete()
        elif path == '/api/prompt/color-schemes/favorite':
            if not self.require_auth():
                return
            self.handle_prompt_color_scheme_favorite()
        elif path == '/api/prompt/color-schemes/migrate-legacy':
            if not self.require_auth():
                return
            self.handle_prompt_color_schemes_migrate_legacy()
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
        elif path == '/api/agent/runs' or path.startswith('/api/agent/runs/'):
            if not self.require_auth():
                return
            self.handle_agent_run_post(parsed)
        elif path == '/api/comfy/run':
            if not self.require_auth():
                return
            self.handle_comfy_run()
        elif path == '/api/comfy/workflow/config':
            if not self.require_auth():
                return
            self.handle_comfy_workflow_config_save()
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
        """发送 JSON 响应；大响应在客户端支持时做 gzip 压缩（提示词文本可压约 10x）。"""
        return _domain_routes_http_responses.send_json(self, data, status, extra_headers, gzip=gzip, json=json)

    def read_json_body(self, max_bytes=64 * 1024 * 1024):
        return _domain_routes_http_responses.read_json_body(self, max_bytes, json=json)

    def _agent_run_route_parts(self, parsed):
        return _domain_routes_agent_routes._agent_run_route_parts(self, parsed, urllib=urllib)

    def _send_agent_error(self, error):
        return _domain_routes_agent_routes._send_agent_error(
            self, error, AgentRunConflict=AgentRunConflict,
            AgentRunNotFound=AgentRunNotFound, AgentRuntimeError=AgentRuntimeError,
        )

    def handle_agent_runs(self, parsed):
        """List persisted Agent runs without exposing server configuration."""
        return _domain_routes_agent_routes.handle_agent_runs(self, parsed, get_agent_runtime=get_agent_runtime, urllib=urllib)

    def handle_agent_run_get(self, parsed):
        """Return one run plus incremental audit events."""
        return _domain_routes_agent_routes.handle_agent_run_get(self, parsed, get_agent_runtime=get_agent_runtime, urllib=urllib)

    def handle_agent_run_delete(self, parsed):
        """Permanently delete one inactive Agent run and its audit events."""
        try:
            parts = self._agent_run_route_parts(parsed)
            if len(parts) != 4 or parts[:3] != ['api', 'agent', 'runs'] or not parts[3]:
                self.send_json({"ok": False, "error": "Agent 运行路径不存在"}, 404)
                return
            self.send_json(get_agent_runtime().delete_run(parts[3]))
        except Exception as error:
            self._send_agent_error(error)

    def handle_agent_run_post(self, parsed):
        """Create or control a supervised Agent run."""
        return _domain_routes_agent_routes.handle_agent_run_post(self, parsed, get_agent_runtime=get_agent_runtime)

    def handle_desktop_workflow_save(self):
        """Save a desktop workflow JSON file (.tcflow.json or .json) to a local path."""
        return _domain_routes_agent_routes.handle_desktop_workflow_save(self, Path=Path, _coerce_bool=_coerce_bool, json=json, os=os, uuid=uuid)

    def handle_pose_assets_status(self):
        return _domain_routes_system_routes.handle_pose_assets_status(self, pose_assets_status=pose_assets_status)

    def handle_layout_fonts(self):
        """Compatibility entrypoint; resolve the font directory per request."""
        return _handle_layout_fonts(self, font_dir=PROJECT_ROOT / 'font')

    def handle_layout_font_file(self, encoded_name):
        return _handle_layout_font_file(
            self, encoded_name, font_dir=PROJECT_ROOT / 'font',
            head_only=self.command == 'HEAD',
        )

    def send_binary_file(self, path):
        return _domain_routes_http_responses.send_binary_file(self, path, Path=Path, mimetypes=mimetypes)

    def handle_layout_draft_get(self, parsed):
        """Compatibility entrypoint; keep storage functions resolved per request."""
        return _handle_layout_draft_get(
            self, parsed, load_draft=load_layout_draft, get_file=get_layout_draft_file,
        )

    def handle_layout_draft_list(self, parsed):
        return _handle_layout_draft_list(self, parsed, list_drafts=list_layout_drafts)

    def handle_layout_draft_post(self, parsed):
        """Compatibility entrypoint; storage writes and publication stay unchanged."""
        return _handle_layout_draft_post(
            self, parsed, create_draft=create_layout_draft,
            update_draft=update_layout_draft, save_asset=save_layout_draft_asset,
        )

    def publish_layout_draft(self, draft_id, data):
        """Compatibility entrypoint; resolve publication dependencies per request."""
        return _publish_layout_draft(
            draft_id, data,
            load_draft=load_layout_draft, get_draft_file=get_layout_draft_file,
            decode_image=_decode_data_uri_image, daily_output_dir=daily_output_dir,
            write_prompt_sidecar=write_obsidian_prompt_sidecar,
            save_thumbnail=save_thumbnail, create_task=create_task, update_task=update_task,
            time_now=time.time, random_int=random.randint,
        )
    
    def handle_login(self):
        """处理密码登录并写入 HttpOnly Cookie"""
        return _domain_routes_auth_routes.handle_login(
            self, AUTH_COOKIE_MAX_AGE=AUTH_COOKIE_MAX_AGE, AUTH_COOKIE_NAME=AUTH_COOKIE_NAME,
            AUTH_PASSWORD=AUTH_PASSWORD, _auth_enabled=_auth_enabled, _build_auth_cookie_value=_build_auth_cookie_value,
            _clear_login_failures=_clear_login_failures, _login_lock_state=_login_lock_state, _login_locked_payload=_login_locked_payload,
            _record_login_failure=_record_login_failure, _request_client_ip=_request_client_ip, json=json,
        )

    def _presented_auth_token(self):
        """按 is_authenticated 的优先级取出请求携带的鉴权 token。"""
        return _domain_routes_auth_routes._presented_auth_token(self, AUTH_COOKIE_NAME=AUTH_COOKIE_NAME, AUTH_HEADER_NAME=AUTH_HEADER_NAME, urllib=urllib)

    def _reusable_auth_token(self):
        """仍在前半有效期内的合法 token 原样复用，保持媒体 URL 跨启动稳定（浏览器缓存命中）。"""
        return _domain_routes_auth_routes._reusable_auth_token(
            self, AUTH_COOKIE_MAX_AGE=AUTH_COOKIE_MAX_AGE, _verify_auth_cookie_value=_verify_auth_cookie_value,
            time=time,
        )

    def _send_auth_success_cookie(self, message, cookie_value=None):
        return _domain_routes_auth_routes._send_auth_success_cookie(
            self, message, cookie_value,
            AUTH_COOKIE_MAX_AGE=AUTH_COOKIE_MAX_AGE, AUTH_COOKIE_NAME=AUTH_COOKIE_NAME, _build_auth_cookie_value=_build_auth_cookie_value,
        )
    
    def handle_auth_verify(self):
        """验证当前 Cookie 是否有效"""
        return _domain_routes_auth_routes.handle_auth_verify(self, _auth_enabled=_auth_enabled)
    
    def handle_generate(self, force_caller=None):
        """处理生成请求（支持 skill 调用托底策略）"""
        return _domain_routes_google_generation_routes.handle_generate(
            self, force_caller, DEFAULT_GOOGLE_IMAGE_MODEL=DEFAULT_GOOGLE_IMAGE_MODEL,
            _attach_lineage_params=_attach_lineage_params, _coerce_bool=_coerce_bool, _coerce_google_max_tokens=_coerce_google_max_tokens,
            _coerce_google_quality=_coerce_google_quality, _coerce_google_temperature=_coerce_google_temperature, _coerce_gpt_resolution=_coerce_gpt_resolution,
            _coerce_model=_coerce_model, _effective_image_ratio=_effective_image_ratio, create_task=create_task,
            json=json, process_task=process_task, random=random,
            time=time,
        )
    
    def handle_edit(self, force_caller=None):
        """处理编辑请求（支持 skill 调用托底策略）"""
        return _domain_routes_google_generation_routes.handle_edit(
            self, force_caller, DEFAULT_GOOGLE_IMAGE_MODEL=DEFAULT_GOOGLE_IMAGE_MODEL,
            _attach_lineage_params=_attach_lineage_params, _coerce_bool=_coerce_bool, _coerce_google_edit_quality=_coerce_google_edit_quality,
            _coerce_google_max_tokens=_coerce_google_max_tokens, _coerce_google_temperature=_coerce_google_temperature, _coerce_model=_coerce_model,
            _effective_image_ratio=_effective_image_ratio, create_task=create_task, json=json,
            process_edit_task=process_edit_task, random=random, time=time,
        )
    
    def handle_gpt_generate(self):
        """处理 GPT 生成请求（使用 ChatGPT/Codex 浏览器自动化）"""
        return _domain_routes_gpt_generation_routes.handle_gpt_generate(
            self, _attach_lineage_params=_attach_lineage_params, _coerce_bool=_coerce_bool,
            _coerce_gpt_image_count=_coerce_gpt_image_count, _coerce_gpt_main_model=_coerce_gpt_main_model, _coerce_gpt_moderation=_coerce_gpt_moderation,
            _coerce_gpt_provider_route=_coerce_gpt_provider_route, _coerce_gpt_quality=_coerce_gpt_quality, _coerce_gpt_reasoning_effort=_coerce_gpt_reasoning_effort,
            _coerce_gpt_resolution=_coerce_gpt_resolution, _coerce_gpt_task_type=_coerce_gpt_task_type, _coerce_prompt_mode=_coerce_prompt_mode,
            _coerce_use_third_party_api=_coerce_use_third_party_api, _effective_image_ratio=_effective_image_ratio, _gpt_route_uses_third_party=_gpt_route_uses_third_party,
            create_task=create_task, json=json, process_gpt_editable_file_task=process_gpt_editable_file_task,
            process_gpt_task=process_gpt_task, random=random, time=time,
        )

    def handle_gpt_edit(self):
        """处理 GPT 图像编辑请求（使用本地 Codex runtime）"""
        return _domain_routes_gpt_generation_routes.handle_gpt_edit(
            self, _attach_lineage_params=_attach_lineage_params, _coerce_bool=_coerce_bool,
            _coerce_gpt_main_model=_coerce_gpt_main_model, _coerce_gpt_moderation=_coerce_gpt_moderation, _coerce_gpt_provider_route=_coerce_gpt_provider_route,
            _coerce_gpt_quality=_coerce_gpt_quality, _coerce_gpt_reasoning_effort=_coerce_gpt_reasoning_effort, _coerce_gpt_resolution=_coerce_gpt_resolution,
            _coerce_prompt_mode=_coerce_prompt_mode, _coerce_use_third_party_api=_coerce_use_third_party_api, _effective_image_ratio=_effective_image_ratio,
            _gpt_route_uses_third_party=_gpt_route_uses_third_party, create_task=create_task, json=json,
            process_gpt_edit_task=process_gpt_edit_task, random=random, time=time,
        )

    def handle_upscale_models(self):
        """返回本地高清放大模型状态。"""
        return _domain_routes_system_routes.handle_upscale_models(
            self, UPSCALE_MODEL_DIR=UPSCALE_MODEL_DIR, available_upscale_models=available_upscale_models,
            get_upscale_component_status=get_upscale_component_status,
        )

    def handle_upscale_component_status(self):
        return _domain_routes_system_routes.handle_upscale_component_status(self, get_upscale_component_status=get_upscale_component_status)

    def handle_upscale_component_install(self):
        return _domain_routes_system_routes.handle_upscale_component_install(self, json=json, start_upscale_component_install=start_upscale_component_install)

    def handle_upscale_component_remove(self):
        return _domain_routes_system_routes.handle_upscale_component_remove(self, remove_upscale_component=remove_upscale_component)

    def handle_upscale_run(self):
        """处理本地高清放大请求。"""
        return _domain_routes_runtime_generation_routes.handle_upscale_run(
            self, UPSCALE_MODEL_DIR=UPSCALE_MODEL_DIR, _attach_lineage_params=_attach_lineage_params,
            _coerce_bool=_coerce_bool, _coerce_upscale_tile=_coerce_upscale_tile, available_upscale_models=available_upscale_models,
            create_task=create_task, get_upscale_component_status=get_upscale_component_status, json=json,
            normalize_upscale_model=normalize_upscale_model, process_upscale_task=process_upscale_task, random=random,
            time=time,
        )
    
    def handle_custom_generate(self):
        """处理 Custom API 生成请求（GPT-5.4 @ localhost:8080）"""
        return _domain_routes_gpt_generation_routes.handle_custom_generate(
            self, _coerce_gpt_moderation=_coerce_gpt_moderation, _coerce_gpt_quality=_coerce_gpt_quality,
            _coerce_gpt_resolution=_coerce_gpt_resolution, _coerce_image_ratio=_coerce_image_ratio, create_task=create_task,
            json=json, process_custom_task=process_custom_task, random=random,
            time=time,
        )

    def handle_spell_generate_prompt(self):
        """处理咒术模块的结构化提示词生成请求"""
        return _domain_routes_prompt_routes.handle_spell_generate_prompt(self, generate_structured_spell_prompt=generate_structured_spell_prompt, json=json)

    def handle_status(self, task_id):
        """处理状态查询"""
        return _handle_status(
            self, task_id, get_task=get_task,
            missing_task_payload=_missing_task_payload, status_response_task=_status_response_task,
        )

    def handle_generation_runs(self, parsed, task_id):
        """返回任务的 generation runs。"""
        return _handle_generation_runs(
            self, parsed, task_id, page_int=_history_page_int, get_runs=get_generation_runs,
        )

    def handle_generation_events(self, parsed, run_id):
        """返回指定 generation run 的事件流。"""
        return _handle_generation_events(
            self, parsed, run_id, page_int=_history_page_int,
            get_run=get_generation_run, get_events=get_generation_events,
        )

    def handle_assets(self, parsed):
        """返回图库资产索引。"""
        return _handle_assets(
            self, parsed, invalidate_cache=invalidate_asset_index_cache, list_assets=list_gallery_assets,
        )

    def handle_asset_videos(self, parsed):
        """返回归档目录中的视频资产，不暴露本机绝对路径。"""
        return _domain_routes_media_routes.handle_asset_videos(
            self, parsed, _ARCHIVE_VIDEO_SOURCE_TYPES=_ARCHIVE_VIDEO_SOURCE_TYPES,
            _coerce_archive_video_source=_coerce_archive_video_source, _history_page_int=_history_page_int, _list_archive_videos=_list_archive_videos,
            urllib=urllib,
        )

    def handle_asset_detail(self, parsed):
        """按 id 返回单个资产的完整字段（瘦身列表的详情补全）。"""
        return _handle_asset_detail(self, parsed, get_asset=get_gallery_asset)

    def handle_asset_sets(self, parsed):
        """返回图库候选集。"""
        return _handle_asset_sets(self, parsed, list_sets=list_asset_sets)

    def handle_prompt_sources(self):
        """返回独立远程提示词源状态。"""
        return _domain_routes_remote_source_routes.handle_prompt_sources(self, list_prompt_sources=list_prompt_sources)

    def handle_pinterest_library(self, parsed):
        """Return local or remote Pinterest Pins without importing them into the asset index."""
        return _domain_routes_remote_source_routes.handle_pinterest_library(
            self, parsed, ensure_pinterest_auth_storage=ensure_pinterest_auth_storage,
            get_pinterest_library=get_pinterest_library, urllib=urllib,
        )

    @staticmethod
    def _pinterest_board_and_pins(board_id, *, refresh=False):
        return _domain_routes_remote_source_routes._pinterest_board_and_pins(
            board_id, refresh=refresh, ensure_pinterest_auth_storage=ensure_pinterest_auth_storage,
            get_pinterest_config=get_pinterest_config, get_pinterest_library=get_pinterest_library,
        )

    def handle_pinterest_download_pin(self):
        """Download one Pinterest Pin into SOURCE_IMAGE_DIR/pinterest."""
        return _domain_routes_remote_source_routes.handle_pinterest_download_pin(self, download_pinterest_pin=download_pinterest_pin)

    def handle_pinterest_prompt_save(self):
        """Persist an analyzed prompt beside a synchronized Pinterest image."""
        return _domain_routes_remote_source_routes.handle_pinterest_prompt_save(self, save_pinterest_pin_prompt=save_pinterest_pin_prompt)

    def handle_pinterest_download_board(self):
        """Create a pollable run and discover/download the board in its worker."""
        return _domain_routes_remote_source_routes.handle_pinterest_download_board(self, start_pinterest_board_sync=start_pinterest_board_sync)

    def handle_pinterest_download_status(self, parsed):
        """Return progress for a Pinterest board download."""
        return _domain_routes_remote_source_routes.handle_pinterest_download_status(self, parsed, get_pinterest_board_download=get_pinterest_board_download, urllib=urllib)

    def handle_pinterest_sync_status(self, parsed):
        """Return a remote/local Pinterest difference summary without remote image URLs."""
        return _domain_routes_remote_source_routes.handle_pinterest_sync_status(
            self, parsed, ensure_pinterest_auth_storage=ensure_pinterest_auth_storage,
            get_pinterest_sync_status=get_pinterest_sync_status, urllib=urllib,
        )

    def handle_prompt_source_items(self, parsed):
        """返回远程提示词源本地化条目，不进入图库资产索引。"""
        return _domain_routes_remote_source_routes.handle_prompt_source_items(self, parsed, list_prompt_source_items=list_prompt_source_items, urllib=urllib)

    def handle_prompt_source_sync(self):
        """启动远程提示词源同步任务。"""
        return _domain_routes_remote_source_routes.handle_prompt_source_sync(self, start_prompt_source_sync=start_prompt_source_sync)

    def handle_prompt_source_stop(self):
        """停止正在运行的远程提示词源同步任务。"""
        return _domain_routes_remote_source_routes.handle_prompt_source_stop(self, stop_prompt_source_sync=stop_prompt_source_sync)

    def handle_prompt_source_run(self, run_id):
        """查询远程提示词源同步任务。"""
        return _domain_routes_remote_source_routes.handle_prompt_source_run(self, run_id, get_prompt_source_run=get_prompt_source_run)

    def handle_asset_set_post(self):
        """新建或更新图库候选集。"""
        return _handle_asset_set_post(self, create_set=create_asset_set, update_set=update_asset_set)

    def handle_asset_set_delete(self, set_id):
        """删除图库候选集。"""
        return _handle_asset_set_delete(self, set_id, delete_set=delete_asset_set)

    def handle_asset_health(self):
        """检查图库资产、候选集和溯源引用健康状态。"""
        return _handle_asset_health(self, collect_health=_collect_asset_health)

    def handle_system_diagnostics(self):
        """Return safe runtime configuration status without secret values."""
        return _domain_routes_system_routes.handle_system_diagnostics(self, _collect_system_diagnostics=_collect_system_diagnostics)

    def handle_app_update_status(self):
        """Return the latest public CanvasHub release without exposing configuration."""
        return _domain_routes_system_routes.handle_app_update_status(self, get_app_update_status=get_app_update_status)

    def handle_system_settings(self):
        """Return editable project settings without secret values."""
        return _domain_routes_system_routes.handle_system_settings(self, _collect_system_settings=_collect_system_settings)

    def handle_system_settings_save(self):
        """Persist whitelisted project settings into settings.json."""
        return _domain_routes_system_routes.handle_system_settings_save(
            self, _coerce_bool=_coerce_bool, _collect_system_settings=_collect_system_settings,
            _normalize_pinterest_cookie_header=_normalize_pinterest_cookie_header, _reload_auth_state=_reload_auth_state, _sanitize_system_settings_patch=_sanitize_system_settings_patch,
            _settings_dict=_settings_dict, copy=copy, delete_pinterest_auth=delete_pinterest_auth,
            ensure_pinterest_auth_storage=ensure_pinterest_auth_storage, get_pinterest_config=get_pinterest_config, import_pinterest_cookie_header=import_pinterest_cookie_header,
            save_app_settings=save_app_settings,
        )

    def handle_video_runtime_status(self, parsed=None):
        """Return H3 Runtime routing and optionally perform a live probe."""
        return _domain_routes_runtime_generation_routes.handle_video_runtime_status(
            self, parsed, _coerce_bool=_coerce_bool,
            collect_video_runtime_status=collect_video_runtime_status, urllib=urllib,
        )

    def handle_video_supervisor_status(self, parsed=None):
        """Return the configured H3 Supervisor address and optional health probe."""
        return _domain_routes_runtime_generation_routes.handle_video_supervisor_status(
            self, parsed, _coerce_bool=_coerce_bool,
            collect_video_supervisor_status=collect_video_supervisor_status, urllib=urllib,
        )

    def handle_video_runtime_capabilities(self):
        """Return live H3 capabilities, or a bounded offline fallback."""
        return _domain_routes_runtime_generation_routes.handle_video_runtime_capabilities(self, collect_video_runtime_capabilities=collect_video_runtime_capabilities)

    def handle_video_runtime_test(self):
        """Probe unsaved local/LAN fields from the settings panel."""
        return _domain_routes_runtime_generation_routes.handle_video_runtime_test(self, collect_video_runtime_status=collect_video_runtime_status)

    def handle_video_supervisor_test(self):
        """Probe an unsaved Supervisor URL from the settings panel."""
        return _domain_routes_runtime_generation_routes.handle_video_supervisor_test(self, collect_video_supervisor_status=collect_video_supervisor_status)

    def handle_video_runtime_start(self):
        """Start a separately installed local H3 Runtime component on Windows."""
        return _domain_routes_runtime_generation_routes.handle_video_runtime_start(self, start_local_video_runtime=start_local_video_runtime)

    def handle_video_prompt_compile(self):
        """Compile an I2VA request with the pinned official MiniMax H3 skill."""
        return _domain_routes_runtime_generation_routes.handle_video_prompt_compile(self, H3PromptCompileError=H3PromptCompileError, compile_h3_prompt=compile_h3_prompt)

    def handle_video_generate(self):
        """Create a tracked MiniMax H3 video task without exposing Runtime secrets."""
        return _domain_routes_runtime_generation_routes.handle_video_generate(
            self, H3_VIDEO_TASK_TYPE=H3_VIDEO_TASK_TYPE, _coerce_bool=_coerce_bool,
            _decode_h3_reference_image=_decode_h3_reference_image, _sanitize_h3_prompt_metadata=_sanitize_h3_prompt_metadata, collect_video_runtime_capabilities=collect_video_runtime_capabilities,
            create_task=create_task, process_h3_video_task=process_h3_video_task, random=random,
            time=time,
        )

    def handle_pinterest_auth_start(self):
        """Open an isolated local browser for Pinterest login."""
        return _domain_routes_remote_source_routes.handle_pinterest_auth_start(
            self, _normalize_pinterest_profile_url=_normalize_pinterest_profile_url, start_pinterest_browser_login=start_pinterest_browser_login,
        )

    def handle_pinterest_auth_complete(self):
        """Capture the isolated browser state after the user logs in."""
        return _domain_routes_remote_source_routes.handle_pinterest_auth_complete(self, complete_pinterest_browser_login=complete_pinterest_browser_login)

    def handle_pinterest_auth_cancel(self):
        """Close and remove an unfinished Pinterest login browser."""
        return _domain_routes_remote_source_routes.handle_pinterest_auth_cancel(self, cancel_pinterest_browser_login=cancel_pinterest_browser_login)

    def handle_pinterest_auth_verify(self):
        """Verify saved Pinterest browser state without exposing it."""
        return _domain_routes_remote_source_routes.handle_pinterest_auth_verify(self, verify_pinterest_saved_auth=verify_pinterest_saved_auth)

    def handle_pinterest_auth_logout(self):
        """Delete saved Pinterest browser authentication."""
        return _domain_routes_remote_source_routes.handle_pinterest_auth_logout(self, delete_pinterest_auth=delete_pinterest_auth)

    def handle_gpt_config(self):
        """Return safe GPT runtime options for the desktop UI."""
        return _domain_routes_provider_account_routes.handle_gpt_config(self, _collect_gpt_runtime_config=_collect_gpt_runtime_config)

    def handle_gpt_config_save(self):
        """Persist non-secret GPT provider settings into project settings.json."""
        return _domain_routes_provider_account_routes.handle_gpt_config_save(
            self, _collect_gpt_runtime_config=_collect_gpt_runtime_config, _sanitize_gpt_provider_patch=_sanitize_gpt_provider_patch,
            json=json, update_app_settings_section=update_app_settings_section,
        )

    def _read_json_body(self):
        return _domain_routes_http_responses._read_json_body(self, json=json)

    def handle_chatgpt_pool_status(self):
        """Return safe ChatGPT account-pool status for desktop settings."""
        return _domain_routes_provider_account_routes.handle_chatgpt_pool_status(self, _collect_chatgpt_pool_status=_collect_chatgpt_pool_status)

    def handle_gpt_models(self, parsed):
        """Return account-scoped generation models for each GPT route."""
        return _domain_routes_provider_account_routes.handle_gpt_models(
            self, parsed, _coerce_bool=_coerce_bool,
            get_gpt_model_catalog=get_gpt_model_catalog, urllib=urllib,
        )

    def handle_chatgpt_pool_accounts(self):
        """Proxy account list through server.py so the UI never sees sidecar auth."""
        return _domain_routes_provider_account_routes.handle_chatgpt_pool_accounts(self, _chatgpt_pool_request=_chatgpt_pool_request)

    def handle_managed_codex_oauth_status(self):
        """Return safe managed Codex OAuth status for desktop settings."""
        return _domain_routes_provider_account_routes.handle_managed_codex_oauth_status(self, get_managed_codex_oauth_status=get_managed_codex_oauth_status)

    def handle_managed_codex_oauth_post(self, path):
        """Handle project-managed Codex OAuth mutations."""
        return _domain_routes_provider_account_routes.handle_managed_codex_oauth_post(
            self, path, _coerce_bool=_coerce_bool,
            delete_managed_auth=delete_managed_auth, finish_managed_codex_oauth_callback=finish_managed_codex_oauth_callback, import_managed_auth_accounts=import_managed_auth_accounts,
            json=json, refresh_managed_auth=refresh_managed_auth, start_managed_codex_oauth_login=start_managed_codex_oauth_login,
            update_managed_auth_account=update_managed_auth_account,
        )

    def handle_chatgpt_pool_post(self, path):
        """Proxy account-pool management mutations to the local sidecar."""
        return _domain_routes_provider_account_routes.handle_chatgpt_pool_post(
            self, path, _chatgpt_pool_build_local_auth_account=_chatgpt_pool_build_local_auth_account,
            _chatgpt_pool_complete_account_verification=_chatgpt_pool_complete_account_verification, _chatgpt_pool_open_account_verification=lambda *args, **kwargs: _chatgpt_pool_open_account_verification(*args, **kwargs), _chatgpt_pool_open_authorize_url_clean=_chatgpt_pool_open_authorize_url_clean,
            _chatgpt_pool_request=_chatgpt_pool_request, json=json, search_chatgpt_pool=search_chatgpt_pool,
        )

    def handle_prompt_config(self, parsed):
        """Return prompt-skill settings and runtime model options."""
        return _domain_routes_prompt_routes.handle_prompt_config(
            self, parsed, _collect_prompt_skill_runtime_config=_collect_prompt_skill_runtime_config,
            urllib=urllib,
        )

    def handle_prompt_models(self, parsed):
        """Return dynamically discovered text model options for a prompt provider."""
        return _domain_routes_prompt_routes.handle_prompt_models(self, parsed, discover_prompt_models=discover_prompt_models, urllib=urllib)

    def handle_prompt_style_presets(self):
        """Return project-local style presets saved by the Prompt Drawer."""
        return _domain_routes_prompt_routes.handle_prompt_style_presets(self, list_style_presets=list_style_presets)

    def handle_prompt_versions(self, parsed):
        """Return saved prompt versions."""
        return _domain_routes_prompt_routes.handle_prompt_versions(
            self, parsed, _history_page_int=_history_page_int,
            list_prompt_versions=list_prompt_versions, urllib=urllib,
        )

    def handle_prompt_color_schemes(self):
        """Return active built-in and user-defined color schemes."""
        return _domain_routes_prompt_routes.handle_prompt_color_schemes(self, list_color_schemes=list_color_schemes)

    def handle_prompt_color_scheme_save(self):
        """Create or update one user-defined color scheme."""
        return _domain_routes_prompt_routes.handle_prompt_color_scheme_save(self, ColorSchemeNotFoundError=ColorSchemeNotFoundError, save_color_scheme=save_color_scheme)

    def handle_prompt_color_scheme_delete(self):
        """Soft-delete one user-defined color scheme."""
        return _domain_routes_prompt_routes.handle_prompt_color_scheme_delete(
            self, ColorSchemeNotFoundError=ColorSchemeNotFoundError, delete_color_scheme=delete_color_scheme,
        )

    def handle_prompt_color_scheme_favorite(self):
        """Persist an explicit favorite state for one color scheme."""
        return _domain_routes_prompt_routes.handle_prompt_color_scheme_favorite(
            self, ColorSchemeNotFoundError=ColorSchemeNotFoundError, set_color_scheme_favorite=set_color_scheme_favorite,
        )

    def handle_prompt_color_schemes_migrate_legacy(self):
        """Import color schemes and favorites from the former localStorage keys."""
        return _domain_routes_prompt_routes.handle_prompt_color_schemes_migrate_legacy(self, migrate_legacy_color_schemes=migrate_legacy_color_schemes)

    def handle_prompt_library_blocks_list(self, parsed):
        """Return reusable short prompt blocks for slash insertion and editors."""
        return _domain_routes_prompt_routes.handle_prompt_library_blocks_list(
            self, parsed, _coerce_bool=_coerce_bool,
            _history_page_int=_history_page_int, list_prompt_blocks=list_prompt_blocks, urllib=urllib,
        )

    def handle_prompt_library_templates_list(self):
        """Return active system and user-defined prompt split rules."""
        return _domain_routes_prompt_routes.handle_prompt_library_templates_list(self, list_prompt_templates=list_prompt_templates)

    def handle_prompt_library_template_save(self):
        """Create or update one user-defined prompt split rule."""
        return _domain_routes_prompt_routes.handle_prompt_library_template_save(self, save_prompt_template=save_prompt_template)

    def handle_prompt_library_template_delete(self):
        """Soft-delete one user-defined prompt split rule."""
        return _domain_routes_prompt_routes.handle_prompt_library_template_delete(self, delete_prompt_template=delete_prompt_template)

    def handle_prompt_config_save(self):
        """Persist non-secret prompt-skill settings into project settings.json."""
        return _domain_routes_prompt_routes.handle_prompt_config_save(
            self, _collect_prompt_skill_runtime_config=_collect_prompt_skill_runtime_config, _sanitize_prompt_skill_patch=_sanitize_prompt_skill_patch,
            json=json, update_app_settings_section=update_app_settings_section,
        )

    def handle_prompt_polish(self):
        """Run the selected prompt skill and return full/compact prompt variants."""
        return _domain_routes_prompt_routes.handle_prompt_polish(
            self, _polish_prompt_with_chatgpt_pool_chat=_polish_prompt_with_chatgpt_pool_chat, json=json,
            polish_prompt=polish_prompt,
        )

    def handle_prompt_style_preset_save(self):
        """Persist one project-local style preset."""
        return _domain_routes_prompt_routes.handle_prompt_style_preset_save(self, save_style_preset=save_style_preset)

    def handle_prompt_style_preset_extract(self):
        """Extract a reusable style preset draft from text-node context."""
        return _domain_routes_prompt_routes.handle_prompt_style_preset_extract(self, extract_style_preset=extract_style_preset)

    def handle_prompt_version_save(self):
        """Persist one prompt candidate/version."""
        return _domain_routes_prompt_routes.handle_prompt_version_save(self, save_prompt_version=save_prompt_version)

    def handle_prompt_library_block_save(self):
        """Create or update one reusable short prompt block."""
        return _domain_routes_prompt_routes.handle_prompt_library_block_save(self, save_prompt_block=save_prompt_block)

    def handle_prompt_library_block_delete(self):
        """Soft-delete one reusable short prompt block."""
        return _domain_routes_prompt_routes.handle_prompt_library_block_delete(self, delete_prompt_block=delete_prompt_block)

    def handle_prompt_library_block_use(self):
        """Update block usage ranking after slash insertion."""
        return _domain_routes_prompt_routes.handle_prompt_library_block_use(self, mark_prompt_block_used=mark_prompt_block_used)

    def handle_prompt_library_blocks_extract(self):
        """Extract editable prompt-block candidates from text or one uploaded image."""
        return _domain_routes_prompt_routes.handle_prompt_library_blocks_extract(
            self, extract_reusable_prompt_blocks=extract_reusable_prompt_blocks, extract_reusable_prompt_blocks_from_image=extract_reusable_prompt_blocks_from_image,
            generic_19_prompt_block_split_rule=generic_19_prompt_block_split_rule, random=random, resolve_prompt_template=resolve_prompt_template,
            time=time,
        )

    def handle_prompt_assistant_chat(self):
        """Lightweight text-node Prompt Copilot discussion endpoint."""
        return _domain_routes_prompt_routes.handle_prompt_assistant_chat(self, assistant_chat=assistant_chat)

    def _start_ndjson_response(self):
        """Start the existing unbuffered NDJSON HTTP response."""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self._apply_cors_headers()
        self.end_headers()

    def _write_ndjson_event(self, event):
        return _domain_routes_http_responses._write_ndjson_event(self, event, json=json)

    def handle_prompt_assistant_chat_stream(self):
        """Stream text-node Prompt Copilot discussion deltas."""
        return _domain_routes_prompt_routes.handle_prompt_assistant_chat_stream(self, assistant_chat_stream=assistant_chat_stream)

    def handle_prompt_safe_rewrite(self):
        """Rewrite one text-node prompt through the standalone safety adapter."""
        return _domain_routes_prompt_routes.handle_prompt_safe_rewrite(self, random=random, safe_rewrite_prompt=safe_rewrite_prompt, time=time)

    def handle_prompt_image_analysis(self):
        """Analyze image references into prompt candidates and structured modules."""
        return _domain_routes_prompt_routes.handle_prompt_image_analysis(self, analyze_prompt_image=analyze_prompt_image)

    def handle_prompt_video_analysis(self):
        """Analyze sampled video references into prompt candidates and modules."""
        return _domain_routes_prompt_routes.handle_prompt_video_analysis(self, analyze_prompt_video=analyze_prompt_video)

    def handle_prompt_versions_generate(self):
        """Generate formal prompt candidates for the text-node assistant."""
        return _domain_routes_prompt_routes.handle_prompt_versions_generate(
            self, _prompt_version_candidates=_prompt_version_candidates, polish_prompt=polish_prompt,
            random=random, time=time,
        )

    def handle_prompt_chat(self):
        """Return prompt candidates for the desktop Prompt Chat Drawer."""
        return _domain_routes_prompt_routes.handle_prompt_chat(
            self, _prompt_version_candidates=_prompt_version_candidates, polish_prompt=polish_prompt,
            random=random, time=time,
        )

    def handle_asset_health_cleanup(self):
        """清理缺文件资产、候选集坏引用、空候选集和失效溯源。"""
        return _domain_routes_asset_maintenance_routes.handle_asset_health_cleanup(
            self, _cleanup_lineage_refs=_cleanup_lineage_refs, _cleanup_no_image_history=_cleanup_no_image_history,
            _collect_asset_health=_collect_asset_health, _remove_asset_from_task=_remove_asset_from_task, cleanup_asset_sets=cleanup_asset_sets,
            get_gallery_asset=get_gallery_asset, remove_asset_from_sets=remove_asset_from_sets, update_asset_meta=update_asset_meta,
        )

    def handle_asset_meta(self):
        """更新图库资产人工元数据。"""
        return _handle_asset_meta(self, update_meta=update_asset_meta)

    def handle_asset_delete(self, asset_id):
        """从图库移除资产，并把本地原图/提示词/预览移入废纸篓。"""
        return _handle_asset_delete(self, asset_id, delete_assets=_delete_gallery_assets)

    def handle_asset_delete_batch(self):
        """批量删除图库资产，避免同任务多图逐张删除时 asset_id 重新计算。"""
        return _handle_asset_delete_batch(self, delete_assets=_delete_gallery_assets)

    def handle_asset_undo_delete(self):
        """撤销最近的图库物理删除。"""
        return _handle_asset_undo_delete(
            self,
            get_batch=get_delete_batch,
            restore_move=_restore_trash_move,
            restore_task=restore_task_snapshot,
            restore_history=_restore_old_history_lines,
            restore_sets=restore_asset_set_snapshots,
            update_meta=update_asset_meta,
            mark_restored=mark_delete_batch_restored,
        )

    def handle_task_cancel(self, task_id):
        """取消正在运行的任务。

        生成线程会通过任务状态感知取消；正在进行中的单次上游调用不会被强杀，
        但后续图片、托底和 Telegram 发送会停止。
        """
        return _domain_routes_task_control_routes.handle_task_cancel(
            self, task_id, _missing_task_payload=_missing_task_payload,
            get_task=get_task, time=time, update_task_fields=update_task_fields,
        )

    def handle_task_retry(self, task_id):
        """从失败历史记录创建一个新的重跑任务，不修改原任务。"""
        return _domain_routes_task_control_routes.handle_task_retry(
            self, task_id, GenerationQueueFullError=GenerationQueueFullError,
            TaskRetryError=TaskRetryError, _generation_busy_payload=_generation_busy_payload, _missing_task_payload=_missing_task_payload,
            get_task=get_task, retry_failed_task=retry_failed_task,
        )

    def handle_task_batch(self):
        """创建顺序执行的批量生成任务。"""
        return _domain_routes_task_control_routes.handle_task_batch(
            self, TaskRetryError=TaskRetryError, _batch_prompt_items=_batch_prompt_items,
            _create_batch_tasks=_create_batch_tasks, process_batch_tasks=process_batch_tasks,
        )

    def handle_batch_status(self, batch_id):
        """聚合同一个 batch_id 下的子任务状态。"""
        return _domain_routes_task_control_routes.handle_batch_status(self, batch_id, get_batch_summary=get_batch_summary)

    def handle_batch_control(self, batch_id, action):
        """暂停、恢复或取消批量任务。"""
        return _domain_routes_task_control_routes.handle_batch_control(
            self, batch_id, action,
            cancel_batch_queued_tasks=cancel_batch_queued_tasks, get_batch_summary=get_batch_summary, set_batch_control=set_batch_control,
        )

    def handle_comfy_workflows(self):
        """返回可用的 ComfyUI 工作流列表"""
        return _domain_routes_runtime_generation_routes.handle_comfy_workflows(
            self, _coerce_bool=_coerce_bool, _collect_comfy_workflows=_collect_comfy_workflows,
            urllib=urllib,
        )

    def handle_comfy_health(self, parsed=None):
        """测试 ComfyUI 服务连接。"""
        return _domain_routes_runtime_generation_routes.handle_comfy_health(self, parsed, _collect_comfy_health=_collect_comfy_health, urllib=urllib)

    def handle_comfy_workflow_thumbnail(self, parsed):
        """返回经过目录白名单解析的工作流缩略图。"""
        return _domain_routes_runtime_generation_routes.handle_comfy_workflow_thumbnail(
            self, parsed, COMFY_WORKFLOW_DIR=COMFY_WORKFLOW_DIR,
            Path=Path, _comfy_workflow_preview_path=_comfy_workflow_preview_path, urllib=urllib,
        )

    def handle_comfy_workflow_config_save(self):
        """保存工作流展示元信息和缩略图。"""
        return _domain_routes_runtime_generation_routes.handle_comfy_workflow_config_save(
            self, _collect_comfy_workflows=_collect_comfy_workflows, _save_comfy_workflow_config=_save_comfy_workflow_config,
        )

    def handle_comfy_run(self):
        """将前端请求转发到远端 ComfyUI /prompt"""
        return _domain_routes_runtime_generation_routes.handle_comfy_run(
            self, COMFY_CLIENT_ID=COMFY_CLIENT_ID, COMFY_RESOLUTION_LONG_EDGES=COMFY_RESOLUTION_LONG_EDGES,
            _apply_comfy_parameter_overrides=_apply_comfy_parameter_overrides, _coerce_bool=_coerce_bool, _collect_comfy_workflows=_collect_comfy_workflows,
            _comfy_ratio_from_size=_comfy_ratio_from_size, _load_comfy_workflow=_load_comfy_workflow, _normalize_comfy_dimension=_normalize_comfy_dimension,
            _prepare_comfy_workflow=_prepare_comfy_workflow, _proxy_comfy_json=_proxy_comfy_json, _resolve_comfy_size=_resolve_comfy_size,
            _upload_comfy_image=_upload_comfy_image, create_task=create_task, json=json,
            process_comfy_task=process_comfy_task, uuid=uuid,
        )

    def handle_comfy_history(self):
        """代理查询远端 ComfyUI 历史任务"""
        return _domain_routes_runtime_generation_routes.handle_comfy_history(
            self, _fetch_comfy_history_entry=_fetch_comfy_history_entry, _sync_comfy_task=_sync_comfy_task,
            urllib=urllib,
        )

    def handle_comfy_image(self):
        """代理远端 ComfyUI 图片下载"""
        return _domain_routes_runtime_generation_routes.handle_comfy_image(self, _fetch_comfy_binary=_fetch_comfy_binary, urllib=urllib)

    def handle_comfy_send_tg(self):
        """下载远端 ComfyUI 结果并无损发送到 Telegram"""
        return _domain_routes_runtime_generation_routes.handle_comfy_send_tg(
            self, Path=Path, _fetch_comfy_binary=_fetch_comfy_binary,
            json=json, os=os, send_telegram=send_telegram,
            tempfile=tempfile,
        )

    def handle_history_export_tg(self):
        """把历史记录中的本机原图通过 Telegram sendDocument 发送出去。"""
        return _domain_routes_asset_maintenance_routes.handle_history_export_tg(
            self, DIRECTORY=DIRECTORY, Path=Path,
            _decode_data_uri_image=_decode_data_uri_image, _fetch_comfy_binary=_fetch_comfy_binary, _resolve_archive_image_file=_resolve_archive_image_file,
            _resolve_download_image=_resolve_download_image, get_task=get_task, json=json,
            os=os, random=random, resolve_editable_file=resolve_editable_file,
            safe_basename=safe_basename, send_telegram=send_telegram, tempfile=tempfile,
            time=time,
        )

    def handle_delete_history_item(self):
        """删除单条历史记录，兼容新任务和旧 history.jsonl 记录"""
        return _domain_routes_asset_maintenance_routes.handle_delete_history_item(
            self, DIRECTORY=DIRECTORY, delete_task=delete_task,
            get_database_path=get_database_path, json=json, os=os,
            urllib=urllib,
        )
    
    def handle_delete_failed(self):
        """删除所有失败任务"""
        return _domain_routes_asset_maintenance_routes.handle_delete_failed(
            self, get_database_path=get_database_path,
        )
    
    def handle_history(self):
        """Compatibility entrypoint; resolve history query dependencies per request."""
        return _handle_history(
            self, page_int=_history_page_int,
            collect_tasks=_collect_renderable_history_tasks, format_task=_format_history_task)
    
    def handle_image(self, filename):
        """处理图片请求（archive directory, with legacy fallback）"""
        return _domain_routes_media_routes.handle_image(self, filename, _resolve_download_file=_resolve_download_file, mimetypes=mimetypes, os=os)

    def handle_image_import_url(self):
        """Download a public remote image for a canvas drag/drop import."""
        return _domain_routes_media_routes.handle_image_import_url(self, _download_remote_image_for_import=_download_remote_image_for_import, urllib=urllib)

    def handle_video(self, filename):
        """Serve an archived video with byte-range support for the canvas player."""
        return _domain_routes_media_routes.handle_video(
            self, filename, Path=Path,
            _ARCHIVE_VIDEO_EXTENSIONS=_ARCHIVE_VIDEO_EXTENSIONS, _resolve_archive_video_file=_resolve_archive_video_file, _resolve_download_file=_resolve_download_file,
            mimetypes=mimetypes, os=os, re=re,
            safe_basename=safe_basename, urllib=urllib,
        )

    def handle_archive_image(self, rel_path):
        """按 Obsidian 归档相对路径读取图片，避免同名文件冲突。"""
        return _domain_routes_media_routes.handle_archive_image(self, rel_path, _resolve_archive_image_file=_resolve_archive_image_file, mimetypes=mimetypes)

    def handle_archive_resource(self, rel_path):
        """Read a prompt TXT/Markdown sidecar from the archive roots only."""
        return _domain_routes_media_routes.handle_archive_resource(
            self, rel_path, _ARCHIVE_VIDEO_SIDECAR_MAX_BYTES=_ARCHIVE_VIDEO_SIDECAR_MAX_BYTES,
            _ARCHIVE_VIDEO_TEXT_EXTENSIONS=_ARCHIVE_VIDEO_TEXT_EXTENSIONS, _resolve_archive_resource_file=_resolve_archive_resource_file, urllib=urllib,
        )

    def handle_editable_file(self, rel_path):
        """Compatibility entrypoint; resolve the file reader per request."""
        return _handle_editable_file(self, rel_path, resolve_file=resolve_editable_file)

    def handle_editable_files(self, parsed):
        """Compatibility entrypoint; resolve listing dependencies per request."""
        return _handle_editable_files(
            self, parsed, list_files=list_editable_files, coerce_bool=_coerce_bool)

    def handle_editable_file_send(self):
        """Compatibility entrypoint; resolve file and Telegram dependencies per request."""
        return _handle_editable_file_send(
            self, resolve_file=resolve_editable_file, send_telegram=send_telegram)

    def handle_editable_file_delete(self):
        """Compatibility entrypoint; resolve the artifact deletion dependency per request."""
        return _handle_editable_file_delete(self, delete_item=delete_editable_item)

    def handle_source_image(self, rel_path):
        """读取 Source_Image 下的远程源本地图片。"""
        return _domain_routes_media_routes.handle_source_image(self, rel_path, mimetypes=mimetypes, resolve_source_image=resolve_source_image)

    def handle_thumb(self, parsed):
        """Generate and serve an authenticated WebP thumbnail for local media."""
        return _domain_routes_media_routes.handle_thumb(
            self, parsed, _ARCHIVE_VIDEO_EXTENSIONS=_ARCHIVE_VIDEO_EXTENSIONS,
            _resolve_archive_image_file=_resolve_archive_image_file, _resolve_archive_video_file=_resolve_archive_video_file, _resolve_download_file=_resolve_download_file,
            ensure_video_webp_thumbnail=ensure_video_webp_thumbnail, ensure_webp_thumbnail=ensure_webp_thumbnail, parse_thumb_request=parse_thumb_request,
            resolve_media_path=resolve_media_path, resolve_source_image=resolve_source_image, shutil=shutil,
            urllib=urllib,
        )
    
    def handle_google_output(self, filename):
        """处理 google_outputs 目录的图片请求"""
        return _domain_routes_media_routes.handle_google_output(self, filename, DIRECTORY=DIRECTORY, os=os)
    
    def handle_gpt_output(self, filename):
        """处理 gpt_outputs 目录的图片请求"""
        return _domain_routes_media_routes.handle_gpt_output(
            self, filename, DIRECTORY=DIRECTORY,
            ensure_gpt_preview_image=ensure_gpt_preview_image, os=os, safe_basename=safe_basename,
        )
    
    def log_message(self, format, *args):
        """自定义日志格式"""
        return _domain_routes_http_responses.log_message(self, format, *args, re=re, time=time)

def send_status_notification(task_id, message, icon='🔄'):
    """发送状态通知到 Telegram"""
    return _domain_services_telegram_notifications.send_status_notification(
        task_id, message, icon,
        _load_telegram_notify_config=_load_telegram_notify_config, requests=requests,
    )

def _is_retryable_generation_error(error_msg):
    """判断是否属于可托底错误（网络/超时/服务暂时不可用）"""
    return _domain_services_google_generation._is_retryable_generation_error(error_msg)


def _map_quality_to_gpt_resolution(quality):
    return _domain_services_google_generation._map_quality_to_gpt_resolution(quality)


def _should_fallback_to_gpt(params, primary_error_msg):
    """skill 调用时是否触发 GPT 托底"""
    return _domain_services_google_generation._should_fallback_to_gpt(params, primary_error_msg, _is_retryable_generation_error=_is_retryable_generation_error)


def process_task(task_id, prompt, params):
    """后台线程：处理任务（skill 调用支持 GPT 托底）"""
    return _domain_services_google_generation.process_task(
        task_id, prompt, params,
        DEFAULT_GOOGLE_IMAGE_MODEL=DEFAULT_GOOGLE_IMAGE_MODEL, Path=Path, _coerce_google_max_tokens=_coerce_google_max_tokens,
        _coerce_google_output_controls=_coerce_google_output_controls, _effective_image_ratio=_effective_image_ratio, _finalize_generation_task=_finalize_generation_task,
        _is_generic_19_fidelity_prompt=_is_generic_19_fidelity_prompt, _map_quality_to_gpt_resolution=_map_quality_to_gpt_resolution, _merge_task_params=_merge_task_params,
        _record_generation_event=_record_generation_event, _result_image_filenames=_result_image_filenames, _should_fallback_to_gpt=_should_fallback_to_gpt,
        _start_generation_audit=_start_generation_audit, _translate_generation_failure=_translate_generation_failure, daily_output_dir=daily_output_dir,
        generate_image=generate_image, google_pool_generate=_google_pool_provider.generate, generate_image_gpt_pool=generate_image_gpt_pool, os=os,
        save_image=save_image, save_thumbnail=save_thumbnail, send_status_notification=send_status_notification,
        send_telegram=send_telegram, send_telegram_result=send_telegram_result, time=time,
        update_task_fields=update_task_fields, update_task_status=update_task_status, write_obsidian_prompt_sidecar=write_obsidian_prompt_sidecar,
    )
def process_edit_task(task_id, prompt, images, params):
    """后台线程：处理编辑任务（skill 调用支持 GPT 托底）"""
    return _domain_services_google_generation.process_edit_task(
        task_id, prompt, images,
        params, DEFAULT_GOOGLE_IMAGE_MODEL=DEFAULT_GOOGLE_IMAGE_MODEL, Path=Path,
        _coerce_google_max_tokens=_coerce_google_max_tokens, _coerce_google_output_controls=_coerce_google_output_controls, _effective_image_ratio=_effective_image_ratio,
        _finalize_generation_task=_finalize_generation_task, _is_generic_19_fidelity_prompt=_is_generic_19_fidelity_prompt, _map_quality_to_gpt_resolution=_map_quality_to_gpt_resolution,
        _merge_task_params=_merge_task_params, _record_generation_event=_record_generation_event, _result_image_filenames=_result_image_filenames,
        _should_fallback_to_gpt=_should_fallback_to_gpt, _start_generation_audit=_start_generation_audit, _translate_generation_failure=_translate_generation_failure,
        daily_output_dir=daily_output_dir, google_pool_edit=_google_pool_provider.edit, generate_image_gpt_pool=generate_image_gpt_pool, json=json,
        os=os, save_image=save_image, save_thumbnail=save_thumbnail,
        send_status_notification=send_status_notification, send_telegram=send_telegram, send_telegram_result=send_telegram_result,
        time=time, update_task_fields=update_task_fields, update_task_status=update_task_status,
        write_obsidian_prompt_sidecar=write_obsidian_prompt_sidecar,
    )

def _annotate_gpt_route_result(result, route_resolution, *, requested_route, requested_model, requested_reasoning_effort):
    return _domain_services_provider_routing._annotate_gpt_route_result(
        result, route_resolution, requested_route=requested_route,
        requested_model=requested_model, requested_reasoning_effort=requested_reasoning_effort,
    )


def _generate_gpt_with_pool_fallback(task_id, prompt, ratio, resolution, quality, image_count=1, moderation='auto', prompt_mode='smart', main_model=None, reasoning_effort=None, gpt_provider_route='codex'):
    """Run Codex with managed OAuth preferred, then local auth, then account-pool fallback."""
    return _domain_services_provider_routing._generate_gpt_with_pool_fallback(
        task_id, prompt, ratio,
        resolution, quality, image_count,
        moderation, prompt_mode, main_model,
        reasoning_effort, gpt_provider_route, ChatgptPoolGenerationError=ChatgptPoolGenerationError,
        DEFAULT_POOL_MODEL=DEFAULT_POOL_MODEL, _annotate_gpt_route_result=_annotate_gpt_route_result, _append_task_route_trace=_append_task_route_trace,
        _coerce_gpt_main_model=_coerce_gpt_main_model, _coerce_gpt_provider_route=_coerce_gpt_provider_route, _coerce_gpt_provider_total_timeout=_coerce_gpt_provider_total_timeout,
        _coerce_gpt_reasoning_effort=_coerce_gpt_reasoning_effort, _effective_prompt_mode=_effective_prompt_mode, _format_gpt_pool_error=_format_gpt_pool_error,
        _format_gpt_provider_error=_format_gpt_provider_error, _is_generic_19_fidelity_prompt=_is_generic_19_fidelity_prompt, _is_task_canceled=_is_task_canceled,
        _make_gpt_image_progress_callback=_make_gpt_image_progress_callback, _make_gpt_pool_wait_callback=_make_gpt_pool_wait_callback, _make_gpt_provider_wait_callback=_make_gpt_provider_wait_callback,
        _prepare_chatgpt_pool_generation_prompt=_prepare_chatgpt_pool_generation_prompt, _prepare_web_search_generation_prompt=_prepare_web_search_generation_prompt, _resolve_codex_provider_env=_resolve_codex_provider_env,
        generate_image_gpt_codex=generate_image_gpt_codex, generate_image_gpt_pool=generate_image_gpt_pool, get_chatgpt_pool_config=get_chatgpt_pool_config,
        get_task=get_task, resolve_route_model=resolve_route_model, send_status_notification=send_status_notification,
        time=time, update_task_status=update_task_status,
    )


def _make_gpt_image_progress_callback(task_id, requested_count):
    return _domain_services_generation_progress._make_gpt_image_progress_callback(
        task_id, requested_count, _is_task_canceled=_is_task_canceled,
        _result_image_filenames=_result_image_filenames, json=json, update_task_status=update_task_status,
    )


def _make_gpt_provider_wait_callback(task_id):
    return _domain_services_generation_progress._make_gpt_provider_wait_callback(task_id, time=time, update_task_fields=update_task_fields)


def _make_gpt_pool_wait_callback(task_id):
    return _domain_services_generation_progress._make_gpt_pool_wait_callback(task_id, time=time, update_task_fields=update_task_fields)


def _format_download_bytes(value):
    return _domain_services_generation_progress._format_download_bytes(value)


def _third_party_download_progress_percent(event):
    return _domain_services_generation_progress._third_party_download_progress_percent(event)


def _make_third_party_download_progress_callback(task_id):
    return _domain_services_generation_progress._make_third_party_download_progress_callback(
        task_id, _format_download_bytes=_format_download_bytes, _is_task_canceled=_is_task_canceled,
        _merge_task_params=_merge_task_params, _record_generation_event=_record_generation_event, _third_party_download_progress_percent=_third_party_download_progress_percent,
        time=time, update_task_status=update_task_status,
    )


def _is_task_canceled(task_id):
    return _domain_services_task_tracking._is_task_canceled(task_id, get_task=get_task)


def _finish_canceled_gpt_task(task_id, result=None):
    return _domain_services_task_tracking._finish_canceled_gpt_task(
        task_id, result, _finalize_generation_task=_finalize_generation_task,
        _generation_last_run_id=_generation_last_run_id, _generation_run_route=_generation_run_route, _record_generation_event=_record_generation_event,
        _result_image_filenames=_result_image_filenames, get_task=get_task, send_status_notification=send_status_notification,
    )


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
    """后台线程：PPT 走账号池，PSD 可走模型原生图片编辑线路。"""
    return _domain_services_editable_generation.process_gpt_editable_file_task(
        task_id, kind, prompt,
        base64_images, prompt_mode, gpt_provider_route,
        archive_enabled, telegram_enabled, _annotate_gpt_route_result=_annotate_gpt_route_result,
        _append_task_route_trace=_append_task_route_trace, _coerce_gpt_main_model=_coerce_gpt_main_model, _coerce_gpt_moderation=_coerce_gpt_moderation,
        _coerce_gpt_provider_route=_coerce_gpt_provider_route, _coerce_gpt_provider_total_timeout=_coerce_gpt_provider_total_timeout, _coerce_gpt_reasoning_effort=_coerce_gpt_reasoning_effort,
        _coerce_gpt_resolution=_coerce_gpt_resolution, _coerce_gpt_task_type=_coerce_gpt_task_type, _coerce_image_ratio=_coerce_image_ratio,
        _finalize_generation_task=_finalize_generation_task, _format_gpt_failure_error=_format_gpt_failure_error, _format_gpt_pool_error=_format_gpt_pool_error,
        _format_gpt_provider_error=_format_gpt_provider_error, _is_task_canceled=_is_task_canceled, _make_gpt_provider_wait_callback=_make_gpt_provider_wait_callback,
        _make_third_party_download_progress_callback=_make_third_party_download_progress_callback, _merge_task_params=_merge_task_params, _record_generation_event=_record_generation_event,
        _resolve_codex_provider_env=_resolve_codex_provider_env, _start_generation_audit=_start_generation_audit, _translate_generation_failure=_translate_generation_failure,
        generate_editable_file_gpt_pool=generate_editable_file_gpt_pool, generate_editable_psd_native=generate_editable_psd_native, get_chatgpt_pool_config=get_chatgpt_pool_config,
        get_task=get_task, resolve_route_model=resolve_route_model, save_editable_artifacts=save_editable_artifacts,
        send_status_notification=send_status_notification, send_telegram=send_telegram, update_task=update_task,
        update_task_status=update_task_status,
    )

def process_gpt_task(task_id, prompt, ratio, resolution, quality='auto', image_count=1, moderation='auto', prompt_mode='smart', main_model=None, reasoning_effort=None, gpt_provider_route='codex', use_third_party_api=False, archive_enabled=True, telegram_enabled=True):
    """后台线程：处理 GPT 任务（Codex 托管授权优先，再账号池托底）"""
    return _domain_services_gpt_generation.process_gpt_task(
        task_id, prompt, ratio,
        resolution, quality, image_count,
        moderation, prompt_mode, main_model,
        reasoning_effort, gpt_provider_route, use_third_party_api,
        archive_enabled, telegram_enabled, _annotate_gpt_route_result=_annotate_gpt_route_result,
        _append_task_route_trace=_append_task_route_trace, _augment_result_resolution_metadata=_augment_result_resolution_metadata, _chatgpt_pool_failure_metadata=_chatgpt_pool_failure_metadata,
        _coerce_bool=_coerce_bool, _coerce_gpt_main_model=_coerce_gpt_main_model, _coerce_gpt_provider_route=_coerce_gpt_provider_route,
        _coerce_gpt_provider_total_timeout=_coerce_gpt_provider_total_timeout, _coerce_gpt_reasoning_effort=_coerce_gpt_reasoning_effort, _coerce_prompt_mode=_coerce_prompt_mode,
        _coerce_use_third_party_api=_coerce_use_third_party_api, _effective_image_ratio=_effective_image_ratio, _effective_prompt_mode=_effective_prompt_mode,
        _finalize_generation_task=_finalize_generation_task, _finish_canceled_gpt_task=_finish_canceled_gpt_task, _format_gpt_failure_error=_format_gpt_failure_error,
        _format_gpt_pool_error=_format_gpt_pool_error, _generate_gpt_with_pool_fallback=_generate_gpt_with_pool_fallback, _gpt_route_uses_third_party=_gpt_route_uses_third_party,
        _is_generic_19_fidelity_prompt=_is_generic_19_fidelity_prompt, _is_task_canceled=_is_task_canceled, _make_third_party_download_progress_callback=_make_third_party_download_progress_callback,
        _merge_task_params=_merge_task_params, _prepare_web_search_generation_prompt=_prepare_web_search_generation_prompt, _record_generation_event=_record_generation_event,
        _result_image_filenames=_result_image_filenames, _start_generation_audit=_start_generation_audit, _translate_generation_failure=_translate_generation_failure,
        generate_image_third_party=generate_image_third_party, get_task=get_task, os=os,
        resolve_route_model=resolve_route_model, send_status_notification=send_status_notification, send_telegram_result=send_telegram_result,
        time=time, update_task_status=update_task_status,
    )

def process_gpt_edit_task(task_id, prompt, images, ratio, resolution, quality='auto', moderation='auto', mask=None, prompt_mode='smart', main_model=None, reasoning_effort=None, use_third_party_api=False, gpt_provider_route='codex', archive_enabled=True, telegram_enabled=True):
    """后台线程：处理 GPT 图像编辑任务（本地 Codex provider）。"""
    return _domain_services_gpt_generation.process_gpt_edit_task(
        task_id, prompt, images,
        ratio, resolution, quality,
        moderation, mask, prompt_mode,
        main_model, reasoning_effort, use_third_party_api,
        gpt_provider_route, archive_enabled, telegram_enabled,
        _annotate_gpt_route_result=_annotate_gpt_route_result, _append_task_route_trace=_append_task_route_trace, _augment_result_resolution_metadata=_augment_result_resolution_metadata,
        _coerce_bool=_coerce_bool, _coerce_gpt_main_model=_coerce_gpt_main_model, _coerce_gpt_provider_route=_coerce_gpt_provider_route,
        _coerce_gpt_provider_total_timeout=_coerce_gpt_provider_total_timeout, _coerce_gpt_reasoning_effort=_coerce_gpt_reasoning_effort, _coerce_use_third_party_api=_coerce_use_third_party_api,
        _effective_image_ratio=_effective_image_ratio, _effective_prompt_mode=_effective_prompt_mode, _finalize_generation_task=_finalize_generation_task,
        _finish_canceled_gpt_task=_finish_canceled_gpt_task, _format_gpt_failure_error=_format_gpt_failure_error, _format_gpt_pool_error=_format_gpt_pool_error,
        _format_gpt_provider_error=_format_gpt_provider_error, _gpt_route_uses_third_party=_gpt_route_uses_third_party, _is_generic_19_fidelity_prompt=_is_generic_19_fidelity_prompt,
        _is_task_canceled=_is_task_canceled, _make_gpt_provider_wait_callback=_make_gpt_provider_wait_callback, _make_third_party_download_progress_callback=_make_third_party_download_progress_callback,
        _merge_task_params=_merge_task_params, _record_generation_event=_record_generation_event, _resolve_codex_provider_env=_resolve_codex_provider_env,
        _result_image_filenames=_result_image_filenames, _start_generation_audit=_start_generation_audit, _translate_generation_failure=_translate_generation_failure,
        edit_image_gpt_codex=edit_image_gpt_codex, edit_image_gpt_pool=edit_image_gpt_pool, edit_image_third_party=edit_image_third_party,
        get_chatgpt_pool_config=get_chatgpt_pool_config, get_task=get_task, os=os,
        resolve_route_model=resolve_route_model, send_status_notification=send_status_notification, send_telegram_result=send_telegram_result,
        time=time, update_task_status=update_task_status,
    )

def process_custom_task(task_id, prompt, ratio, resolution, quality='auto', moderation='auto'):
    """兼容 custom 路由，复用 GPT provider + fallback 流程。"""
    return _domain_services_gpt_generation.process_custom_task(task_id, prompt, ratio, resolution, quality, moderation, process_gpt_task=process_gpt_task)


def run_server():
    """启动服务器"""
    return _domain_services_server_lifecycle.run_server(
        APP_DATA_DIR=APP_DATA_DIR, PORT=PORT, RequestHandler=RequestHandler,
        SERVER_CONFIG=SERVER_CONFIG, SERVER_HOST=SERVER_HOST, SOURCE_IMAGE_DIR=SOURCE_IMAGE_DIR,
        STYLE_PRESETS_FILE=STYLE_PRESETS_FILE, _ensure_db_file_permissions=_ensure_db_file_permissions, _init_generation_semaphore=_init_generation_semaphore,
        _validate_public_mode_password=_validate_public_mode_password, cancel_orphan_prompt_source_runs=cancel_orphan_prompt_source_runs, fail_stale_processing_tasks=fail_stale_processing_tasks,
        get_agent_runtime=get_agent_runtime, init_agent_store=init_agent_store, init_asset_store=init_asset_store,
        init_db=init_db, init_layout_draft_store=init_layout_draft_store, init_prompt_library_store=init_prompt_library_store,
        recover_cyimg_tasks=_CYIMG_SERVICE.recover,
        recover_krea2_tasks=_KREA2_SERVICE.recover,
        recover_qwen21_tasks=_QWEN21_SERVICE.recover,
        init_prompt_source_store=init_prompt_source_store, socketserver=socketserver,
    )

if __name__ == '__main__':
    run_server()
