"""Generation audit events, outcome classification and task finalization.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations

from .image_preview import image_url


def _merge_task_params(task_id, patch, *, get_task, json, update_task_fields):
    if not isinstance(patch, dict) or not patch:
        return
    task = get_task(task_id) or {}
    params = task.get('params') if isinstance(task.get('params'), dict) else {}
    params.update({k: v for k, v in patch.items() if v not in (None, '')})
    update_task_fields(task_id, params=json.dumps(params, ensure_ascii=False))


def _append_task_route_trace(
    task_id,
    route,
    status,
    message='',
    *,
    extra,
    _classify_route_error,
    _record_generation_event,
    get_task,
    json,
    time,
    update_task_fields,
):
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


def _generation_run_task(task_id, *, get_task):
    task = get_task(task_id) or {}
    params = task.get('params') if isinstance(task.get('params'), dict) else {}
    return task, params


def _generation_last_run_id(task_id, *, _generation_run_task):
    task, params = _generation_run_task(task_id)
    run_id = str(task.get('last_run_id') or params.get('last_run_id') or '').strip()
    return run_id


def _record_generation_event(
    task_id,
    event_type,
    message='',
    stage='',
    severity='info',
    payload=None,
    *,
    _generation_last_run_id,
    record_generation_event,
):
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


def _generation_run_route(task_id, fallback='', *, _generation_run_task):
    task, params = _generation_run_task(task_id)
    route = (
        params.get('gpt_provider_route')
        or params.get('provider_route')
        or task.get('type')
        or fallback
    )
    return str(route or fallback or '').strip()


def _start_generation_audit(
    task_id,
    task_type,
    prompt,
    params,
    *,
    provider='',
    route='',
    stage='preparing',
    parent_run_id='',
    _record_generation_event,
    start_generation_run,
):
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


def _translate_generation_failure(
    task_id,
    raw_error,
    *,
    provider='',
    route='',
    task_type='',
    stage='',
    exception_name='',
    _record_generation_event,
    translate_generation_error,
):
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
    finish_generation_run,
    json,
    update_task,
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


def _status_response_task(
    task,
    *,
    H3_VIDEO_TASK_TYPE,
    _history_task_result_files,
    _public_h3_task_params,
    safe_basename,
    urllib,
):
    task = dict(task or {})
    is_video = task.get('type') in {H3_VIDEO_TASK_TYPE, 'cyimg-video'}
    params = task.get('params') if isinstance(task.get('params'), dict) else {}
    if task.get('type') == H3_VIDEO_TASK_TYPE:
        params = _public_h3_task_params(params)
        task['params'] = params
    provider_failure = params.get('provider_failure') if isinstance(params.get('provider_failure'), dict) else {}
    for key in ('timed_out', 'partial_errors', 'completed_image_count', 'requested_image_count'):
        if provider_failure.get(key) is not None:
            task[key] = provider_failure.get(key)
    result_files, primary_output = _history_task_result_files(task)
    if result_files:
        task['result_file'] = primary_output
        task['result_files'] = result_files
        task['output_files'] = result_files
        if is_video:
            video_paths = [f"/video/{urllib.parse.quote(safe_basename(name))}" for name in result_files]
            task['image_paths'] = []
            task['image_count'] = 0
            task['video_paths'] = video_paths
            task['video_path'] = video_paths[0] if video_paths else ''
            task['video_count'] = len(video_paths)
            task['video_metadata'] = {
                key: params.get(key)
                for key in ('width', 'height', 'fps', 'frame_count', 'duration_seconds', 'video_size_bytes', 'seed', 'elapsed_seconds', 'acceleration')
                if params.get(key) is not None
            }
        elif task.get('type') == 'gpt-file':
            task['image_paths'] = []
            params = task.get('params') if isinstance(task.get('params'), dict) else {}
            if isinstance(params.get('file_manifest'), dict):
                task['file_manifest'] = params.get('file_manifest')
            task['artifact_type'] = params.get('artifact_type') or params.get('task_type')
        else:
            task['image_paths'] = [f"/gpt_outputs/{name}" for name in result_files] if task.get('type') in ('gpt', 'gpt-edit') else [image_url(name) for name in result_files]
        # Keep the legacy H3 status count contract; Cyimg video is a new task
        # type and should not report its video result as an image.
        task['image_count'] = 0 if task.get('type') == 'cyimg-video' else len(result_files)
    else:
        task.setdefault('result_files', [])
        task.setdefault('output_files', [])
        task.setdefault('image_paths', [])
        task.setdefault('image_count', 0)
        if is_video:
            task.setdefault('video_paths', [])
            task.setdefault('video_path', '')
            task.setdefault('video_count', 0)
    task.setdefault('display_error', task.get('error') or '')
    task.setdefault('error_code', '')
    task.setdefault('error_category', '')
    task.setdefault('raw_error', task.get('error') or '')
    task.setdefault('last_run_id', '')
    task.setdefault('run_count', 0)
    return task


def _missing_task_payload(task_id, *, time):
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


def _is_task_canceled(task_id, *, get_task):
    task = get_task(task_id)
    return str(task.get('status') if task else '') == 'canceled'


def _finish_canceled_gpt_task(
    task_id,
    result=None,
    *,
    _finalize_generation_task,
    _generation_last_run_id,
    _generation_run_route,
    _record_generation_event,
    _result_image_filenames,
    get_task,
    send_status_notification,
):
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
