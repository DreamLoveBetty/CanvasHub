"""Native editable PPT/PSD worker lifecycle.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def process_gpt_editable_file_task(
    task_id,
    kind,
    prompt,
    base64_images=None,
    prompt_mode='smart',
    gpt_provider_route='chatgpt_pool',
    archive_enabled=True,
    telegram_enabled=True,
    *,
    _annotate_gpt_route_result,
    _append_task_route_trace,
    _coerce_gpt_main_model,
    _coerce_gpt_moderation,
    _coerce_gpt_provider_route,
    _coerce_gpt_provider_total_timeout,
    _coerce_gpt_reasoning_effort,
    _coerce_gpt_resolution,
    _coerce_gpt_task_type,
    _coerce_image_ratio,
    _finalize_generation_task,
    _format_gpt_failure_error,
    _format_gpt_pool_error,
    _format_gpt_provider_error,
    _is_task_canceled,
    _make_gpt_provider_wait_callback,
    _make_third_party_download_progress_callback,
    _merge_task_params,
    _record_generation_event,
    _resolve_codex_provider_env,
    _start_generation_audit,
    _translate_generation_failure,
    generate_editable_file_gpt_pool,
    generate_editable_psd_native,
    get_chatgpt_pool_config,
    get_task,
    resolve_route_model,
    save_editable_artifacts,
    send_status_notification,
    send_telegram,
    update_task,
    update_task_status,
):
    """后台线程：PPT 走账号池，PSD 可走模型原生图片编辑线路。"""
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

        requested_route = _coerce_gpt_provider_route(gpt_provider_route)
        selected_route = 'chatgpt_pool' if kind == 'ppt' else requested_route
        task_params = (get_task(task_id) or {}).get('params') or {}
        requested_main_model = _coerce_gpt_main_model(task_params.get('main_model'))
        requested_reasoning_effort = _coerce_gpt_reasoning_effort(task_params.get('reasoning_effort'))
        route_resolution = resolve_route_model(
            selected_route,
            requested_main_model,
            reasoning_effort=requested_reasoning_effort,
        )
        main_model = route_resolution.get('model') or requested_main_model
        reasoning_effort = route_resolution.get('reasoning_effort') or requested_reasoning_effort
        codex_unavailable_error = ''
        if kind == 'psd' and selected_route == 'codex' and not route_resolution.get('available'):
            codex_unavailable_error = route_resolution.get('warning') or '当前 Codex 账号没有可用的 PSD 图片编辑模型'
            if get_chatgpt_pool_config(ensure_auth_key=True).get('enabled'):
                selected_route = 'chatgpt_pool'

        def apply_selected_route(route):
            nonlocal selected_route, task_provider, task_route
            selected_route = route
            task_provider = 'third_party_image_api' if route == 'third_party_image_api' else ('codex' if route == 'codex' else 'chatgpt_pool')
            task_route = 'third_party_image_api_edit' if route == 'third_party_image_api' else ('codex_edit' if route == 'codex' else 'chatgpt_pool_editable')

        apply_selected_route(selected_route)
        _merge_task_params(task_id, {
            'task_type': kind,
            'artifact_type': kind,
            'requested_gpt_provider_route': requested_route,
            'gpt_provider_route': selected_route,
            'prompt_mode': prompt_mode,
            'main_model': main_model,
            'reasoning_effort': reasoning_effort,
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
        if codex_unavailable_error:
            _append_task_route_trace(task_id, 'codex_edit', 'skipped', codex_unavailable_error)
            if selected_route != 'chatgpt_pool':
                raise RuntimeError(codex_unavailable_error)

        provider_labels = {
            'codex': '本地 Codex 原生图片能力',
            'third_party_image_api': '第三方原生图片 API',
            'chatgpt_pool': 'ChatGPT 账号池 Web API',
        }

        def call_selected_provider():
            label = provider_labels[selected_route]
            stage = 'calling_chatgpt_pool' if selected_route == 'chatgpt_pool' else ('calling_third_party_image_api' if selected_route == 'third_party_image_api' else 'calling_gpt_edit')
            update_task_status(task_id, 'processing', f'正在调用 {label}...', stage=stage)
            _append_task_route_trace(task_id, task_route, 'started', f'正在生成 {kind.upper()} 文件')
            _record_generation_event(
                task_id,
                'provider_call_started',
                f'开始调用 {label} 生成 {kind.upper()} 文件',
                stage=stage,
                payload={'provider': task_provider, 'route': task_route, 'artifact_type': kind},
            )
            if selected_route == 'chatgpt_pool':
                return generate_editable_file_gpt_pool(kind=kind, prompt=prompt, base64_images=images, task_id=task_id)
            provider_env = None
            codex_auth_source = ''
            if selected_route == 'codex':
                provider_env, codex_auth_source = _resolve_codex_provider_env()
            native_result = generate_editable_psd_native(
                route=selected_route,
                prompt=prompt,
                base64_images=images,
                ratio=_coerce_image_ratio(task_params.get('ratio'), '1:1'),
                resolution=_coerce_gpt_resolution(task_params.get('resolution')),
                quality='high',
                moderation=_coerce_gpt_moderation(task_params.get('moderation', 'auto')),
                prompt_mode=prompt_mode,
                main_model=main_model,
                reasoning_effort=reasoning_effort,
                total_timeout_seconds=_coerce_gpt_provider_total_timeout(None),
                on_provider_wait=_make_gpt_provider_wait_callback(task_id),
                progress_callback=_make_third_party_download_progress_callback(task_id),
                provider_env=provider_env,
            )
            if codex_auth_source:
                native_result['codex_auth_source'] = codex_auth_source
            if native_result.get('success'):
                _annotate_gpt_route_result(
                    native_result,
                    route_resolution,
                    requested_route=requested_route,
                    requested_model=requested_main_model,
                    requested_reasoning_effort=requested_reasoning_effort,
                )
            return native_result

        result = call_selected_provider()
        if not result.get('success') and kind == 'psd' and selected_route == 'codex':
            primary_error = result.get('error') or 'Codex PSD 生成失败'
            _append_task_route_trace(task_id, task_route, 'failed', primary_error)
            pool_cfg = get_chatgpt_pool_config(ensure_auth_key=True)
            if pool_cfg.get('enabled'):
                update_task_status(task_id, 'fallback_running', 'Codex PSD 生成失败，正在切换账号池托底...', stage='fallback_running')
                send_status_notification(task_id, 'Codex PSD 生成失败，切换账号池托底中...', '🛟')
                apply_selected_route('chatgpt_pool')
                _merge_task_params(task_id, {
                    'gpt_provider_route': selected_route,
                    'psd_fallback_from': 'codex',
                    'psd_primary_error': str(primary_error)[:800],
                })
                result = call_selected_provider()
        if not result.get('success'):
            error = result.get('error') or f'{provider_labels[selected_route]}可编辑文件任务失败'
            _append_task_route_trace(task_id, task_route, 'failed', error)
            raise RuntimeError(_format_gpt_pool_error(error) if selected_route == 'chatgpt_pool' else _format_gpt_provider_error(error))
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
        _append_task_route_trace(task_id, task_route, 'succeeded', f'{kind.upper()} 文件生成成功')
        _merge_task_params(task_id, {
            'file_manifest': manifest,
            'file_manifest_url': manifest.get('manifest_url'),
            'editable_preview_status': (manifest.get('preview') or {}).get('status'),
            'editable_artifact_type': kind,
            'gpt_provider_route': selected_route,
            'codex_auth_source': result.get('codex_auth_source'),
            'generated_transparent_path': result.get('generated_transparent_path'),
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
