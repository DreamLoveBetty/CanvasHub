"""Retry validation, parameter copying and existing provider dispatch.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


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


def _make_retry_task_id(task_type, params=None, *, _retry_task_id_prefix, random, time):
    return f"{_retry_task_id_prefix(task_type, params)}_{int(time.time())}_{random.randint(1000, 9999)}"


def _copy_retry_params(original_task, new_task_id, *, RETRY_PARAM_RESULT_KEYS, copy, time):
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


def _validate_retry_payload(task_type, params, *, TaskRetryError, _coerce_gpt_task_type):
    if task_type != 'gpt-file':
        return
    kind = _coerce_gpt_task_type(params.get('task_type') or params.get('artifact_type'))
    if kind not in ('ppt', 'psd'):
        raise TaskRetryError('这个 GPT 文件任务缺少可重跑的文件类型。')
    if kind == 'psd':
        raise TaskRetryError('PSD 任务依赖原始参考图，当前历史记录未保存原图，暂不能直接重跑。')


def _start_retry_thread(
    task_type,
    task_id,
    prompt,
    params,
    *,
    GenerationQueueFullError,
    TaskRetryError,
    _coerce_bool,
    _coerce_gpt_image_count,
    _coerce_gpt_main_model,
    _coerce_gpt_moderation,
    _coerce_gpt_provider_route,
    _coerce_gpt_quality,
    _coerce_gpt_reasoning_effort,
    _coerce_gpt_resolution,
    _coerce_gpt_task_type,
    _coerce_image_ratio,
    _coerce_prompt_mode,
    _coerce_use_third_party_api,
    _generation_busy_message,
    _is_gpt_image_retry,
    _start_generation_thread,
    process_custom_task,
    process_gpt_editable_file_task,
    process_gpt_task,
    process_task,
    update_task,
):
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


def retry_failed_task(
    original_task,
    *,
    FAILED_RETRY_STATUSES,
    RETRYABLE_TASK_TYPES,
    TaskRetryError,
    _copy_retry_params,
    _make_retry_task_id,
    _start_retry_thread,
    _validate_retry_payload,
    create_task,
    get_task,
):
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
