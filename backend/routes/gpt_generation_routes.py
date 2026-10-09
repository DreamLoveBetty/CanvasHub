"""GPT generation/edit/custom request adapters.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def handle_gpt_generate(
    handler,
    *,
    _attach_lineage_params,
    _coerce_bool,
    _coerce_gpt_image_count,
    _coerce_gpt_main_model,
    _coerce_gpt_moderation,
    _coerce_gpt_provider_route,
    _coerce_gpt_quality,
    _coerce_gpt_reasoning_effort,
    _coerce_gpt_resolution,
    _coerce_gpt_task_type,
    _coerce_prompt_mode,
    _coerce_use_third_party_api,
    _effective_image_ratio,
    _gpt_route_uses_third_party,
    create_task,
    json,
    process_gpt_editable_file_task,
    process_gpt_task,
    random,
    time,
):
    """处理 GPT 生成请求（使用 ChatGPT/Codex 浏览器自动化）"""
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(content_length)
        data = json.loads(body)
        
        prompt = data.get('prompt', '')
        ratio = _effective_image_ratio(prompt, data.get('ratio'), '1:1')
        resolution = _coerce_gpt_resolution(data.get('resolution'))
        quality = _coerce_gpt_quality(data.get('quality', 'auto'))
        moderation = _coerce_gpt_moderation(data.get('moderation', 'auto'))
        gpt_task_type = _coerce_gpt_task_type(data.get('task_type', data.get('taskType', data.get('gpt_task_type', data.get('gptTaskType')))))
        prompt_mode = _coerce_prompt_mode(data.get('prompt_mode', data.get('promptMode', 'smart')))
        gpt_provider_route = _coerce_gpt_provider_route(
            data.get('gpt_provider_route', data.get('gptProviderRoute', data.get('provider_route', data.get('providerRoute'))))
        )
        if gpt_task_type == 'ppt':
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
            handler.send_json({"error": "Prompt is required"}, 400)
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
        if not handler.start_generation_task(task_id, target, args):
            return
        
        handler.send_json({
            "task_id": task_id,
            "status": "queued",
            "message": "已提交 GPT 图片生成任务，请等待..."
        }, 202)
        
    except Exception as e:
        handler.send_json({"error": str(e)}, 500)


def handle_gpt_edit(
    handler,
    *,
    _attach_lineage_params,
    _coerce_bool,
    _coerce_gpt_main_model,
    _coerce_gpt_moderation,
    _coerce_gpt_provider_route,
    _coerce_gpt_quality,
    _coerce_gpt_reasoning_effort,
    _coerce_gpt_resolution,
    _coerce_prompt_mode,
    _coerce_use_third_party_api,
    _effective_image_ratio,
    _gpt_route_uses_third_party,
    create_task,
    json,
    process_gpt_edit_task,
    random,
    time,
):
    """处理 GPT 图像编辑请求（使用本地 Codex runtime）"""
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(content_length)
        data = json.loads(body or b'{}')

        prompt = data.get('prompt', '')
        images = data.get('images', [])
        ratio = _effective_image_ratio(prompt, data.get('ratio'), '1:1')
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
            handler.send_json({"error": "Prompt is required"}, 400)
            return
        if not images:
            handler.send_json({"error": "请上传至少一张图片"}, 400)
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

        if not handler.start_generation_task(
            task_id,
            process_gpt_edit_task,
            (task_id, prompt, images, ratio, resolution, quality, moderation, mask, prompt_mode, main_model, reasoning_effort, use_third_party_api, gpt_provider_route, archive_enabled, telegram_enabled),
        ):
            return

        handler.send_json({
            "task_id": task_id,
            "status": "queued",
            "message": "已提交 GPT 图片编辑任务，请等待..."
        }, 202)

    except Exception as e:
        handler.send_json({"error": str(e)}, 500)


def handle_custom_generate(
    handler,
    *,
    _coerce_gpt_moderation,
    _coerce_gpt_quality,
    _coerce_gpt_resolution,
    _coerce_image_ratio,
    create_task,
    json,
    process_custom_task,
    random,
    time,
):
    """处理 Custom API 生成请求（GPT-5.4 @ localhost:8080）"""
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(content_length)
        data = json.loads(body)
        
        prompt = data.get('prompt', '')
        ratio = _coerce_image_ratio(data.get('ratio'), '1:1')
        resolution = _coerce_gpt_resolution(data.get('resolution'))
        quality = _coerce_gpt_quality(data.get('quality', 'auto'))
        moderation = _coerce_gpt_moderation(data.get('moderation', 'auto'))
        
        if not prompt:
            handler.send_json({"error": "Prompt is required"}, 400)
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
        if not handler.start_generation_task(task_id, process_custom_task, (task_id, prompt, ratio, resolution, quality, moderation)):
            return
        
        handler.send_json({
            "task_id": task_id,
            "status": "queued",
            "message": "已提交 Custom API 图片生成任务，请等待..."
        }, 202)
        
    except Exception as e:
        handler.send_json({"error": str(e)}, 500)
