"""ComfyUI workflow preparation and existing remote API calls.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _collect_comfy_workflows(
    include_disabled=False,
    *,
    COMFY_WORKFLOW_DIR,
    _coerce_bool,
    _comfy_workflow_catalog_settings,
    _comfy_workflow_has_image_input,
    _comfy_workflow_preview_path,
    _comfy_workflow_uses_token,
    _default_comfy_workflow_label,
    _extract_comfy_workflow_default_size,
    _extract_comfy_workflow_parameters,
    _normalize_comfy_dimension,
    _resolve_comfy_size,
    json,
    urllib,
):
    catalog = _comfy_workflow_catalog_settings()
    items = []
    def bounded_int(value, default, minimum, maximum):
        try:
            return max(minimum, min(maximum, int(value)))
        except (TypeError, ValueError):
            return default
    for path in sorted(COMFY_WORKFLOW_DIR.glob('*.json')):
        workflow_id = path.name
        meta = catalog.get(workflow_id) if isinstance(catalog.get(workflow_id), dict) else {}
        try:
            workflow_data = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            workflow_data = {}
        parameters = _extract_comfy_workflow_parameters(workflow_data)
        default_ratio = str(meta.get('default_ratio') or '1:1')
        ratio_width, ratio_height = _resolve_comfy_size(default_ratio, '1k')
        detected_width, detected_height = _extract_comfy_workflow_default_size(
            workflow_data,
            (ratio_width, ratio_height),
        )
        default_width = _normalize_comfy_dimension(meta.get('default_width'), detected_width)
        default_height = _normalize_comfy_dimension(meta.get('default_height'), detected_height)
        auto_accepts_image = (
            _comfy_workflow_uses_token(path, '{{IMAGE}}')
            or _comfy_workflow_uses_token(path, '{{IMAGE_')
            or _comfy_workflow_has_image_input(workflow_data)
        )
        accepts_image = _coerce_bool(meta.get('accepts_image'), auto_accepts_image)
        enabled = _coerce_bool(meta.get('enabled'), True)
        if not include_disabled and not enabled:
            continue
        max_images = bounded_int(meta.get('max_images'), 1 if accepts_image else 0, 0, 8)
        output_count = bounded_int(meta.get('output_count'), 1, 1, 8)
        preview_path = _comfy_workflow_preview_path(workflow_id)
        label = str(meta.get('label') or _default_comfy_workflow_label(workflow_id)).strip()[:120]
        summary = str(meta.get('summary') or ('图生图 · 需要参考图' if accepts_image else '文生图 · 单图')).strip()[:180]
        items.append({
            'id': workflow_id,
            'label': label,
            'summary': summary,
            'enabled': enabled,
            'is_default': _coerce_bool(meta.get('is_default'), False),
            'order': bounded_int(meta.get('order'), 100, 0, 9999),
            'default_ratio': default_ratio,
            'default_width': default_width,
            'default_height': default_height,
            'accepts_text': _coerce_bool(meta.get('accepts_text'), True),
            'accepts_image': accepts_image,
            'max_images': max_images,
            'output_count': output_count,
            'parameter_count': len(parameters),
            'parameters': parameters,
            'thumbnail_url': f'/api/comfy/workflow-thumbnail?id={urllib.parse.quote(workflow_id)}&v={preview_path.stat().st_mtime_ns}' if preview_path.exists() else '',
        })
    items.sort(key=lambda item: (item['order'], item['label'].lower(), item['id'].lower()))
    default_item = next((item for item in items if item['is_default'] and item['enabled']), None)
    if default_item is None:
        default_item = next((item for item in items if item['enabled']), None)
    return {
        'workflows': [item['id'] for item in items if item['enabled']],
        'items': items,
        'default_workflow': default_item['id'] if default_item else '',
    }


def _save_comfy_workflow_config(
    data,
    *,
    COMFY_PREVIEW_DIR,
    COMFY_WORKFLOW_DIR,
    Image,
    Path,
    _coerce_bool,
    _collect_comfy_workflows,
    _comfy_workflow_preview_path,
    _decode_data_uri_image,
    _normalize_comfy_dimension,
    load_app_settings,
    save_app_settings,
):
    workflow_id = Path(str(data.get('id') or data.get('workflow') or '')).name
    workflow_path = COMFY_WORKFLOW_DIR / workflow_id
    if not workflow_id or not workflow_path.exists() or workflow_path.suffix.lower() != '.json':
        raise FileNotFoundError('工作流不存在')

    thumbnail_data = str(data.get('thumbnail_data') or '').strip()
    thumbnail_bytes = None
    if thumbnail_data:
        image_bytes, _mime_type, _extension = _decode_data_uri_image(thumbnail_data)
        buffer = __import__('io').BytesIO()
        with Image.open(__import__('io').BytesIO(image_bytes)) as source:
            preview = source.convert('RGB')
            preview.thumbnail((640, 400), Image.Resampling.LANCZOS)
            preview.save(buffer, 'WEBP', quality=84, method=6)
        thumbnail_bytes = buffer.getvalue()

    settings = load_app_settings()
    section = settings.get('comfy') if isinstance(settings.get('comfy'), dict) else {}
    section = dict(section)
    catalog = section.get('workflow_catalog') if isinstance(section.get('workflow_catalog'), dict) else {}
    catalog = dict(catalog)
    previous = catalog.get(workflow_id) if isinstance(catalog.get(workflow_id), dict) else {}
    meta = dict(previous)
    for key, limit in (('label', 120), ('summary', 180), ('default_ratio', 16)):
        if key in data:
            meta[key] = str(data.get(key) or '').strip()[:limit]
    for key in ('enabled', 'is_default', 'accepts_text', 'accepts_image'):
        if key in data:
            meta[key] = _coerce_bool(data.get(key), False)
    for key, minimum, maximum in (('order', 0, 9999), ('max_images', 0, 8), ('output_count', 1, 8)):
        if key in data:
            try:
                meta[key] = max(minimum, min(maximum, int(data.get(key))))
            except (TypeError, ValueError):
                pass
    for key in ('default_width', 'default_height'):
        if key in data:
            meta[key] = _normalize_comfy_dimension(data.get(key), previous.get(key, 1024))
    if meta.get('is_default'):
        for existing_id, existing_meta in list(catalog.items()):
            if isinstance(existing_meta, dict) and existing_id != workflow_id and existing_meta.get('is_default'):
                catalog[existing_id] = {**existing_meta, 'is_default': False}
    catalog[workflow_id] = meta
    section['workflow_catalog'] = catalog
    settings['comfy'] = section
    save_app_settings(settings)

    if thumbnail_bytes is not None:
        COMFY_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        _comfy_workflow_preview_path(workflow_id).write_bytes(thumbnail_bytes)
    elif _coerce_bool(data.get('clear_thumbnail'), False):
        try:
            _comfy_workflow_preview_path(workflow_id).unlink()
        except FileNotFoundError:
            pass
    return next((item for item in _collect_comfy_workflows(include_disabled=True)['items'] if item['id'] == workflow_id), None)


def _normalize_comfy_base_url(value, *, urllib):
    base_url = str(value or '').strip().rstrip('/')
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('ComfyUI Base URL 必须是完整的 http:// 或 https:// 地址')
    return base_url


def _collect_comfy_health(overrides=None, *, _new_comfy_session, _normalize_comfy_base_url, get_comfy_config, time):
    config = dict(get_comfy_config())
    overrides = overrides if isinstance(overrides, dict) else {}
    if str(overrides.get('base_url') or '').strip():
        config['base_url'] = _normalize_comfy_base_url(overrides.get('base_url'))
    if str(overrides.get('timeout_seconds') or '').strip():
        try:
            config['timeout_seconds'] = max(5, min(1800, int(overrides.get('timeout_seconds'))))
        except (TypeError, ValueError):
            raise ValueError('ComfyUI 请求超时必须是 5 到 1800 之间的整数')
    started = time.perf_counter()
    with _new_comfy_session() as session:
        response = session.get(f"{config['base_url']}/system_stats", timeout=min(config['timeout_seconds'], 10))
        response.raise_for_status()
        stats = response.json() if response.content else {}
        queue_response = session.get(f"{config['base_url']}/queue", timeout=min(config['timeout_seconds'], 10))
        queue_response.raise_for_status()
        queue_data = queue_response.json() if queue_response.content else {}
    pending = queue_data.get('queue_pending') if isinstance(queue_data, dict) else []
    running = queue_data.get('queue_running') if isinstance(queue_data, dict) else []
    return {
        'ok': True,
        'online': True,
        'latency_ms': round((time.perf_counter() - started) * 1000),
        'queue_pending': len(pending) if isinstance(pending, list) else 0,
        'queue_running': len(running) if isinstance(running, list) else 0,
        'system': stats if isinstance(stats, dict) else {},
    }


def _load_comfy_workflow(workflow_name, *, COMFY_WORKFLOW_DIR, Path, json):
    if not workflow_name:
        raise ValueError('缺少工作流名称')

    workflow_path = (COMFY_WORKFLOW_DIR / Path(workflow_name).name).resolve()
    if workflow_path.parent != COMFY_WORKFLOW_DIR.resolve() or not workflow_path.exists():
        raise FileNotFoundError(f'工作流不存在：{workflow_name}')

    with open(workflow_path, 'r', encoding='utf-8') as f:
        return json.load(f), workflow_path.name


def _resolve_comfy_size(ratio, resolution='1k', *, COMFY_RATIO_SIZES, COMFY_RESOLUTION_LONG_EDGES):
    width, height = COMFY_RATIO_SIZES.get(str(ratio or '1:1').strip(), COMFY_RATIO_SIZES['1:1'])
    target_long_edge = COMFY_RESOLUTION_LONG_EDGES.get(str(resolution or '1k').strip().lower(), 0)
    if not target_long_edge:
        return width, height
    try:
        ratio_width, ratio_height = (max(1, int(part)) for part in str(ratio or '1:1').split(':', 1))
    except (TypeError, ValueError):
        ratio_width, ratio_height = 1, 1
    if ratio_width >= ratio_height:
        width = target_long_edge
        height = max(64, round(target_long_edge * ratio_height / ratio_width / 64) * 64)
    else:
        height = target_long_edge
        width = max(64, round(target_long_edge * ratio_width / ratio_height / 64) * 64)
    return width, height


def _replace_comfy_tokens(value, replacements, *, _replace_comfy_tokens):
    if isinstance(value, dict):
        return {k: _replace_comfy_tokens(v, replacements) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_comfy_tokens(v, replacements) for v in value]
    if isinstance(value, str):
        if value in replacements:
            return replacements[value]
        updated = value
        for token, replacement in replacements.items():
            updated = updated.replace(token, str(replacement))
        return updated
    return value


def _decode_data_uri_image(data, *, base64):
    if not data:
        raise ValueError('缺少图片数据')

    mime_type = 'image/png'
    payload = data
    if ',' in data:
        header, payload = data.split(',', 1)
        if ';base64' not in header:
            raise ValueError('仅支持 base64 data URI')
        if header.startswith('data:'):
            mime_type = header[5:].split(';', 1)[0] or mime_type

    image_bytes = base64.b64decode(payload)
    extension = '.png'
    if '/' in mime_type:
        subtype = mime_type.split('/', 1)[1].split('+', 1)[0].lower()
        if subtype in ('jpeg', 'jpg'):
            extension = '.jpg'
        elif subtype == 'webp':
            extension = '.webp'

    return image_bytes, mime_type, extension


def _upload_comfy_image(image_data, *, _decode_data_uri_image, _new_comfy_session, get_comfy_config, random, time):
    image_bytes, mime_type, extension = _decode_data_uri_image(image_data)
    filename = f"miniapp_{int(time.time())}_{random.randint(1000, 9999)}{extension}"

    config = get_comfy_config()
    with _new_comfy_session() as session:
        response = session.post(
            f"{config['base_url']}/upload/image",
            files={'image': (filename, image_bytes, mime_type)},
            data={'type': 'input', 'overwrite': 'true'},
            timeout=config['timeout_seconds'],
        )
        response.raise_for_status()
        result = response.json()

    return result.get('name') or filename


def _prepare_comfy_workflow(
    workflow,
    prompt,
    ratio,
    uploaded_image_name=None,
    uploaded_image_names=None,
    resolution='1k',
    width=None,
    height=None,
    *,
    _normalize_comfy_dimension,
    _replace_comfy_tokens,
    _resolve_comfy_size,
    json,
    random,
):
    fallback_width, fallback_height = _resolve_comfy_size(ratio, resolution)
    width = _normalize_comfy_dimension(width, fallback_width)
    height = _normalize_comfy_dimension(height, fallback_height)
    prepared = json.loads(json.dumps(workflow))
    image_names = [str(name).strip() for name in (uploaded_image_names or []) if str(name).strip()]
    if uploaded_image_name and uploaded_image_name not in image_names:
        image_names.insert(0, uploaded_image_name)
    replacements = {
        '{{PROMPT}}': prompt or '',
        '{{WIDTH}}': width,
        '{{HEIGHT}}': height,
        '{{SEED}}': random.randint(1, 2**31 - 1),
        '{{IMAGE}}': image_names[0] if image_names else '',
    }
    for index, image_name in enumerate(image_names, start=1):
        replacements[f'{{{{IMAGE_{index}}}}}'] = image_name
    prepared = _replace_comfy_tokens(prepared, replacements)

    load_image_index = 0
    for node in prepared.values():
        if not isinstance(node, dict):
            continue

        class_type = str(node.get('class_type') or '')
        class_key = class_type.lower().replace('_', '')
        inputs = node.get('inputs') if isinstance(node.get('inputs'), dict) else None
        if not inputs:
            continue

        if class_type == 'EmptyLatentImage':
            inputs['width'] = width
            inputs['height'] = height
        else:
            if 'width' in inputs and not isinstance(inputs.get('width'), (dict, list)):
                inputs['width'] = width
            if 'height' in inputs and not isinstance(inputs.get('height'), (dict, list)):
                inputs['height'] = height

        if prompt and isinstance(inputs.get('prompt'), str):
            inputs['prompt'] = prompt

        if image_names and 'loadimage' in class_key and 'image' in inputs and not isinstance(inputs.get('image'), (dict, list)):
            inputs['image'] = image_names[min(load_image_index, len(image_names) - 1)]
            load_image_index += 1

    return prepared


def _proxy_comfy_json(method, path, *, params=None, payload=None, _new_comfy_session, get_comfy_config):
    config = get_comfy_config()
    with _new_comfy_session() as session:
        response = session.request(
            method,
            f"{config['base_url']}{path}",
            params=params,
            json=payload,
            timeout=config['timeout_seconds'],
        )
        response.raise_for_status()
        return response.json()


def _fetch_comfy_binary(filename, subfolder='', file_type='output', *, _new_comfy_session, get_comfy_config):
    params = {
        'filename': filename,
        'subfolder': subfolder or '',
        'type': file_type or 'output',
    }
    config = get_comfy_config()
    with _new_comfy_session() as session:
        response = session.get(
            f"{config['base_url']}/view",
            params=params,
            timeout=config['timeout_seconds'],
        )
        response.raise_for_status()
        return response.content, response.headers.get('Content-Type', 'application/octet-stream')


def _find_comfy_images(outputs):
    if not isinstance(outputs, dict):
        return []

    final_images = []
    temp_images = []
    seen = set()
    for node_output in outputs.values():
        images = node_output.get('images') if isinstance(node_output, dict) else None
        if not images:
            continue
        for image in images:
            if not isinstance(image, dict):
                continue
            key = (image.get('filename'), image.get('subfolder'), image.get('type'))
            if not key[0] or key in seen:
                continue
            seen.add(key)
            if image.get('type') == 'output':
                final_images.append(image)
            else:
                temp_images.append(image)

    return final_images or temp_images


def _find_best_comfy_image(outputs, *, _find_comfy_images):
    images = _find_comfy_images(outputs)
    return images[0] if images else None


def _save_task_params(task_id, params, *, json, update_task_fields):
    update_task_fields(task_id, params=json.dumps(params, ensure_ascii=False))


def _extract_comfy_error(entry):
    status = entry.get('status') if isinstance(entry, dict) else {}
    if isinstance(status, dict):
        for key in ('messages', 'error', 'status_str'):
            value = status.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, list) and value:
                return str(value[-1])
    return 'ComfyUI 任务失败'


def _sync_comfy_task(
    prompt_id,
    entry,
    *,
    _extract_comfy_error,
    _find_comfy_images,
    get_task,
    json,
    update_task,
    update_task_status,
):
    task = get_task(prompt_id)
    if not task:
        return

    status = entry.get('status') if isinstance(entry, dict) else {}
    outputs = entry.get('outputs') if isinstance(entry, dict) else {}
    completed = bool(status.get('completed')) if isinstance(status, dict) else False
    status_str = str(status.get('status_str', '') if isinstance(status, dict) else '').lower()
    comfy_images = _find_comfy_images(outputs)
    comfy_image = comfy_images[0] if comfy_images else None

    params = task.get('params') or {}
    updated_params = dict(params)
    if comfy_image:
        updated_params['comfy_image'] = comfy_image
        updated_params['comfy_images'] = comfy_images

    if completed and comfy_image:
        update_task_status(
            prompt_id,
            'processing',
            'ComfyUI 已完成，正在整理结果...',
            stage='comfy_completed',
            result_file=comfy_image.get('filename'),
            params=json.dumps(updated_params, ensure_ascii=False),
        )
        return {
            'completed': True,
            'image': comfy_image,
            'images': comfy_images,
            'params': updated_params,
            'progress_text': 'ComfyUI 已完成，正在整理结果...',
        }

    if completed and not comfy_image:
        error_msg = _extract_comfy_error(entry)
        update_task(
            prompt_id,
            'failed',
            error=error_msg,
            stage='failed',
            progress_text=error_msg,
            params=json.dumps(updated_params, ensure_ascii=False),
        )
        return {
            'completed': True,
            'error': error_msg,
            'params': updated_params,
            'progress_text': error_msg,
        }

    progress_text = 'ComfyUI 生成中...'
    if status_str:
        progress_text = f'ComfyUI {status_str}...'
    update_task_status(
        prompt_id,
        'processing',
        progress_text,
        stage='processing',
        params=json.dumps(updated_params, ensure_ascii=False),
    )
    return {
        'completed': False,
        'params': updated_params,
        'progress_text': progress_text,
    }


def _fetch_comfy_history_entry(prompt_id, *, _proxy_comfy_json, urllib):
    result = _proxy_comfy_json('GET', f'/history/{urllib.parse.quote(prompt_id)}')
    if isinstance(result, dict) and prompt_id not in result and 'outputs' in result:
        result = {prompt_id: result}
    entry = result.get(prompt_id) if isinstance(result, dict) else None
    return result, entry
