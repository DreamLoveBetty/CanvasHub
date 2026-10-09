"""Google generation/edit request adapters.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def handle_generate(
    handler,
    force_caller=None,
    *,
    DEFAULT_GOOGLE_IMAGE_MODEL,
    _attach_lineage_params,
    _coerce_bool,
    _coerce_google_max_tokens,
    _coerce_google_quality,
    _coerce_google_temperature,
    _coerce_gpt_resolution,
    _coerce_model,
    _effective_image_ratio,
    create_task,
    json,
    process_task,
    random,
    time,
):
    """处理生成请求（支持 skill 调用托底策略）"""
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(content_length)
        data = json.loads(body)

        if not isinstance(data, dict):
            handler.send_json({'error': '请求必须为 JSON 对象'}, 400)
            return
        incoming_params = data.get('params') if isinstance(data.get('params'), dict) else {}
        requested_route = data.get('google_provider_route', incoming_params.get('google_provider_route', 'third_party'))
        if requested_route not in ('third_party', 'google_pool'):
            handler.send_json({'error': 'Google线路无效'}, 400)
            return
        prompt = data.get('prompt', '')
        incoming_params = data.get('params', {}) if isinstance(data.get('params'), dict) else {}
        params = {
            'google_provider_route': requested_route,
            'ratio': _effective_image_ratio(prompt, data.get('ratio', incoming_params.get('ratio', '1:1')), '1:1'),
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
        if requested_route == 'google_pool' and params['model'].removesuffix('-preview') not in (
            'gemini-3-pro-image', 'gemini-3.1-pro-image', 'gemini-3-flash-image', 'gemini-3.1-flash-image'
        ):
            handler.send_json({'error': 'Google OAuth 线路仅支持 Gemini 图像模型'}, 400)
            return
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
            handler.send_json({"error": "Prompt is required"}, 400)
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
        if not handler.start_generation_task(task_id, process_task, (task_id, prompt, params)):
            return

        handler.send_json({
            "task_id": task_id,
            "status": "queued",
            "message": "已提交图片生成任务，请等待...",
            "type": task_type,
            "caller": caller,
            "fallback": fallback_cfg
        }, 202)

    except Exception as e:
        handler.send_json({"error": str(e)}, 500)


def handle_edit(
    handler,
    force_caller=None,
    *,
    DEFAULT_GOOGLE_IMAGE_MODEL,
    _attach_lineage_params,
    _coerce_bool,
    _coerce_google_edit_quality,
    _coerce_google_max_tokens,
    _coerce_google_temperature,
    _coerce_model,
    _effective_image_ratio,
    create_task,
    json,
    process_edit_task,
    random,
    time,
):
    """处理编辑请求（支持 skill 调用托底策略）"""
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(content_length)
        data = json.loads(body)

        if not isinstance(data, dict):
            handler.send_json({'error': '请求必须为 JSON 对象'}, 400)
            return
        incoming_params = data.get('params') if isinstance(data.get('params'), dict) else {}
        requested_route = data.get('google_provider_route', incoming_params.get('google_provider_route', 'third_party'))
        if requested_route not in ('third_party', 'google_pool'):
            handler.send_json({'error': 'Google线路无效'}, 400)
            return
        prompt = data.get('prompt', '')
        images = data.get('images', [])

        incoming_params = data.get('params', {}) if isinstance(data.get('params'), dict) else {}

        # 兼容前端顶层字段 + params 字段
        params = {
            'google_provider_route': requested_route,
            'ratio': _effective_image_ratio(prompt, data.get('ratio', incoming_params.get('ratio', '1:1')), '1:1'),
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
        if requested_route == 'google_pool' and params['model'].removesuffix('-preview') not in (
            'gemini-3-pro-image', 'gemini-3.1-pro-image', 'gemini-3-flash-image', 'gemini-3.1-flash-image'
        ):
            handler.send_json({'error': 'Google OAuth 线路仅支持 Gemini 图像模型'}, 400)
            return
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
            handler.send_json({"error": "Prompt is required"}, 400)
            return

        if not images or len(images) == 0:
            handler.send_json({"error": "请上传至少一张图片"}, 400)
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
        if not handler.start_generation_task(task_id, process_edit_task, (task_id, prompt, images, params)):
            return

        handler.send_json({
            "task_id": task_id,
            "status": "queued",
            "message": "已提交图片编辑任务，请等待...",
            "caller": caller,
            "fallback": fallback_cfg,
        }, 202)

    except Exception as e:
        handler.send_json({"error": str(e)}, 500)
