"""Local upscale, video runtime and ComfyUI HTTP adapters.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def handle_upscale_run(
    handler,
    *,
    UPSCALE_MODEL_DIR,
    _attach_lineage_params,
    _coerce_bool,
    _coerce_upscale_tile,
    available_upscale_models,
    create_task,
    get_upscale_component_status,
    json,
    normalize_upscale_model,
    process_upscale_task,
    random,
    time,
):
    """处理本地高清放大请求。"""
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(content_length)
        data = json.loads(body or b'{}')

        images = data.get('images', [])
        if not isinstance(images, list):
            images = []
        image_data = next((str(item or '').strip() for item in images if str(item or '').strip()), '')
        if not image_data:
            handler.send_json({"error": "请先连接或上传一张图片"}, 400)
            return

        incoming_params = data.get('params') if isinstance(data.get('params'), dict) else {}
        model_name = normalize_upscale_model(data.get('model', incoming_params.get('model')))
        model_status = next((item for item in available_upscale_models(UPSCALE_MODEL_DIR) if item.get('id') == model_name), {})
        if not model_status.get('available'):
            if model_name.startswith('topaz-'):
                handler.send_json({'error': model_status.get('error') or 'Topaz 原生模型不可用'}, 409)
                return
            handler.send_json({
                "error": "高清放大组件尚未安装，请先完成组件下载。",
                "component": get_upscale_component_status(),
            }, 409)
            return
        prompt = str(data.get('prompt') or incoming_params.get('prompt') or f'高清放大：{model_name}').strip()
        params = {
            'model': model_name,
            'scale': model_status.get('scale', 4),
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
        if not handler.start_generation_task(task_id, process_upscale_task, (task_id, prompt, image_data, params)):
            return

        handler.send_json({
            "task_id": task_id,
            "status": "queued",
            "message": "已提交高清放大任务，请等待...",
            "type": "upscale",
        }, 202)
    except ValueError as e:
        handler.send_json({'error': str(e)}, 400)
    except Exception as e:
        handler.send_json({"error": str(e)}, 500)


def handle_video_runtime_status(handler, parsed=None, *, _coerce_bool, collect_video_runtime_status, urllib):
    """Return H3 Runtime routing and optionally perform a live probe."""
    try:
        query = urllib.parse.parse_qs(parsed.query) if parsed else {}
        probe = _coerce_bool((query.get("probe") or ["0"])[0], False)
        handler.send_json(collect_video_runtime_status(probe=probe))
    except ValueError as e:
        handler.send_json({"ok": False, "online": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ H3 Runtime 状态读取失败：{e}")
        handler.send_json({"ok": False, "online": False, "error": str(e)}, 500)


def handle_video_supervisor_status(handler, parsed=None, *, _coerce_bool, collect_video_supervisor_status, urllib):
    """Return the configured H3 Supervisor address and optional health probe."""
    try:
        query = urllib.parse.parse_qs(parsed.query) if parsed else {}
        probe = _coerce_bool((query.get("probe") or ["0"])[0], False)
        handler.send_json(collect_video_supervisor_status(probe=probe))
    except Exception as e:
        print(f"❌ H3 Supervisor 状态读取失败：{e}")
        handler.send_json({"ok": False, "online": False, "error": str(e)}, 500)


def handle_video_runtime_capabilities(handler, *, collect_video_runtime_capabilities):
    """Return live H3 capabilities, or a bounded offline fallback."""
    try:
        handler.send_json(collect_video_runtime_capabilities())
    except Exception as e:
        print(f"❌ H3 Runtime 能力读取失败：{e}")
        handler.send_json({"ok": False, "runtime_online": False, "error": str(e)}, 500)


def handle_video_runtime_test(handler, *, collect_video_runtime_status):
    """Probe unsaved local/LAN fields from the settings panel."""
    try:
        payload = handler.read_json_body(max_bytes=64 * 1024)
        handler.send_json(collect_video_runtime_status(probe=True, overrides=payload))
    except ValueError as e:
        handler.send_json({"ok": False, "online": False, "error": str(e)}, 400)
    except Exception as e:
        handler.send_json({"ok": False, "online": False, "error": str(e)}, 502)


def handle_video_supervisor_test(handler, *, collect_video_supervisor_status):
    """Probe an unsaved Supervisor URL from the settings panel."""
    try:
        payload = handler.read_json_body(max_bytes=16 * 1024)
        handler.send_json(collect_video_supervisor_status(
            probe=True,
            base_url=payload.get("manager_base_url") if isinstance(payload, dict) else None,
        ))
    except ValueError as e:
        handler.send_json({"ok": False, "online": False, "error": str(e)}, 400)
    except Exception as e:
        handler.send_json({"ok": False, "online": False, "error": str(e)}, 502)


def handle_video_runtime_start(handler, *, start_local_video_runtime):
    """Start a separately installed local H3 Runtime component on Windows."""
    try:
        result = start_local_video_runtime()
        handler.send_json(result, 202 if result.get("ok") else 409)
    except Exception as e:
        print(f"❌ H3 Runtime 启动失败：{e}")
        handler.send_json({"ok": False, "started": False, "error": str(e)}, 500)


def handle_video_prompt_compile(handler, *, H3PromptCompileError, compile_h3_prompt):
    """Compile an I2VA request with the pinned official MiniMax H3 skill."""
    try:
        payload = handler.read_json_body(max_bytes=64 * 1024 * 1024)
        handler.send_json(compile_h3_prompt(payload))
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except H3PromptCompileError as e:
        handler.send_json({"ok": False, "error": str(e)}, 502)
    except RuntimeError as e:
        print(f"❌ H3 提示词模型调用失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 502)
    except Exception as e:
        print(f"❌ H3 提示词编译失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_video_generate(
    handler,
    *,
    H3_VIDEO_TASK_TYPE,
    _coerce_bool,
    _decode_h3_reference_image,
    _sanitize_h3_prompt_metadata,
    collect_video_runtime_capabilities,
    create_task,
    process_h3_video_task,
    random,
    time,
):
    """Create a tracked MiniMax H3 video task without exposing Runtime secrets."""
    try:
        data = handler.read_json_body(max_bytes=140 * 1024 * 1024)
        prompt = str(data.get('prompt') or '').strip()
        if not prompt:
            raise ValueError('请连接一个包含提示词的文本节点')
        if len(prompt) > 20_000:
            raise ValueError('提示词不能超过 20000 字符')

        mode = str(data.get('mode') or 'image_to_video').strip().lower()
        if mode not in {'image_to_video', 'reference_to_video'}:
            raise ValueError('mode 必须是 image_to_video 或 reference_to_video')
        aspect_ratio = str(data.get('aspect_ratio') or '3:4').strip()
        if aspect_ratio not in {'16:9', '9:16', '3:4', '4:3', '2:3', '3:2', '1:1', '21:9', '9:21'}:
            raise ValueError('不支持的 H3 画幅比例')

        capabilities_payload = collect_video_runtime_capabilities()
        capabilities = capabilities_payload.get('capabilities') if isinstance(capabilities_payload, dict) else {}
        constraints = capabilities.get('constraints') if isinstance(capabilities, dict) and isinstance(capabilities.get('constraints'), dict) else {}
        dimension_multiple = max(1, int(constraints.get('dimension_multiple') or 32))
        max_pixels = max(1, int(constraints.get('max_pixels') or 1_032_192))
        duration_range = constraints.get('duration_seconds') if isinstance(constraints.get('duration_seconds'), dict) else {}
        min_duration = max(1.0, float(duration_range.get('min') or 1))
        max_duration = max(min_duration, float(duration_range.get('max') or 15))

        width = int(float(data.get('width') or 0))
        height = int(float(data.get('height') or 0))
        if width <= 0 or height <= 0:
            raise ValueError('视频宽高必须大于 0')
        if width % dimension_multiple or height % dimension_multiple:
            raise ValueError(f'视频宽高必须都是 {dimension_multiple} 的倍数')
        if width * height > max_pixels:
            raise ValueError(f'当前 H3 Runtime 最大允许 {max_pixels:,} 像素')
        try:
            pixel_budget_mp = float(data.get('pixel_budget_mp'))
        except (TypeError, ValueError):
            pixel_budget_mp = round(width * height / 1_000_000, 3)
        if not 0.1 <= pixel_budget_mp <= 8:
            raise ValueError('质量（像素量）参数无效')

        duration_seconds = float(data.get('duration_seconds') or 15)
        if not min_duration <= duration_seconds <= max_duration:
            raise ValueError(f'视频时长必须在 {min_duration:g} 到 {max_duration:g} 秒之间')
        steps = int(float(data.get('steps') or 20))
        if not 1 <= steps <= 100:
            raise ValueError('采样步数必须在 1 到 100 之间')
        denoise = 1.0
        crf = int(float(data.get('crf') if data.get('crf') is not None else 23))
        if not 0 <= crf <= 51:
            raise ValueError('视频 CRF 必须在 0 到 51 之间')
        acceleration_mode = str(data.get('acceleration_mode') or 'first_block_cache').strip().lower()
        if acceleration_mode not in {'off', 'first_block_cache', 'sol_attn', 'combined'}:
            raise ValueError('不支持的 H3 加速模式')
        first_block_cache_threshold = float(data.get('first_block_cache_threshold') or 0.08)
        if not 0 < first_block_cache_threshold <= 1:
            raise ValueError('FirstBlockCache 阈值必须大于 0 且不超过 1')
        seed = ''
        prompt_metadata = _sanitize_h3_prompt_metadata(data.get('prompt_metadata'))

        first_frame = data.get('first_frame') or data.get('reference_image')
        upload = _decode_h3_reference_image(first_frame)
        params = {
            'provider': 'minimax_h3',
            'mode': mode,
            'aspect_ratio': aspect_ratio,
            'pixel_budget_mp': pixel_budget_mp,
            'actual_megapixels': round(width * height / 1_000_000, 3),
            'width': width,
            'height': height,
            'duration_seconds': duration_seconds,
            'steps': steps,
            'denoise': denoise,
            'crf': crf,
            'seed': seed,
            'acceleration_mode': acceleration_mode,
            'first_block_cache_threshold': first_block_cache_threshold,
            'archive_enabled': True,
            'telegram_enabled': _coerce_bool(data.get('telegram_enabled'), False),
            'runtime_capability_source': capabilities_payload.get('source') if isinstance(capabilities_payload, dict) else 'fallback',
            'prompt_metadata': prompt_metadata,
            'dimension_multiple': dimension_multiple,
            'max_pixels': max_pixels,
        }
        task_id = f"h3v_{int(time.time())}_{random.randint(1000, 9999)}"
        create_task(task_id, prompt, params, status='queued', task_type=H3_VIDEO_TASK_TYPE)
        if not handler.start_generation_task(task_id, process_h3_video_task, (task_id, prompt, upload, params)):
            return
        handler.send_json({
            'ok': True,
            'task_id': task_id,
            'status': 'queued',
            'progress': 0,
            'message': 'MiniMax H3 视频任务已提交',
        }, 202)
    except ValueError as e:
        handler.send_json({'ok': False, 'error': str(e)}, 400)
    except Exception as e:
        print(f'❌ H3 视频任务提交失败：{e}')
        handler.send_json({'ok': False, 'error': str(e)}, 500)


def handle_comfy_workflows(handler, *, _coerce_bool, _collect_comfy_workflows, urllib):
    """返回可用的 ComfyUI 工作流列表"""
    try:
        parsed = urllib.parse.urlparse(handler.path)
        query = urllib.parse.parse_qs(parsed.query)
        include_disabled = _coerce_bool((query.get('include_disabled') or ['0'])[0], False)
        handler.send_json({"ok": True, **_collect_comfy_workflows(include_disabled=include_disabled)})
    except Exception as e:
        handler.send_json({"error": str(e)}, 500)


def handle_comfy_health(handler, parsed=None, *, _collect_comfy_health, urllib):
    """测试 ComfyUI 服务连接。"""
    try:
        query = urllib.parse.parse_qs(parsed.query) if parsed else {}
        overrides = {
            'base_url': (query.get('base_url') or [''])[0],
            'timeout_seconds': (query.get('timeout_seconds') or [''])[0],
        }
        handler.send_json(_collect_comfy_health(overrides))
    except Exception as e:
        handler.send_json({"ok": False, "online": False, "error": str(e)}, 502)


def handle_comfy_workflow_thumbnail(handler, parsed, *, COMFY_WORKFLOW_DIR, Path, _comfy_workflow_preview_path, urllib):
    """返回经过目录白名单解析的工作流缩略图。"""
    query = urllib.parse.parse_qs(parsed.query)
    workflow_id = Path(str((query.get('id') or [''])[0])).name
    if not workflow_id or not (COMFY_WORKFLOW_DIR / workflow_id).exists():
        handler.send_error(404, 'Not Found')
        return
    preview = _comfy_workflow_preview_path(workflow_id)
    if not preview.exists():
        handler.send_error(404, 'Not Found')
        return
    data = preview.read_bytes()
    handler.send_response(200)
    handler.send_header('Content-Type', 'image/webp')
    handler.send_header('Content-Length', str(len(data)))
    handler.send_header('Cache-Control', 'private, max-age=300')
    handler._apply_cors_headers()
    handler.end_headers()
    handler.wfile.write(data)


def handle_comfy_workflow_config_save(handler, *, _collect_comfy_workflows, _save_comfy_workflow_config):
    """保存工作流展示元信息和缩略图。"""
    try:
        data = handler.read_json_body(max_bytes=12 * 1024 * 1024)
        item = _save_comfy_workflow_config(data)
        handler.send_json({"ok": True, "item": item, **_collect_comfy_workflows(include_disabled=True)})
    except FileNotFoundError as e:
        handler.send_json({"ok": False, "error": str(e)}, 404)
    except Exception as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)


def handle_comfy_run(
    handler,
    *,
    COMFY_CLIENT_ID,
    COMFY_RESOLUTION_LONG_EDGES,
    _apply_comfy_parameter_overrides,
    _coerce_bool,
    _collect_comfy_workflows,
    _comfy_ratio_from_size,
    _load_comfy_workflow,
    _normalize_comfy_dimension,
    _prepare_comfy_workflow,
    _proxy_comfy_json,
    _resolve_comfy_size,
    _upload_comfy_image,
    create_task,
    json,
    process_comfy_task,
    uuid,
):
    """将前端请求转发到远端 ComfyUI /prompt"""
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(content_length)
        data = json.loads(body or b'{}')

        workflow_name = data.get('workflow', '')
        prompt = data.get('prompt', '')
        ratio = str(data.get('ratio') or '').strip()
        resolution = str(data.get('resolution') or '1k').strip().lower()
        if resolution not in COMFY_RESOLUTION_LONG_EDGES:
            resolution = '1k'
        archive_enabled = True
        telegram_enabled = _coerce_bool(data.get('telegram_enabled', data.get('telegramEnabled')), True)

        workflow, normalized_name = _load_comfy_workflow(workflow_name)
        workflow_parameters = data.get('workflow_parameters') if isinstance(data.get('workflow_parameters'), dict) else {}
        workflow, applied_workflow_parameters = _apply_comfy_parameter_overrides(workflow, workflow_parameters)
        catalog_item = next((item for item in _collect_comfy_workflows(include_disabled=True)['items'] if item['id'] == normalized_name), None)
        if catalog_item and not catalog_item.get('enabled'):
            raise ValueError('当前 ComfyUI 工作流已停用')
        legacy_ratio = ratio or str((catalog_item or {}).get('default_ratio') or '1:1')
        legacy_width, legacy_height = _resolve_comfy_size(legacy_ratio, resolution)
        width = _normalize_comfy_dimension(data.get('width'), (catalog_item or {}).get('default_width', legacy_width))
        height = _normalize_comfy_dimension(data.get('height'), (catalog_item or {}).get('default_height', legacy_height))
        ratio = ratio or _comfy_ratio_from_size(width, height)
        raw_images = data.get('images') if isinstance(data.get('images'), list) else []
        if not raw_images and data.get('image'):
            raw_images = [data.get('image')]
        max_images = int(catalog_item.get('max_images') or 0) if catalog_item and catalog_item.get('accepts_image') else 0
        image_payloads = [item for item in raw_images if isinstance(item, str) and item.strip()][:max_images]
        if catalog_item and catalog_item.get('accepts_image') and not image_payloads:
            raise ValueError('当前 ComfyUI 工作流需要至少一张参考图')
        if catalog_item and not catalog_item.get('accepts_text'):
            prompt = ''
        uploaded_image_names = [_upload_comfy_image(image_data) for image_data in image_payloads]
        uploaded_image_name = uploaded_image_names[0] if uploaded_image_names else None
        prepared_prompt = _prepare_comfy_workflow(
            workflow,
            prompt,
            ratio,
            uploaded_image_name,
            uploaded_image_names,
            resolution=resolution,
            width=width,
            height=height,
        )

        client_id = f'{COMFY_CLIENT_ID}-{uuid.uuid4().hex[:12]}'
        result = _proxy_comfy_json(
            'POST',
            '/prompt',
            payload={'prompt': prepared_prompt, 'client_id': client_id},
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
                'resolution': resolution,
                'width': width,
                'height': height,
                'comfy_prompt_id': prompt_id,
                'comfy_client_id': client_id,
                'comfy_transport': 'websocket_history',
                'comfy_uploaded_image': uploaded_image_name,
                'comfy_uploaded_images': uploaded_image_names,
                'comfy_expected_output_count': int(catalog_item.get('output_count') or 1) if catalog_item else 1,
                'workflow_parameters': applied_workflow_parameters,
                'archive_enabled': archive_enabled,
                'telegram_enabled': telegram_enabled,
            },
            status='queued',
            task_type='comfy',
        )

        if not handler.start_generation_task(
            prompt_id,
            process_comfy_task,
            (prompt_id, prompt, normalized_name, ratio, client_id),
        ):
            return

        handler.send_json({
            'status': 'queued',
            'prompt_id': prompt_id,
            'task_id': prompt_id,
            'workflow': normalized_name,
        })
    except FileNotFoundError as e:
        handler.send_json({"error": str(e)}, 404)
    except ValueError as e:
        handler.send_json({"error": str(e)}, 400)
    except Exception as e:
        print(f"❌ Comfy run failed: {e}")
        handler.send_json({"error": str(e)}, 500)


def handle_comfy_history(handler, *, _fetch_comfy_history_entry, _sync_comfy_task, urllib):
    """代理查询远端 ComfyUI 历史任务"""
    try:
        parsed = urllib.parse.urlparse(handler.path)
        params = urllib.parse.parse_qs(parsed.query)
        prompt_id = params.get('prompt_id', [''])[0].strip()
        if not prompt_id:
            handler.send_json({"error": "缺少 prompt_id"}, 400)
            return

        result, entry = _fetch_comfy_history_entry(prompt_id)
        if isinstance(entry, dict):
            _sync_comfy_task(prompt_id, entry)
        handler.send_json(result)
    except Exception as e:
        print(f"❌ Comfy history failed: {e}")
        handler.send_json({"error": str(e)}, 500)


def handle_comfy_image(handler, *, _fetch_comfy_binary, urllib):
    """代理远端 ComfyUI 图片下载"""
    try:
        parsed = urllib.parse.urlparse(handler.path)
        params = urllib.parse.parse_qs(parsed.query)
        filename = params.get('filename', [''])[0].strip()
        subfolder = params.get('subfolder', [''])[0]
        file_type = params.get('type', ['output'])[0]
        if not filename:
            handler.send_json({"error": "缺少 filename"}, 400)
            return

        image_bytes, content_type = _fetch_comfy_binary(filename, subfolder, file_type)
        handler.send_response(200)
        handler.send_header('Content-Type', content_type)
        handler._apply_cors_headers()
        handler.end_headers()
        handler.wfile.write(image_bytes)
    except Exception as e:
        print(f"❌ Comfy image failed: {e}")
        handler.send_json({"error": str(e)}, 500)


def handle_comfy_send_tg(handler, *, Path, _fetch_comfy_binary, json, os, send_telegram, tempfile):
    """下载远端 ComfyUI 结果并无损发送到 Telegram"""
    temp_path = None
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(content_length)
        data = json.loads(body or b'{}')

        filename = str(data.get('filename', '')).strip()
        subfolder = data.get('subfolder', '')
        file_type = data.get('type', 'output')
        prompt = str(data.get('prompt', '')).strip()
        workflow = str(data.get('workflow', '')).strip()
        ratio = str(data.get('ratio', '')).strip()

        if not filename:
            handler.send_json({"error": "缺少 filename"}, 400)
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

        handler.send_json({"ok": True})
    except Exception as e:
        print(f"❌ Comfy send_tg failed: {e}")
        handler.send_json({"error": str(e)}, 500)
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass
