"""Shared image-enhancement task lifecycle: archive, sidecars, audit and delivery.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations
from dataclasses import dataclass
import json


@dataclass(frozen=True)
class EnhancementEngine:
    task_type: str
    provider: str
    models: dict
    normalize_model: object
    execute: object
    output_format: str = "png"
    parameter_key: str = ""
    display_name: str = "图像增强"



def _coerce_upscale_tile(value, fallback=256, minimum=64, maximum=2048):
    try:
        parsed = int(value)
    except Exception:
        parsed = fallback
    return max(minimum, min(maximum, parsed))


def _write_upscale_sidecar(output_path, prompt, params, result_meta, *, Path, write_obsidian_prompt_sidecar):
    sidecar = Path(output_path).with_suffix('.txt')
    lines = [
        str(prompt or '高清放大').strip() or '高清放大',
        '',
        f"task_type: {params.get('enhancement_type', 'upscale')}",
        f"model: {result_meta.model}",
        f"scale: {result_meta.scale}x",
        f"input_size: {result_meta.input_width}x{result_meta.input_height}",
        f"output_size: {result_meta.output_width}x{result_meta.output_height}",
        f"device: {result_meta.device}",
    ]
    parameter_key = params.get('enhancement_parameter_key')
    if parameter_key and isinstance(params.get(parameter_key), dict):
        lines.extend(['', parameter_key + '_parameters: ' + json.dumps(params[parameter_key], ensure_ascii=False, sort_keys=True)])
    lineage = params.get('lineage') if isinstance(params.get('lineage'), dict) else {}
    refs = lineage.get('reference_assets') if isinstance(lineage, dict) else []
    if refs:
        lines.append('')
        lines.append('source_refs:')
        for ref in refs[:8]:
            if not isinstance(ref, dict):
                continue
            title = ref.get('title') or ref.get('file') or ref.get('image_url') or ref.get('source_node_id') or 'source'
            lines.append(f"- {title}")
    try:
        write_obsidian_prompt_sidecar(Path(output_path), '\n'.join(lines), txt_path=sidecar)
    except Exception as exc:
        print(f"⚠️ 写入高清放大 sidecar 失败: {exc}")


def process_image_enhancement_task(
    task_id,
    prompt,
    image_data,
    params,
    *,
    Path,
    UPSCALE_MODELS,
    UPSCALE_MODEL_DIR,
    UpscaleRuntimeError,
    _coerce_bool,
    _coerce_upscale_tile,
    _decode_data_uri_image,
    _finalize_generation_task,
    _merge_task_params,
    _record_generation_event,
    _start_generation_audit,
    _translate_generation_failure,
    _upscale_progress_callback,
    _write_upscale_sidecar,
    daily_output_dir,
    datetime,
    normalize_upscale_model,
    os,
    random,
    re,
    save_thumbnail,
    send_status_notification,
    send_tg_document,
    tempfile,
    update_task_status,
    upscale_image_file,
    is_task_canceled=lambda task_id: False,
    engine=None,
):
    """后台线程：本地高清放大任务。"""
    temp_path = None
    run_id = ''
    task_kind = engine.task_type if engine else 'upscale'
    task_provider = engine.provider if engine else 'local_upscale'
    if engine:
        UPSCALE_MODELS, normalize_upscale_model, upscale_image_file = engine.models, engine.normalize_model, engine.execute
    params = dict(params or {})
    params['enhancement_type'] = task_kind
    if engine: params['enhancement_parameter_key'] = engine.parameter_key
    label = engine.display_name if engine else '高清放大'
    task_route = 'spandrel'
    try:
        model_name = normalize_upscale_model(params.get('model'))
        model_label = UPSCALE_MODELS.get(model_name, {}).get('label', model_name)
        task_route = UPSCALE_MODELS.get(model_name, {}).get('route', 'spandrel')
        if is_task_canceled(task_id):
            return
        archive_enabled = True
        telegram_enabled = _coerce_bool(params.get('telegram_enabled', params.get('telegramEnabled')), True)
        params = dict(params or {})
        params['archive_enabled'] = archive_enabled
        params['telegram_enabled'] = telegram_enabled
        params['model'] = model_name
        params['scale'] = UPSCALE_MODELS.get(model_name, {}).get('scale', 4)
        _merge_task_params(task_id, params)

        run_id = _start_generation_audit(
            task_id,
            task_kind,
            prompt,
            params,
            provider=task_provider,
            route=task_route,
            stage='preparing',
        )
        update_task_status(task_id, 'preparing', f'正在准备{label}...', stage='preparing', progress=4)
        send_status_notification(task_id, f'已提交{label}：{model_label}', '✅')

        image_bytes, _mime_type, extension = _decode_data_uri_image(image_data)
        with tempfile.NamedTemporaryFile(delete=False, suffix=extension or '.png') as tmp:
            tmp.write(image_bytes)
            temp_path = tmp.name

        now = datetime.now()
        timestamp = now.strftime('%Y%m%d_%H%M%S')
        model_slug = re.sub(r'[^a-zA-Z0-9]+', '_', model_name).strip('_').lower() or 'upscale'
        filename = f"{task_kind}_{model_slug}_{timestamp}_{random.randint(1000, 9999)}.{engine.output_format if engine else 'png'}"
        output_dir = daily_output_dir(now)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename

        update_task_status(task_id, 'processing', f'正在载入{label}模型...', stage='loading_model', progress=8)
        _record_generation_event(task_id, 'provider_call_started', f'开始执行本地{label}', stage='loading_model', payload={'provider': task_provider, 'route': task_route, 'model': model_name})
        result_meta = upscale_image_file(
            Path(temp_path),
            output_path,
            model_name=model_name,
            model_dir=UPSCALE_MODEL_DIR,
            device=params.get('device') or 'auto',
            tile_size=_coerce_upscale_tile(params.get('tile_size', params.get('tileSize')), 256),
            tile_overlap=_coerce_upscale_tile(params.get('tile_overlap', params.get('tileOverlap')), 32, minimum=0, maximum=256),
            progress=_upscale_progress_callback(task_id),
            cancelled=lambda: is_task_canceled(task_id),
        )

        if is_task_canceled(task_id):
            raise RuntimeError(f'{label}任务已取消')

        _write_upscale_sidecar(output_path, prompt, params, result_meta)
        save_thumbnail(str(output_path), filename)

        _merge_task_params(task_id, {
            'model': result_meta.model,
            'scale': result_meta.scale,
            'device': result_meta.device,
            'input_size': f'{result_meta.input_width}x{result_meta.input_height}',
            'output_size': f'{result_meta.output_width}x{result_meta.output_height}',
            'archive_dir': str(output_dir),
        })

        telegram_success = False
        if is_task_canceled(task_id):
            raise RuntimeError(f'{label}任务已取消')
        if telegram_enabled:
            update_task_status(task_id, 'processing', '正在发送高清结果到 Telegram...', stage='sending_telegram', progress=96)
            _record_generation_event(task_id, 'telegram_send_started', f'开始发送{label}结果到 Telegram', stage='sending_telegram')
            caption = f"{label} | {model_label} | {result_meta.input_width}x{result_meta.input_height} -> {result_meta.output_width}x{result_meta.output_height}"
            prompt_line = str(prompt or '').strip()
            if prompt_line:
                caption = f"{caption}\n{prompt_line[:400]}"
            try:
                send_tg_document(output_path, caption=caption[:1000])
                telegram_success = True
            except Exception as exc:
                print(f"❌ 高清放大 Telegram 发送失败：{exc}")
        else:
            update_task_status(task_id, 'processing', 'Telegram 已关闭，正在整理高清结果...', stage='saving', progress=98)
            _record_generation_event(task_id, 'telegram_send_skipped', '已按节点开关跳过 Telegram', stage='saving')

        if telegram_success or not telegram_enabled:
            progress_text = f'{label}完成' if telegram_enabled else f'{label}完成，已按节点开关跳过 Telegram'
            final_status = 'succeeded' if telegram_enabled else 'succeeded_no_telegram'
        else:
            progress_text = f'{label}完成，但 Telegram 发送失败'
            final_status = 'succeeded_no_telegram'

        if is_task_canceled(task_id):
            raise RuntimeError(f'{label}任务已取消')
        _finalize_generation_task(
            task_id,
            final_status,
            run_id=run_id,
            provider=task_provider,
            route=task_route,
            task_type=task_kind,
            result_file=filename,
            stage='done',
            progress_text=progress_text,
            result_files=[filename],
            image_count=1,
            extra={
                'model': result_meta.model,
                'scale': result_meta.scale,
                'device': result_meta.device,
                'output_size': f'{result_meta.output_width}x{result_meta.output_height}',
            },
        )
        _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload={'provider': task_provider, 'route': task_route, 'model': model_name, 'scale': result_meta.scale})
        send_status_notification(task_id, f'✅ {label}完成！', '🎉')
    except Exception as e:
        if is_task_canceled(task_id):
            _finalize_generation_task(task_id, 'canceled', run_id=run_id,
                provider=task_provider, route=task_route, task_type=task_kind,
                stage='canceled', progress_text=f'{label}任务已取消')
            _record_generation_event(task_id, 'run_canceled', f'{label}任务已取消', stage='canceled')
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
        display = error_info.get('display_error') or raw_error_msg
        if isinstance(e, UpscaleRuntimeError) or engine is not None:
            display = raw_error_msg
            error_info['display_error'] = display
        _finalize_generation_task(
            task_id,
            'failed',
            run_id=run_id,
            provider=task_provider,
            route=task_route,
            task_type=task_kind,
            stage='failed',
            progress_text=display,
            error_info=error_info,
            error_type=error_type,
        )
        send_status_notification(task_id, f'❌ {label}失败：{display[:100]}', '⚠️')
        print(f"❌ 高清放大任务失败：{task_id} - {raw_error_msg}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception:
                pass
