"""Existing generation option, lineage and output metadata normalization.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _coerce_gpt_image_count(data, prompt='', *, MAX_GPT_IMAGE_COUNT, re):
    """Accept frontend count aliases, with a light prompt fallback."""
    aliases = ('image_count', 'imageCount', 'count', 'n', 'num_images', 'numImages')
    raw = None
    for key in aliases:
        if key in data:
            raw = data.get(key)
            break

    if raw is None and prompt:
        text = str(prompt)
        match = re.search(r'(?:生成|出|做|来)?\s*([1-8])\s*(?:张|幅|个|images?|pics?)', text, re.I)
        if not match:
            cn_digits = {
                '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
                '六': 6, '七': 7, '八': 8,
            }
            match = re.search(r'(?:生成|出|做|来)?\s*([一二两三四五六七八])\s*(?:张|幅|个)', text)
            raw = cn_digits.get(match.group(1)) if match else None
        else:
            raw = match.group(1)

    try:
        count = int(raw or 1)
    except (TypeError, ValueError):
        count = 1
    return max(1, min(MAX_GPT_IMAGE_COUNT, count))


def _coerce_gpt_quality(value):
    quality = str(value or 'auto').strip().lower()
    return quality if quality in ('low', 'medium', 'high', 'auto') else 'auto'


def _coerce_gpt_moderation(value):
    moderation = str(value or 'auto').strip().lower()
    return moderation if moderation in ('auto', 'low') else 'auto'


def _coerce_prompt_mode(value):
    mode = str(value or 'smart').strip().lower()
    if mode in ('faithful', 'literal', '忠实原文'):
        return 'faithful'
    if mode in ('web_search', 'search', 'research', '联网检索', '联网搜索'):
        return 'web_search'
    return 'smart'


def _is_generic_19_fidelity_prompt(prompt, *, GENERIC_19_FIDELITY_MARKER, GENERIC_19_LEGACY_FIDELITY_MARKERS):
    prompt_text = str(prompt or '')
    return any(
        marker in prompt_text
        for marker in (GENERIC_19_FIDELITY_MARKER, *GENERIC_19_LEGACY_FIDELITY_MARKERS)
    )


def _effective_prompt_mode(prompt, value, *, _coerce_prompt_mode, _is_generic_19_fidelity_prompt):
    if _is_generic_19_fidelity_prompt(prompt):
        return 'faithful'
    return _coerce_prompt_mode(value)


def _coerce_gpt_task_type(value):
    task_type = str(value or 'image').strip().lower()
    if task_type in ('ppt', 'powerpoint', 'presentation'):
        return 'ppt'
    if task_type in ('psd', 'photoshop'):
        return 'psd'
    return 'image'


def _coerce_bool(value, default=True):
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    raw = str(value).strip().lower()
    if raw in {'1', 'true', 'yes', 'on', 'enabled', '开启'}:
        return True
    if raw in {'0', 'false', 'no', 'off', 'disabled', '关闭'}:
        return False
    return bool(default)


def _coerce_use_third_party_api(*values, _coerce_bool):
    for value in values:
        if value is not None:
            return _coerce_bool(value, False)
    return False


def _coerce_gpt_provider_route(value):
    route = str(value or 'codex').strip().lower()
    if route in ('managed_codex_oauth', 'managed_codex', 'managed_oauth', 'codex_oauth', 'oauth_codex'):
        return 'codex'
    if route in ('chatgpt_pool', 'pool', 'sidecar', 'web_api', 'account_pool'):
        return 'chatgpt_pool'
    if route in ('third_party_image_api', 'third_party_api', 'third_party', 'external_api', 'yunwu'):
        return 'third_party_image_api'
    if route in ('codex', 'local', 'local_codex'):
        return 'codex'
    return 'codex'


def _gpt_route_uses_third_party(route, *, _coerce_gpt_provider_route):
    return _coerce_gpt_provider_route(route) == 'third_party_image_api'


def _resolve_codex_provider_env(
    *,
    get_managed_codex_oauth_status,
    get_managed_codex_provider_env,
) -> tuple[dict | None, str]:
    """Prefer project-managed Codex OAuth, then fall back to local Codex auth."""
    try:
        managed_status = get_managed_codex_oauth_status()
    except Exception as exc:
        print(f"⚠️ managed Codex status unavailable: {exc}")
        managed_status = {}

    if managed_status.get("enabled") and managed_status.get("configured"):
        try:
            return get_managed_codex_provider_env(), "managed_codex_oauth"
        except Exception as exc:
            print(f"⚠️ managed Codex auth unavailable; falling back to local Codex: {exc}")

    return None, "codex"


def _coerce_gpt_main_model(value, *, DEFAULT_GPT_IMAGE_MAIN_MODEL, get_gpt_provider_config, normalize_model_id):
    if value in (None, ''):
        value = get_gpt_provider_config().get('image_main_model')
    return normalize_model_id(value, DEFAULT_GPT_IMAGE_MAIN_MODEL)


def _coerce_gpt_reasoning_effort(
    value,
    *,
    DEFAULT_GPT_REASONING_EFFORT,
    VALID_GPT_REASONING_EFFORTS,
    get_gpt_provider_config,
):
    if value in (None, ''):
        value = get_gpt_provider_config().get('reasoning_effort')
    effort = str(value or DEFAULT_GPT_REASONING_EFFORT).strip().lower()
    return effort if effort in VALID_GPT_REASONING_EFFORTS else DEFAULT_GPT_REASONING_EFFORT


def _coerce_gpt_transport_mode(
    value,
    *,
    DEFAULT_GPT_TRANSPORT_MODE,
    VALID_GPT_TRANSPORT_MODES,
    get_gpt_provider_config,
):
    if value in (None, ''):
        value = get_gpt_provider_config().get('transport_mode')
    mode = str(value or DEFAULT_GPT_TRANSPORT_MODE).strip().lower()
    return mode if mode in VALID_GPT_TRANSPORT_MODES else DEFAULT_GPT_TRANSPORT_MODE


def _coerce_gpt_provider_total_timeout(value, *, DEFAULT_GPT_PROVIDER_TOTAL_TIMEOUT_SECONDS, get_gpt_provider_config):
    if value in (None, ''):
        value = get_gpt_provider_config().get('total_timeout_seconds')
    try:
        timeout = int(value or DEFAULT_GPT_PROVIDER_TOTAL_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        timeout = DEFAULT_GPT_PROVIDER_TOTAL_TIMEOUT_SECONDS
    return max(30, min(1800, timeout))


def _coerce_image_ratio(value, default='1:1', *, VALID_IMAGE_RATIOS):
    ratio = str(value or '').strip().lower()
    return ratio if ratio in VALID_IMAGE_RATIOS else default


def _effective_image_ratio(
    prompt,
    value,
    default='1:1',
    *,
    VALID_IMAGE_RATIOS,
    _coerce_image_ratio,
    _is_generic_19_fidelity_prompt,
    re,
):
    """Honor the source ratio embedded by a complete generic_19 bundle."""
    selected = _coerce_image_ratio(value, default)
    if not _is_generic_19_fidelity_prompt(prompt):
        return selected
    match = re.search(r'【原图比例\s*[：:]\s*([0-9]+\s*:\s*[0-9]+)】', str(prompt or ''))
    if not match:
        return selected
    locked_ratio = re.sub(r'\s+', '', match.group(1))
    return locked_ratio if locked_ratio in VALID_IMAGE_RATIOS else selected


def _coerce_gpt_resolution(value):
    resolution = str(value or '1k').strip().lower()
    return resolution if resolution in ('1k', '2k', '4k') else '1k'


def _result_path_dimensions(path_value, *, Image, PROJECT_ROOT, Path):
    path_text = str(path_value or '').strip()
    if not path_text:
        return None
    try:
        path = Path(path_text)
    except Exception:
        return None
    if not path.is_absolute():
        path = PROJECT_ROOT / path_text.lstrip('/\\')
    try:
        with Image.open(path) as img:
            return img.size
    except Exception:
        return None


def _result_actual_sizes(result, *, _result_path_dimensions, normalize_actual_sizes):
    result = result if isinstance(result, dict) else {}
    sizes = normalize_actual_sizes(result.get('actual_sizes'))
    if sizes:
        return sizes
    paths = []
    for item in result.get('image_paths') or []:
        if item:
            paths.append(item)
    if result.get('image_path'):
        paths.append(result.get('image_path'))
    discovered = []
    seen = set()
    for item in paths:
        key = str(item or '').strip()
        if not key or key in seen:
            continue
        seen.add(key)
        dimensions = _result_path_dimensions(key)
        if dimensions:
            discovered.append({'width': dimensions[0], 'height': dimensions[1]})
    return discovered


def _augment_result_resolution_metadata(
    result,
    requested_resolution,
    *,
    _result_actual_sizes,
    build_resolution_metadata,
):
    if not isinstance(result, dict):
        return {}
    metadata = build_resolution_metadata(
        requested_resolution,
        _result_actual_sizes(result),
        result.get('requested_size'),
    )
    for key, value in metadata.items():
        if value not in (None, ''):
            result[key] = value
    return metadata


def _coerce_google_quality(value, default='2k'):
    quality = str(value or default).strip().lower()
    aliases = {
        'standard': '1k',
        'normal': '1k',
        'hd': '4k',
    }
    quality = aliases.get(quality, quality)
    return quality if quality in ('1k', '2k', '4k') else default


def _coerce_google_edit_quality(value):
    quality = str(value or 'hd').strip().lower()
    if quality in ('1k', 'standard', 'normal'):
        return 'standard'
    return 'hd' if quality in ('2k', '4k', 'hd') else 'hd'


def _coerce_model(value, default):
    model = str(value or '').strip()
    aliases = {
        'gemini-3-pro-image-preview': 'gemini-3-pro-image',
        'gemini-3.1-flash-image-preview': 'gemini-3.1-flash-image',
    }
    return aliases.get(model, model) or default


def _coerce_google_max_tokens(value, default):
    try:
        tokens = int(value)
    except Exception:
        tokens = default
    return tokens if tokens > 0 else default


def _coerce_google_temperature(value):
    if value is None or value == '':
        return None
    try:
        return float(value)
    except Exception:
        return None


def _coerce_google_output_controls(params, *, _coerce_bool):
    params = params if isinstance(params, dict) else {}
    archive_enabled = _coerce_bool(params.get('archive_enabled', params.get('archiveEnabled')), True)
    telegram_enabled = _coerce_bool(params.get('telegram_enabled', params.get('telegramEnabled')), True)
    return archive_enabled, telegram_enabled


def _short_text(value, limit=500):
    text = " ".join(str(value or "").split())
    return text[:limit]


def _stable_lineage_url(value):
    url = str(value or "").strip()
    if not url or url.startswith("data:") or url.startswith("blob:"):
        return ""
    return url[:500]


def _normalize_lineage_reference(item, index=0, *, _short_text, _stable_lineage_url):
    if not isinstance(item, dict):
        return None
    asset_id = _short_text(item.get("asset_id") or item.get("assetId") or item.get("id"), 120)
    task_id = _short_text(item.get("task_id") or item.get("taskId"), 120)
    # History/canvas IDs are not gallery asset IDs. Keep the task locator so the
    # index can resolve the exact output without persisting the incorrect alias.
    if asset_id == task_id:
        asset_id = ""
    image_url = _stable_lineage_url(item.get("image_url") or item.get("imageUrl") or item.get("imagePath") or item.get("url"))
    source_node_id = _short_text(item.get("source_node_id") or item.get("sourceNodeId"), 120)
    if not asset_id and not task_id and not image_url and not source_node_id:
        return None
    return {
        "asset_id": asset_id,
        "task_id": task_id,
        "image_url": image_url,
        "title": _short_text(item.get("title") or item.get("name") or item.get("file") or f"参考图 {index + 1}", 160),
        "prompt": _short_text(item.get("prompt"), 500),
        "file": _short_text(item.get("file"), 180),
        "source": _short_text(item.get("source"), 48),
        "source_node_id": source_node_id,
        "index": index,
    }


def _extract_lineage_payload(data, *, _normalize_lineage_reference):
    if not isinstance(data, dict):
        return {}
    raw = data.get("lineage") if isinstance(data.get("lineage"), dict) else {}
    raw_refs = raw.get("reference_assets") or raw.get("referenceAssets") or data.get("reference_assets") or data.get("referenceAssets") or []
    refs = []
    seen = set()
    if isinstance(raw_refs, list):
        for index, item in enumerate(raw_refs[:16]):
            ref = _normalize_lineage_reference(item, index)
            if not ref:
                continue
            key = ref.get("asset_id") or (f"{ref.get('task_id')}:{ref.get('image_url')}:{ref.get('file')}" if ref.get("task_id") or ref.get("image_url") or ref.get("file") else "") or ref.get("source_node_id")
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    if not refs:
        return {}
    asset_ids = []
    task_ids = []
    for ref in refs:
        if ref.get("asset_id") and ref["asset_id"] not in asset_ids:
            asset_ids.append(ref["asset_id"])
        if ref.get("task_id") and ref["task_id"] not in task_ids:
            task_ids.append(ref["task_id"])
    return {
        "reference_assets": refs,
        "reference_asset_ids": asset_ids,
        "source_task_ids": task_ids,
    }


def _attach_lineage_params(params, data, *, _extract_lineage_payload):
    lineage = _extract_lineage_payload(data)
    if lineage:
        params["lineage"] = lineage
    return params


def _result_image_filenames(result, *, os):
    paths = result.get('image_paths') or [result.get('image_path')]
    filenames = []
    for path in paths:
        if not path:
            continue
        filename = os.path.basename(str(path))
        if filename and filename not in filenames:
            filenames.append(filename)
    return filenames
