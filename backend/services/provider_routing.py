"""Codex, account-pool and third-party fallback orchestration.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _annotate_gpt_route_result(
    result,
    route_resolution,
    *,
    requested_route,
    requested_model,
    requested_reasoning_effort,
):
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


def _generate_gpt_with_pool_fallback(
    task_id,
    prompt,
    ratio,
    resolution,
    quality,
    image_count=1,
    moderation='auto',
    prompt_mode='smart',
    main_model=None,
    reasoning_effort=None,
    gpt_provider_route='codex',
    *,
    ChatgptPoolGenerationError,
    DEFAULT_POOL_MODEL,
    _annotate_gpt_route_result,
    _append_task_route_trace,
    _coerce_gpt_main_model,
    _coerce_gpt_provider_route,
    _coerce_gpt_provider_total_timeout,
    _coerce_gpt_reasoning_effort,
    _effective_prompt_mode,
    _format_gpt_pool_error,
    _format_gpt_provider_error,
    _is_generic_19_fidelity_prompt,
    _is_task_canceled,
    _make_gpt_image_progress_callback,
    _make_gpt_pool_wait_callback,
    _make_gpt_provider_wait_callback,
    _prepare_chatgpt_pool_generation_prompt,
    _prepare_web_search_generation_prompt,
    _resolve_codex_provider_env,
    generate_image_gpt_codex,
    generate_image_gpt_pool,
    get_chatgpt_pool_config,
    get_task,
    resolve_route_model,
    send_status_notification,
    time,
    update_task_status,
):
    """Run Codex with managed OAuth preferred, then local auth, then account-pool fallback."""
    primary_error = None
    pool_error = None
    pool_result = None
    prompt = str(prompt or '')
    fidelity_locked = _is_generic_19_fidelity_prompt(prompt)
    prompt_mode = _effective_prompt_mode(prompt, prompt_mode)
    prompt_meta = {
        'prompt_fidelity_locked': True,
        'prompt_optimized': False,
        'prompt_optimized_by': 'generic_19_fidelity_bundle',
    } if fidelity_locked else {}
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
