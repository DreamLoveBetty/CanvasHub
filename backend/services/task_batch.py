"""Batch task creation, ordered/parallel scheduling and batch control.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _batch_prompt_items(data, *, re):
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


def _batch_task_id(provider, params, index, *, _batch_task_type, _retry_task_id_prefix, random, time):
    task_type = _batch_task_type(provider, params)
    prefix = _retry_task_id_prefix(task_type, params)
    return f"{prefix}_{int(time.time())}_{random.randint(1000, 9999)}_{index + 1}"


def _batch_task_type(provider, params, *, _coerce_gpt_task_type):
    if provider == 'google':
        return 'google-gen'
    if provider == 'gpt':
        kind = _coerce_gpt_task_type(params.get('gptTaskType') or params.get('task_type'))
        return 'gpt-file' if kind != 'image' else 'gpt'
    return provider


def _make_batch_task_params(
    provider,
    incoming_params,
    prompt,
    batch_id,
    index,
    total,
    lineage=None,
    *,
    DEFAULT_GOOGLE_IMAGE_MODEL,
    TaskRetryError,
    _coerce_bool,
    _coerce_google_max_tokens,
    _coerce_google_quality,
    _coerce_google_temperature,
    _coerce_gpt_image_count,
    _coerce_gpt_main_model,
    _coerce_gpt_moderation,
    _coerce_gpt_provider_route,
    _coerce_gpt_quality,
    _coerce_gpt_reasoning_effort,
    _coerce_gpt_resolution,
    _coerce_gpt_task_type,
    _coerce_model,
    _coerce_prompt_mode,
    _coerce_use_third_party_api,
    _effective_image_ratio,
    _gpt_route_uses_third_party,
    time,
):
    incoming_params = incoming_params if isinstance(incoming_params, dict) else {}
    if provider == 'google':
        google_route = incoming_params.get('google_provider_route', 'third_party')
        if google_route not in ('third_party', 'google_pool'):
            raise TaskRetryError('Google 线路无效')
        archive_enabled = _coerce_bool(incoming_params.get('archiveEnabled', incoming_params.get('archive_enabled')), True)
        telegram_enabled = _coerce_bool(incoming_params.get('telegramEnabled', incoming_params.get('telegram_enabled')), True)
        params = {
            'ratio': _effective_image_ratio(prompt, incoming_params.get('ratio'), '1:1'),
            'quality': _coerce_google_quality(incoming_params.get('resolution', incoming_params.get('quality', '2k')), '2k'),
            'model': _coerce_model(incoming_params.get('model', DEFAULT_GOOGLE_IMAGE_MODEL)),
            'max_tokens': _coerce_google_max_tokens(incoming_params.get('maxTokens', incoming_params.get('max_tokens'))),
            'archive_enabled': archive_enabled,
            'telegram_enabled': telegram_enabled,
        }
        params['google_provider_route'] = google_route
        if google_route == 'google_pool' and params['model'].removesuffix('-preview') not in (
            'gemini-3-pro-image', 'gemini-3.1-pro-image', 'gemini-3-flash-image', 'gemini-3.1-flash-image'
        ):
            raise TaskRetryError('Google OAuth 线路仅支持 Gemini 图像模型')
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
            'ratio': _effective_image_ratio(prompt, incoming_params.get('ratio'), '1:1'),
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


def _create_batch_tasks(
    provider,
    prompts,
    params,
    lineage=None,
    *,
    TaskRetryError,
    _batch_task_id,
    _batch_task_type,
    _coerce_gpt_task_type,
    _make_batch_task_params,
    create_task,
    random,
    time,
):
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


def _run_batch_task(
    task,
    *,
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
    process_gpt_editable_file_task,
    process_gpt_task,
    process_task,
    update_task,
):
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


def _batch_task_uses_chatgpt_pool(task, *, _coerce_gpt_provider_route, _coerce_use_third_party_api):
    if not isinstance(task, dict) or task.get('type') != 'gpt':
        return False
    params = task.get('params') if isinstance(task.get('params'), dict) else {}
    if _coerce_use_third_party_api(params.get('use_third_party_api'), params.get('useThirdPartyApi')):
        return False
    return _coerce_gpt_provider_route(params.get('gpt_provider_route', 'codex')) == 'chatgpt_pool'


def _batch_task_requested_image_count(task, *, _coerce_gpt_image_count):
    params = task.get('params') if isinstance(task.get('params'), dict) else {}
    return _coerce_gpt_image_count({'image_count': params.get('image_count')}, task.get('prompt') or '')


def _batch_chatgpt_pool_parallel_limit(
    tasks,
    *,
    _batch_task_requested_image_count,
    _batch_task_uses_chatgpt_pool,
    _collect_chatgpt_pool_status,
    _current_generation_limit,
):
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


def _wait_acquire_generation_slot_for_batch(batch_id, *, _GENERATION_SEMAPHORE, get_batch_control, time):
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


def _run_batch_task_guarded(batch_id, task, *, _run_batch_task, get_batch_control, get_task, time, update_task):
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


def _run_batch_tasks_parallel(
    batch_id,
    tasks,
    parallel_limit,
    *,
    _release_generation_slot,
    _run_batch_task_guarded,
    _wait_acquire_generation_slot_for_batch,
    queue,
    threading,
):
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


def process_batch_tasks(
    batch_id,
    tasks,
    *,
    _batch_chatgpt_pool_parallel_limit,
    _run_batch_task_guarded,
    _run_batch_tasks_parallel,
    cancel_batch_queued_tasks,
    get_batch_control,
):
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


def _batch_tasks(batch_id, *, get_all_tasks):
    tasks = [
        task for task in get_all_tasks(limit=5000, offset=0)
        if isinstance(task.get('params'), dict) and task['params'].get('batch_id') == batch_id
    ]
    tasks.sort(key=lambda task: int((task.get('params') or {}).get('batch_index') or 0))
    return tasks


def get_batch_control(batch_id, *, _batch_tasks):
    for task in _batch_tasks(batch_id):
        control = str((task.get('params') or {}).get('batch_control') or '').strip().lower()
        if control:
            return control
    return 'running'


def set_batch_control(batch_id, control, *, _batch_tasks, copy, json, time, update_task_fields):
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


def cancel_batch_queued_tasks(batch_id, *, _batch_tasks, time, update_task_fields):
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


def get_batch_summary(batch_id, *, FAILED_RETRY_STATUSES, _batch_tasks, _format_history_task, get_batch_control):
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
