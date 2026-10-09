"""GPT image generation and editing worker lifecycles.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def process_gpt_task(
    task_id,
    prompt,
    ratio,
    resolution,
    quality='auto',
    image_count=1,
    moderation='auto',
    prompt_mode='smart',
    main_model=None,
    reasoning_effort=None,
    gpt_provider_route='codex',
    use_third_party_api=False,
    archive_enabled=True,
    telegram_enabled=True,
    *,
    _annotate_gpt_route_result,
    _append_task_route_trace,
    _augment_result_resolution_metadata,
    _chatgpt_pool_failure_metadata,
    _coerce_bool,
    _coerce_gpt_main_model,
    _coerce_gpt_provider_route,
    _coerce_gpt_provider_total_timeout,
    _coerce_gpt_reasoning_effort,
    _coerce_prompt_mode,
    _coerce_use_third_party_api,
    _effective_image_ratio,
    _effective_prompt_mode,
    _finalize_generation_task,
    _finish_canceled_gpt_task,
    _format_gpt_failure_error,
    _format_gpt_pool_error,
    _generate_gpt_with_pool_fallback,
    _gpt_route_uses_third_party,
    _is_generic_19_fidelity_prompt,
    _is_task_canceled,
    _make_third_party_download_progress_callback,
    _merge_task_params,
    _prepare_web_search_generation_prompt,
    _record_generation_event,
    _result_image_filenames,
    _start_generation_audit,
    _translate_generation_failure,
    generate_image_third_party,
    get_task,
    os,
    resolve_route_model,
    send_status_notification,
    send_telegram_result,
    time,
    update_task_status,
):
    """后台线程：处理 GPT 任务（Codex 托管授权优先，再账号池托底）"""
    run_id = ''
    task_kind = 'gpt'
    task_provider = 'codex'
    task_route = 'codex'
    try:
        ratio = _effective_image_ratio(prompt, ratio, '1:1')
        prompt_mode = _effective_prompt_mode(prompt, prompt_mode)
        requested_main_model = _coerce_gpt_main_model(main_model)
        main_model = requested_main_model
        requested_reasoning_effort = _coerce_gpt_reasoning_effort(reasoning_effort)
        reasoning_effort = requested_reasoning_effort
        gpt_provider_route = _coerce_gpt_provider_route(gpt_provider_route)
        use_third_party_api = _gpt_route_uses_third_party(gpt_provider_route) or _coerce_use_third_party_api(use_third_party_api)
        archive_enabled = _coerce_bool(archive_enabled, True)
        telegram_enabled = _coerce_bool(telegram_enabled, True)
        _merge_task_params(task_id, {
            'ratio': ratio,
            'archive_enabled': archive_enabled,
            'telegram_enabled': telegram_enabled,
            **({
                'prompt_fidelity_locked': True,
                'source_ratio_locked': True,
            } if _is_generic_19_fidelity_prompt(prompt) else {}),
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


def process_gpt_edit_task(
    task_id,
    prompt,
    images,
    ratio,
    resolution,
    quality='auto',
    moderation='auto',
    mask=None,
    prompt_mode='smart',
    main_model=None,
    reasoning_effort=None,
    use_third_party_api=False,
    gpt_provider_route='codex',
    archive_enabled=True,
    telegram_enabled=True,
    *,
    _annotate_gpt_route_result,
    _append_task_route_trace,
    _augment_result_resolution_metadata,
    _coerce_bool,
    _coerce_gpt_main_model,
    _coerce_gpt_provider_route,
    _coerce_gpt_provider_total_timeout,
    _coerce_gpt_reasoning_effort,
    _coerce_use_third_party_api,
    _effective_image_ratio,
    _effective_prompt_mode,
    _finalize_generation_task,
    _finish_canceled_gpt_task,
    _format_gpt_failure_error,
    _format_gpt_pool_error,
    _format_gpt_provider_error,
    _gpt_route_uses_third_party,
    _is_generic_19_fidelity_prompt,
    _is_task_canceled,
    _make_gpt_provider_wait_callback,
    _make_third_party_download_progress_callback,
    _merge_task_params,
    _record_generation_event,
    _resolve_codex_provider_env,
    _result_image_filenames,
    _start_generation_audit,
    _translate_generation_failure,
    edit_image_gpt_codex,
    edit_image_gpt_pool,
    edit_image_third_party,
    get_chatgpt_pool_config,
    get_task,
    os,
    resolve_route_model,
    send_status_notification,
    send_telegram_result,
    time,
    update_task_status,
):
    """后台线程：处理 GPT 图像编辑任务（本地 Codex provider）。"""
    run_id = ''
    task_kind = 'gpt-edit'
    task_provider = 'codex'
    task_route = 'codex_edit'
    try:
        ratio = _effective_image_ratio(prompt, ratio, '1:1')
        prompt_mode = _effective_prompt_mode(prompt, prompt_mode)
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
            'ratio': ratio,
            'archive_enabled': archive_enabled,
            'telegram_enabled': telegram_enabled,
            **({
                'prompt_fidelity_locked': True,
                'source_ratio_locked': True,
            } if _is_generic_19_fidelity_prompt(prompt) else {}),
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


def process_custom_task(task_id, prompt, ratio, resolution, quality='auto', moderation='auto', *, process_gpt_task):
    """兼容 custom 路由，复用 GPT provider + fallback 流程。"""
    return process_gpt_task(task_id, prompt, ratio, resolution, quality, moderation=moderation)
