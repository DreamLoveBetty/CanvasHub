"""ComfyUI workflow catalog and parameter policies.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _new_comfy_session(*, requests):
    session = requests.Session()
    session.trust_env = False
    session.proxies = {}
    session.headers.update({'User-Agent': 'MiniApp-ComfyProxy/1.0'})
    return session


def _comfy_workflow_catalog_settings(*, load_app_settings):
    settings = load_app_settings()
    section = settings.get('comfy') if isinstance(settings.get('comfy'), dict) else {}
    catalog = section.get('workflow_catalog') if isinstance(section.get('workflow_catalog'), dict) else {}
    return catalog


def _comfy_workflow_preview_path(workflow_name, *, COMFY_PREVIEW_DIR, Path, hashlib):
    safe_name = Path(str(workflow_name or '')).name
    digest = hashlib.sha256(safe_name.encode('utf-8')).hexdigest()[:20]
    return COMFY_PREVIEW_DIR / f'{digest}.webp'


def _comfy_workflow_uses_token(path, token):
    try:
        return token in path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return False


def _default_comfy_workflow_label(filename, *, Path):
    stem = Path(filename).stem.replace('_', ' ').replace('-', ' ').strip()
    aliases = {
        'sd15 text to image': 'SD 1.5 文生图',
        'lumina 2 upscale': 'Lumina 2 放大',
    }
    return aliases.get(stem.lower(), stem or filename)


def _comfy_parameter_label(name, *, COMFY_PARAMETER_LABELS):
    label = COMFY_PARAMETER_LABELS.get(name)
    if label:
        return label
    readable = str(name or '').replace('_', ' ').strip()
    return f'自定义参数（{readable or "未命名"}）'


def _normalize_comfy_dimension(value, fallback=1024, *, COMFY_DIMENSION_MAX, COMFY_DIMENSION_MIN, COMFY_DIMENSION_STEP):
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        try:
            number = int(round(float(fallback)))
        except (TypeError, ValueError):
            number = 1024
    number = max(COMFY_DIMENSION_MIN, min(COMFY_DIMENSION_MAX, number))
    number = int(round(number / COMFY_DIMENSION_STEP) * COMFY_DIMENSION_STEP)
    return max(COMFY_DIMENSION_MIN, min(COMFY_DIMENSION_MAX, number))


def _extract_comfy_workflow_default_size(workflow, fallback=(1024, 1024), *, _normalize_comfy_dimension):
    fallback_width = _normalize_comfy_dimension(fallback[0] if fallback else 1024, 1024)
    fallback_height = _normalize_comfy_dimension(fallback[1] if fallback else 1024, 1024)
    if not isinstance(workflow, dict):
        return fallback_width, fallback_height
    candidates = []
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get('inputs') if isinstance(node.get('inputs'), dict) else {}
        raw_width = inputs.get('width')
        raw_height = inputs.get('height')
        if isinstance(raw_width, bool) or isinstance(raw_height, bool):
            continue
        if isinstance(raw_width, (dict, list)) or isinstance(raw_height, (dict, list)):
            continue
        try:
            width = float(raw_width)
            height = float(raw_height)
        except (TypeError, ValueError):
            continue
        priority = 0 if str(node.get('class_type') or '').lower() == 'emptylatentimage' else 1
        candidates.append((priority, width, height))
    if not candidates:
        return fallback_width, fallback_height
    _, width, height = min(candidates, key=lambda item: item[0])
    return _normalize_comfy_dimension(width, fallback_width), _normalize_comfy_dimension(height, fallback_height)


def _comfy_workflow_has_image_input(workflow):
    if not isinstance(workflow, dict):
        return False
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        class_key = str(node.get('class_type') or '').lower().replace('_', '')
        inputs = node.get('inputs') if isinstance(node.get('inputs'), dict) else {}
        if 'loadimage' in class_key and 'image' in inputs:
            return True
    return False


def _comfy_ratio_from_size(width, height, *, _normalize_comfy_dimension, math):
    width = _normalize_comfy_dimension(width, 1024)
    height = _normalize_comfy_dimension(height, 1024)
    divisor = math.gcd(width, height) or 1
    return f'{width // divisor}:{height // divisor}'


def _comfy_parameter_number_bounds(name, value):
    specs = {
        'seed': (-1, 2**31 - 1, 1),
        'steps': (1, 200, 1),
        'cfg': (0, 100, 0.1),
        'denoise': (0, 1, 0.01),
        'strength_model': (-10, 10, 0.05),
        'strength_clip': (-10, 10, 0.05),
        'scale_by': (0.1, 8, 0.05),
        'batch_size': (1, 8, 1),
        'resolution': (64, 8192, 64),
        'max_resolution': (0, 8192, 64),
        'input_noise_scale': (0, 10, 0.01),
        'latent_noise_scale': (0, 10, 0.01),
        'temporal_overlap': (0, 256, 1),
        'prepend_frames': (0, 256, 1),
        'blocks_to_swap': (0, 128, 1),
    }
    if name in specs:
        return specs[name]
    if isinstance(value, int) and not isinstance(value, bool):
        return (-1000000, 1000000, 1)
    return (-1000000, 1000000, 0.01)


def _extract_comfy_workflow_parameters(
    workflow,
    *,
    COMFY_PARAMETER_EXCLUDED_INPUTS,
    COMFY_PARAMETER_OPTIONS,
    _comfy_parameter_label,
    _comfy_parameter_number_bounds,
):
    if not isinstance(workflow, dict):
        return []
    parameters = []
    for raw_node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        node_id = str(raw_node_id)
        class_type = str(node.get('class_type') or 'Node').strip()
        class_key = class_type.lower()
        if class_type in ('SaveImage', 'PreviewImage') or class_key.endswith('loader') or 'loadmodel' in class_key:
            continue
        inputs = node.get('inputs') if isinstance(node.get('inputs'), dict) else {}
        node_title = str((node.get('_meta') or {}).get('title') or class_type).strip()[:100]
        for raw_name, raw_value in inputs.items():
            name = str(raw_name)
            if name in COMFY_PARAMETER_EXCLUDED_INPUTS or (name.startswith('text_') and name[5:].isdigit()):
                continue
            if isinstance(raw_value, (dict, list)) or raw_value is None:
                continue
            if not isinstance(raw_value, (str, int, float, bool)):
                continue
            value = raw_value
            if isinstance(value, str) and '{{' in value:
                if name != 'seed':
                    continue
                value = -1
            parameter_type = 'text'
            parameter = {
                'id': f'{node_id}:{name}',
                'node_id': node_id,
                'input_name': name,
                'node_title': node_title,
                'class_type': class_type,
                'label': _comfy_parameter_label(name),
                'default': value,
            }
            if isinstance(value, bool):
                parameter_type = 'boolean'
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                parameter_type = 'number'
                minimum, maximum, step = _comfy_parameter_number_bounds(name, value)
                parameter.update({'min': minimum, 'max': maximum, 'step': step})
            elif name in COMFY_PARAMETER_OPTIONS:
                parameter_type = 'select'
                options = list(COMFY_PARAMETER_OPTIONS[name])
                if value not in options:
                    options.insert(0, value)
                parameter['options'] = options
            parameter['type'] = parameter_type
            parameters.append(parameter)
            if len(parameters) >= 256:
                return parameters
    return parameters


def _coerce_comfy_parameter_value(parameter, value, *, _coerce_bool):
    parameter_type = parameter.get('type')
    if parameter_type == 'boolean':
        return _coerce_bool(value, bool(parameter.get('default')))
    if parameter_type == 'number':
        try:
            number = float(value)
        except (TypeError, ValueError):
            return parameter.get('default')
        number = max(float(parameter.get('min', -1000000)), min(float(parameter.get('max', 1000000)), number))
        step = float(parameter.get('step', 1) or 1)
        if isinstance(parameter.get('default'), int) and not isinstance(parameter.get('default'), bool) and step.is_integer():
            return int(round(number))
        return number
    if parameter_type == 'select':
        text = str(value or '')
        return text if text in (parameter.get('options') or []) else parameter.get('default')
    return str(value or '')[:4096]


def _apply_comfy_parameter_overrides(
    workflow,
    overrides,
    *,
    _coerce_comfy_parameter_value,
    _extract_comfy_workflow_parameters,
):
    if not isinstance(overrides, dict) or not overrides:
        return workflow, {}
    schema = {item['id']: item for item in _extract_comfy_workflow_parameters(workflow)}
    applied = {}
    for parameter_id, raw_value in overrides.items():
        parameter = schema.get(str(parameter_id))
        if not parameter:
            continue
        node = workflow.get(parameter['node_id'])
        inputs = node.get('inputs') if isinstance(node, dict) and isinstance(node.get('inputs'), dict) else None
        if inputs is None:
            continue
        value = _coerce_comfy_parameter_value(parameter, raw_value)
        inputs[parameter['input_name']] = value
        applied[parameter['id']] = value
    return workflow, applied
