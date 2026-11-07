"""ComfyUI workflow preparation and existing remote API calls.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations

from .comfy_video import MAX_VIDEOS, fill_video_loaders, video_token_replacements, workflow_video_io
from .comfy_audio import MAX_AUDIOS
from .comfy_workflow_switches import (apply_workflow_switches, collect_workflow_switches, has_switches,
                                      resolve_switch_choices, strip_switch_tags, unknown_title_tags)
from .comfy_workflow_tags import (apply_tagged_inputs, collect_workflow_tags, empty_media_slots, media_loader_ids,
                                  randomize_seeds, workflow_tag_summary)

MAX_TAGGED_IMAGES = 12

# ComfyUI's plain "Save" writes the editor (UI) format: top-level `nodes` / `links` lists. The /prompt API and
# the title tags only understand the "Export (API)" format, so a UI file is flagged instead of guessed at.
COMFY_UI_FORMAT_ERROR = '这是 ComfyUI 的 UI 格式（「保存」导出），无法识别节点标题也不能运行。请在 ComfyUI 中用「导出 (API)」重新导出后覆盖此文件。'


def is_ui_format_workflow(workflow):
    return isinstance(workflow, dict) and isinstance(workflow.get('nodes'), list) and isinstance(workflow.get('links'), list)


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
            raw_text = path.read_text(encoding='utf-8')
            workflow_data = json.loads(raw_text)
        except Exception:
            raw_text, workflow_data = '', {}
        ui_format = is_ui_format_workflow(workflow_data)
        if ui_format:
            workflow_data = {}
        video_io = workflow_video_io(workflow_data, raw_text)
        tag_info, _tags = workflow_tag_summary(workflow_data, raw_text)
        tagged = tag_info['tag_mode'] == 'tags'
        switches = collect_workflow_switches(workflow_data) if tagged else None
        switchable = bool(switches and has_switches(switches))
        tag_warnings = [*tag_info['tag_warnings'], *(switches['warnings'] if switches else []),
                        *(unknown_title_tags(workflow_data) if tagged else [])][:20]
        parameters = _extract_comfy_workflow_parameters(workflow_data)
        default_ratio = str(meta.get('default_ratio') or '1:1')
        ratio_width, ratio_height = _resolve_comfy_size(default_ratio, '1k')
        detected_width, detected_height = _extract_comfy_workflow_default_size(
            workflow_data,
            (ratio_width, ratio_height),
        )
        default_width = _normalize_comfy_dimension(meta.get('default_width'), detected_width)
        default_height = _normalize_comfy_dimension(meta.get('default_height'), detected_height)
        auto_accepts_image = tag_info['accepts_image'] if tagged else (
            _comfy_workflow_uses_token(path, '{{IMAGE}}')
            or _comfy_workflow_uses_token(path, '{{IMAGE_')
            or _comfy_workflow_has_image_input(workflow_data)
        )
        accepts_image = _coerce_bool(meta.get('accepts_image'), auto_accepts_image)
        accepts_video = _coerce_bool(meta.get('accepts_video'), tag_info['accepts_video'] if tagged else video_io['accepts_video'])
        accepts_audio = bool(tagged and tag_info['accepts_audio'])
        output_kind = meta.get('output_kind') if meta.get('output_kind') in ('image', 'video') else video_io['output_kind']
        enabled = _coerce_bool(meta.get('enabled'), True)
        if not include_disabled and not enabled:
            continue
        image_slots = max(1, tag_info['image_slots']) if tagged else 1
        video_slots = max(1, tag_info['video_slots']) if tagged else 1
        max_images = bounded_int(meta.get('max_images'), image_slots if accepts_image else 0, 0, MAX_TAGGED_IMAGES if tagged else 8)
        max_videos = bounded_int(meta.get('max_videos'), video_slots if accepts_video else 0, 0, MAX_VIDEOS)
        max_audios = min(tag_info['audio_slots'], MAX_AUDIOS) if accepts_audio else 0
        output_count = bounded_int(meta.get('output_count'), 1, 1, 8)
        preview_path = _comfy_workflow_preview_path(workflow_id)
        label = str(meta.get('label') or _default_comfy_workflow_label(workflow_id)).strip()[:120]
        if output_kind == 'video' and switchable and len(switches['branches']) >= 2:
            default_summary = ' / '.join(item['name'] for item in switches['branches']) + ' · 可切换'
        elif output_kind == 'video':
            default_summary = '视频转视频 · 需要视频' if accepts_video else ('图生视频 · 需要参考图' if accepts_image else '文生视频')
        else:
            default_summary = '图生图 · 需要参考图' if accepts_image else '文生图 · 单图'
        if ui_format:
            default_summary = 'UI 格式 · 需改用「导出 (API)」'
        summary = str(meta.get('summary') or default_summary).strip()[:180]
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
            'accepts_text': _coerce_bool(meta.get('accepts_text'), tag_info['accepts_text'] if tagged else True),
            'accepts_image': accepts_image,
            'max_images': max_images,
            'accepts_video': accepts_video,
            'max_videos': max_videos,
            'accepts_audio': accepts_audio,
            'max_audios': max_audios,
            'switchable': switchable,
            'output_kind': output_kind,
            'output_count': output_count,
            'tag_mode': tag_info['tag_mode'],
            'default_prompt': tag_info['default_prompt'],
            'size_editable': tag_info['size_editable'],
            'tag_warnings': tag_warnings,
            'accepts_negative': tag_info['accepts_negative'],
            'input_slots': tag_info['input_slots'],
            'format_error': COMFY_UI_FORMAT_ERROR if ui_format else '',
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
    if data.get('output_kind') in ('image', 'video', ''):
        if data.get('output_kind'):
            meta['output_kind'] = data.get('output_kind')
        else:
            meta.pop('output_kind', None)
    for key in ('enabled', 'is_default', 'accepts_text', 'accepts_image', 'accepts_video'):
        if key in data:
            meta[key] = _coerce_bool(data.get(key), False)
    for key, minimum, maximum in (('order', 0, 9999), ('max_images', 0, 8), ('max_videos', 0, MAX_VIDEOS), ('output_count', 1, 8)):
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
        workflow = json.load(f)
    if is_ui_format_workflow(workflow):
        raise ValueError(f'{workflow_path.name}：{COMFY_UI_FORMAT_ERROR}')
    return workflow, workflow_path.name


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
    uploaded_video_names=None,
    negative_prompt='',
    uploaded_audio_names=None,
    workflow_parameters=None,
    report=None,
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
    # Read tags before token replacement so token-composed prompt fields are recognised.
    tags = collect_workflow_tags(workflow)
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
    replacements.update(video_token_replacements(uploaded_video_names))
    prepared = _replace_comfy_tokens(prepared, replacements)
    if tags['tagged']:
        # Tagged slots are positional: keep empty entries so a skipped slot keeps the workflow's value
        # (switchable workflows instead detach empty slots, see comfy_workflow_switches).
        slot_images = list(uploaded_image_names or image_names)
        slot_videos = list(uploaded_video_names or [])
        slot_audios = list(uploaded_audio_names or [])
        prepared = apply_tagged_inputs(prepared, tags, prompt=prompt, negative_prompt=str(negative_prompt or '').strip(),
                                       width=width, height=height, image_names=slot_images, video_names=slot_videos,
                                       audio_names=slot_audios)
        report = report if isinstance(report, dict) else {}
        report['seeds'] = randomize_seeds(prepared, tags, random)
        switches = collect_workflow_switches(workflow)
        if has_switches(switches):
            choices = resolve_switch_choices(switches, workflow_parameters)
            empty = empty_media_slots(tags, image_names=slot_images, video_names=slot_videos, audio_names=slot_audios)
            apply_workflow_switches(prepared, switches, choices, media_ids=media_loader_ids(tags), empty_media_ids=empty)
            report['switches'] = choices
        return prepared

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

    return fill_video_loaders(prepared, uploaded_video_names)


class ComfyPromptRejected(RuntimeError):
    """ComfyUI answered 400 with its validation report ({'error': {...}, 'node_errors': {...}})."""

    def __init__(self, body):
        self.body = body if isinstance(body, dict) else {}
        super().__init__(describe_comfy_rejection(self.body))


def describe_comfy_rejection(body, workflow=None, limit=6):
    """One readable line per failed input, naming the node by id and title: '#272 创建视频 · chroma_subsampling：…'."""
    body = body if isinstance(body, dict) else {}
    error = body.get('error') if isinstance(body.get('error'), dict) else {}
    nodes = workflow if isinstance(workflow, dict) else {}
    lines = []
    for node_id, entry in (body.get('node_errors') or {}).items() if isinstance(body.get('node_errors'), dict) else ():
        node = nodes.get(str(node_id)) if isinstance(nodes.get(str(node_id)), dict) else {}
        title = strip_switch_tags((node.get('_meta') or {}).get('title')) or (entry or {}).get('class_type') or 'Node'
        for item in (entry or {}).get('errors') or []:
            if not isinstance(item, dict):
                continue
            field = str((item.get('extra_info') or {}).get('input_name') or '').strip()
            detail = str(item.get('details') or item.get('message') or '').strip()
            lines.append(f"#{node_id} {title}{f' · {field}' if field else ''}：{detail[:200]}")
    head = str(error.get('message') or 'ComfyUI 拒绝了这个工作流').strip()
    if not lines:
        detail = str(error.get('details') or '').strip()
        return f'ComfyUI 拒绝了工作流：{head}{f"（{detail[:300]}）" if detail else ""}'
    more = f'；另有 {len(lines) - limit} 处' if len(lines) > limit else ''
    return f"ComfyUI 拒绝了工作流（{head}）：{'；'.join(lines[:limit])}{more}"


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
        if response.status_code == 400:
            # /prompt validation failures carry the per-node reason; keep it instead of a bare "400 Bad Request".
            try:
                body = response.json()
            except ValueError:
                body = None
            if isinstance(body, dict) and ('node_errors' in body or 'error' in body):
                raise ComfyPromptRejected(body)
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
    _find_comfy_videos,
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
    params = task.get('params') or {}
    is_video = params.get('comfy_output_kind') == 'video'
    comfy_images = (_find_comfy_videos if is_video else _find_comfy_images)(outputs)
    comfy_image = comfy_images[0] if comfy_images else None

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
        if is_video and status_str == 'success':
            error_msg = 'ComfyUI 没有输出视频：请用 SaveVideo 或 Video Combine 保存为 MP4 / WebM / MOV'
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
