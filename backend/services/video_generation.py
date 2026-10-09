"""H3 video public metadata, reference preparation and task lifecycle.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _sanitize_h3_prompt_metadata(value):
    source = value if isinstance(value, dict) else {}
    string_keys = {
        'skill_id', 'source_repository', 'source_commit', 'source_path',
        'compiler_version', 'schema_version', 'mode', 'provider', 'model',
        'reasoning_effort',
    }
    boolean_keys = {'reference_image_used', 'repair_applied', 'bilingual_output'}
    integer_keys = {'verified_files', 'minimum_shot_count'}
    clean = {}
    for key in string_keys:
        text = str(source.get(key) or '').strip()
        if text:
            clean[key] = text[:500]
    for key in boolean_keys:
        if key in source:
            clean[key] = bool(source.get(key))
    for key in integer_keys:
        try:
            number = int(source.get(key))
        except (TypeError, ValueError):
            continue
        if number >= 0:
            clean[key] = min(number, 1000)
    return clean


def _public_h3_acceleration(value, *, _H3_PUBLIC_ACCELERATION_KEYS):
    if not isinstance(value, dict):
        return {}
    public = {}
    for key in _H3_PUBLIC_ACCELERATION_KEYS:
        item = value.get(key)
        if item is None or isinstance(item, (dict, list, tuple, set, bytes, bytearray)):
            continue
        if isinstance(item, str):
            item = item[:200]
        public[key] = item
    return public


def _public_h3_runtime_output(runtime_job, *, _H3_PUBLIC_RUNTIME_OUTPUT_KEYS, _public_h3_acceleration):
    raw = runtime_job.get('output') if isinstance(runtime_job, dict) and isinstance(runtime_job.get('output'), dict) else {}
    public = {
        key: raw.get(key)
        for key in _H3_PUBLIC_RUNTIME_OUTPUT_KEYS
        if raw.get(key) is not None and not isinstance(raw.get(key), (dict, list, tuple, set, bytes, bytearray))
    }
    acceleration = _public_h3_acceleration(raw.get('acceleration'))
    if acceleration:
        public['acceleration'] = acceleration
    return public


def _public_h3_task_params(params, *, _H3_PUBLIC_TASK_PARAM_KEYS, _public_h3_acceleration, safe_basename):
    if not isinstance(params, dict):
        return {}
    public = {
        key: value
        for key, value in params.items()
        if key in _H3_PUBLIC_TASK_PARAM_KEYS
    }
    seed = public.get('seed')
    if isinstance(seed, int) and abs(seed) > 9_007_199_254_740_991:
        public['seed'] = str(seed)
    if 'acceleration' in public:
        public['acceleration'] = _public_h3_acceleration(public.get('acceleration'))
    if isinstance(public.get('sidecar_files'), dict):
        public['sidecar_files'] = {
            str(key)[:40]: safe_basename(value)
            for key, value in public['sidecar_files'].items()
            if value
        }
    return public


def _write_text_atomic(path, content, *, Path, os, uuid):
    path = Path(path)
    temporary_path = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        temporary_path.write_text(str(content or ''), encoding='utf-8')
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass


def _decode_h3_reference_image(data, *, H3_VIDEO_MAX_REFERENCE_BYTES, Image, _decode_data_uri_image, io):
    raw = str(data or '').strip()
    if not raw:
        raise ValueError('缺少首帧图片数据')
    if len(raw) > H3_VIDEO_MAX_REFERENCE_BYTES * 2:
        raise ValueError('首帧图片过大')
    image_bytes, mime_type, extension = _decode_data_uri_image(raw)
    if len(image_bytes) > H3_VIDEO_MAX_REFERENCE_BYTES:
        raise ValueError('首帧图片不能超过 64 MB')
    if not str(mime_type or '').lower().startswith('image/'):
        raise ValueError('首帧必须是图片文件')
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.verify()
    except Exception as exc:
        raise ValueError('首帧图片无法识别或文件已损坏') from exc
    return {
        'filename': f'first_frame{extension or ".png"}',
        'content': image_bytes,
        'content_type': mime_type or 'image/png',
    }


def _h3_phase_label(phase, fallback=''):
    labels = {
        'receiving': '正在接收任务',
        'queued': '已进入 GPU 队列',
        'starting': '正在启动 H3 推理',
        'loading_models': '正在加载 H3 模型',
        'conditioning': '正在编码提示词与参考图',
        'sampling': '正在进行音视频联合采样',
        'decoding_video': '正在解码视频',
        'decoding_audio': '正在解码音频',
        'muxing': '正在封装 MP4',
        'completed': 'H3 视频生成完成',
        'cancelled': '任务已取消',
        'failed': 'H3 推理失败',
    }
    return str(fallback or labels.get(str(phase or '').strip().lower()) or 'H3 视频生成中...')


def _archive_h3_reference_image(output_path, upload, *, Path, _ARCHIVE_IMAGE_EXTENSIONS, os, uuid):
    """Persist the verified H3 input image beside a new output when available."""
    if not isinstance(upload, dict):
        return None
    content = upload.get('content')
    if not isinstance(content, (bytes, bytearray)) or not content:
        return None
    suffix = Path(str(upload.get('filename') or '')).suffix.lower()
    if suffix not in _ARCHIVE_IMAGE_EXTENSIONS:
        content_type = str(upload.get('content_type') or '').lower()
        suffix = {
            'image/jpeg': '.jpg',
            'image/jpg': '.jpg',
            'image/webp': '.webp',
        }.get(content_type, '.png')
    reference_path = Path(output_path).with_name(f'{Path(output_path).stem}_reference{suffix}')
    temporary_path = reference_path.with_name(f'.{reference_path.name}.{uuid.uuid4().hex}.tmp')
    try:
        if reference_path.exists():
            if reference_path.is_symlink() or not reference_path.is_file():
                return None
            return reference_path
        temporary_path.write_bytes(bytes(content))
        os.replace(temporary_path, reference_path)
        if reference_path.stat().st_size != len(content):
            return None
    except OSError as exc:
        print(f'⚠️ H3 参考图归档失败（视频仍保留）：{exc}')
        return None
    finally:
        if temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass
    return reference_path


def _write_h3_video_sidecars(
    output_path,
    prompt,
    params,
    runtime_job,
    task_id='',
    reference_image_name='',
    *,
    H3_VIDEO_TASK_TYPE,
    Path,
    _public_h3_runtime_output,
    _sanitize_h3_prompt_metadata,
    _write_text_atomic,
    json,
    re,
):
    output_path = Path(output_path)
    runtime_output = _public_h3_runtime_output(runtime_job)
    details = {
        'task_type': H3_VIDEO_TASK_TYPE,
        'runtime_job_id': runtime_job.get('id'),
        'task_id': str(task_id or '').strip(),
        'mode': params.get('mode'),
        'aspect_ratio': params.get('aspect_ratio'),
        'pixel_budget_mp': params.get('pixel_budget_mp'),
        'actual_megapixels': params.get('actual_megapixels'),
        'width': params.get('width'),
        'height': params.get('height'),
        'size': f"{params.get('width')}x{params.get('height')}",
        'duration_seconds': params.get('duration_seconds'),
        'steps': params.get('steps'),
        'denoise': params.get('denoise'),
        'crf': params.get('crf'),
        'seed': (runtime_job.get('params') or {}).get('seed', params.get('seed')),
        'acceleration_mode': params.get('acceleration_mode'),
        'first_block_cache_threshold': params.get('first_block_cache_threshold'),
        'prompt_metadata': _sanitize_h3_prompt_metadata(params.get('prompt_metadata')),
        'runtime_output': runtime_output,
    }
    if reference_image_name:
        details['reference_image'] = str(reference_image_name)
    txt_path = output_path.with_suffix('.txt')
    txt_lines = [str(prompt or '').strip(), '', json.dumps(details, ensure_ascii=False, indent=2)]
    _write_text_atomic(txt_path, '\n'.join(txt_lines).rstrip() + '\n')

    prompt_text = str(prompt or '').strip()
    longest = max((len(match.group(0)) for match in re.finditer(r'`+', prompt_text)), default=0)
    fence = '`' * max(3, longest + 1)
    md_path = output_path.with_suffix('.md')
    _write_text_atomic(md_path, '\n'.join([
        '---',
        'source: tg-mini-app-img-gen',
        'type: video_prompt',
        f'generated_date: {json.dumps(output_path.parent.name, ensure_ascii=False)}',
        f'task_id: {json.dumps(str(task_id or output_path.stem), ensure_ascii=False)}',
        f'video: {json.dumps(output_path.name, ensure_ascii=False)}',
        f'txt_file: {json.dumps(txt_path.name, ensure_ascii=False)}',
        *( [f'reference_image: {json.dumps(str(reference_image_name), ensure_ascii=False)}'] if reference_image_name else [] ),
        '---',
        '',
        f'![[{output_path.name}]]',
        *( [f'![[{str(reference_image_name)}]]', ''] if reference_image_name else [] ),
        '',
        '## Prompt',
        '',
        f'{fence}text',
        prompt_text,
        fence,
        '',
        '## Parameters',
        '',
        '```json',
        json.dumps(details, ensure_ascii=False, indent=2),
        '```',
        '',
    ]))
    sidecars = {'txt': str(txt_path), 'markdown': str(md_path)}
    if reference_image_name:
        sidecars['reference_image'] = str(output_path.with_name(reference_image_name))
    return sidecars


def process_h3_video_task(
    task_id,
    prompt,
    upload,
    params,
    *,
    H3_VIDEO_DEFAULT_TASK_TIMEOUT_SECONDS,
    H3_VIDEO_TASK_TYPE,
    Path,
    _archive_h3_reference_image,
    _coerce_bool,
    _finalize_generation_task,
    _h3_phase_label,
    _is_task_canceled,
    _merge_task_params,
    _public_h3_runtime_output,
    _record_generation_event,
    _start_generation_audit,
    _translate_generation_failure,
    _write_h3_video_sidecars,
    cancel_video_runtime_job,
    daily_output_dir,
    datetime,
    download_video_runtime_result,
    get_video_runtime_job,
    random,
    re,
    send_tg_document,
    submit_video_runtime_job,
    time,
    update_task_status,
    urllib,
):
    """Background bridge from the main task system to H3_Runtime_Server."""
    run_id = ''
    target = None
    runtime_job_id = ''
    task_provider = 'minimax_h3'
    task_route = 'h3_runtime'
    params = dict(params or {})
    try:
        run_id = _start_generation_audit(
            task_id,
            H3_VIDEO_TASK_TYPE,
            prompt,
            params,
            provider=task_provider,
            route=task_route,
            stage='preparing',
        )
        update_task_status(task_id, 'preparing', '正在连接 H3 Runtime...', stage='runtime_connecting', progress=2)
        runtime_params = {
            'mode': params.get('mode', 'image_to_video'),
            'prompt': prompt,
            'width': params.get('width'),
            'height': params.get('height'),
            'duration_seconds': params.get('duration_seconds'),
            'steps': params.get('steps'),
            'denoise': params.get('denoise'),
            'crf': params.get('crf'),
            'seed': params.get('seed'),
            'acceleration_mode': params.get('acceleration_mode'),
            'first_block_cache_threshold': params.get('first_block_cache_threshold'),
        }
        runtime_uploads = {
            'first_frame' if params.get('mode') == 'image_to_video' else 'reference_images': upload,
        }
        _record_generation_event(task_id, 'provider_call_started', '开始提交 H3 Runtime 任务', stage='runtime_submitting', payload={
            'provider': task_provider,
            'route': task_route,
            'width': params.get('width'),
            'height': params.get('height'),
            'duration_seconds': params.get('duration_seconds'),
            'acceleration_mode': params.get('acceleration_mode'),
        })
        target, runtime_job = submit_video_runtime_job(runtime_params, runtime_uploads)
        runtime_job_id = str(runtime_job.get('id') or '')
        _merge_task_params(task_id, {
            'runtime_job_id': runtime_job_id,
            'runtime_mode': target.get('mode'),
            'runtime_base_url': target.get('base_url'),
            'runtime_version': target.get('version'),
        })
        update_task_status(task_id, 'processing', 'H3 任务已进入 GPU 队列', stage='queued', progress=5)

        timeout_seconds = max(300, min(24 * 60 * 60, int(params.get('task_timeout_seconds') or H3_VIDEO_DEFAULT_TASK_TIMEOUT_SECONDS)))
        deadline = time.monotonic() + timeout_seconds
        last_success_at = time.monotonic()
        last_phase = ''
        while time.monotonic() < deadline:
            if _is_task_canceled(task_id):
                try:
                    cancel_video_runtime_job(target, runtime_job_id)
                except Exception as exc:
                    print(f'⚠️ 取消 H3 Runtime 任务失败：{exc}')
                _finalize_generation_task(
                    task_id,
                    'canceled',
                    run_id=run_id,
                    provider=task_provider,
                    route=task_route,
                    task_type=H3_VIDEO_TASK_TYPE,
                    stage='canceled',
                    progress_text='H3 视频任务已取消',
                )
                return
            try:
                runtime_job = get_video_runtime_job(target, runtime_job_id)
                last_success_at = time.monotonic()
            except Exception as exc:
                if time.monotonic() - last_success_at > 120:
                    raise RuntimeError(f'H3 Runtime 状态连续 120 秒不可达：{exc}') from exc
                update_task_status(task_id, 'processing', 'H3 Runtime 暂时不可达，正在重试...', stage='runtime_reconnecting')
                time.sleep(3)
                continue

            runtime_status = str(runtime_job.get('status') or '').strip().lower()
            phase = str(runtime_job.get('phase') or runtime_status or 'processing').strip().lower()
            try:
                runtime_progress = max(0.0, min(1.0, float(runtime_job.get('progress') or 0)))
            except Exception:
                runtime_progress = 0.0
            progress = min(95, max(5, round(5 + runtime_progress * 90)))
            message = _h3_phase_label(phase, runtime_job.get('message'))
            update_task_status(task_id, 'processing', message, stage=phase, progress=progress)
            if phase != last_phase:
                _record_generation_event(task_id, 'runtime_phase', message, stage=phase, payload={
                    'runtime_job_id': runtime_job_id,
                    'progress': runtime_progress,
                })
                last_phase = phase

            if runtime_status == 'succeeded':
                break
            if runtime_status in {'cancelled', 'canceled'}:
                _finalize_generation_task(
                    task_id,
                    'canceled',
                    run_id=run_id,
                    provider=task_provider,
                    route=task_route,
                    task_type=H3_VIDEO_TASK_TYPE,
                    stage='canceled',
                    progress_text='H3 Runtime 已取消任务',
                )
                return
            if runtime_status == 'failed':
                raise RuntimeError(str(runtime_job.get('error') or runtime_job.get('message') or 'H3 Runtime 推理失败'))
            time.sleep(2)
        else:
            try:
                cancel_video_runtime_job(target, runtime_job_id)
            except Exception:
                pass
            raise TimeoutError(f'H3 视频任务超过 {timeout_seconds} 秒仍未完成')

        update_task_status(task_id, 'processing', '正在下载并归档 H3 视频...', stage='saving', progress=97)
        now = datetime.now()
        timestamp = now.strftime('%Y%m%d_%H%M%S')
        suffix = re.sub(r'[^A-Za-z0-9]+', '', runtime_job_id)[-8:] or f'{random.randint(1000, 9999)}'
        filename = f'h3_{timestamp}_{suffix}.mp4'
        output_dir = daily_output_dir(now)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename
        download_meta = download_video_runtime_result(target, runtime_job_id, output_path)
        reference_path = _archive_h3_reference_image(output_path, upload)
        sidecars = {}
        try:
            sidecars = _write_h3_video_sidecars(
                output_path,
                prompt,
                params,
                runtime_job,
                task_id=task_id,
                reference_image_name=reference_path.name if reference_path else '',
            )
        except Exception as exc:
            print(f'⚠️ H3 提示词侧车写入失败（MP4 已保留）：{exc}')
            _record_generation_event(
                task_id,
                'artifact_sidecar_warning',
                'H3 MP4 已归档，但提示词侧车写入失败',
                stage='saving',
                payload={'filename': filename, 'error_type': type(exc).__name__},
            )
        runtime_output = _public_h3_runtime_output(runtime_job)
        result_meta = {
            'runtime_job_id': runtime_job_id,
            'video_filename': filename,
            'video_url': f'/video/{urllib.parse.quote(filename)}',
            'video_size_bytes': int(download_meta.get('bytes') or output_path.stat().st_size),
            'width': int(runtime_output.get('width') or params.get('width') or 0),
            'height': int(runtime_output.get('height') or params.get('height') or 0),
            'fps': int(runtime_output.get('fps') or 24),
            'frame_count': int(runtime_output.get('frame_count') or 0),
            'duration_seconds': float(runtime_output.get('duration_seconds') or params.get('duration_seconds') or 0),
            'seed': runtime_output.get('seed', (runtime_job.get('params') or {}).get('seed', params.get('seed'))),
            'elapsed_seconds': runtime_output.get('elapsed_seconds'),
            'acceleration': runtime_output.get('acceleration') if isinstance(runtime_output.get('acceleration'), dict) else {},
            'archive_date': output_dir.name,
            'sidecar_files': {
                key: Path(value).name
                for key, value in sidecars.items()
                if key in {'txt', 'markdown'} and value
            },
        }
        if reference_path:
            result_meta['reference_image_filename'] = reference_path.name
        _merge_task_params(task_id, result_meta)
        _record_generation_event(task_id, 'artifact_saved', 'H3 MP4 已归档', stage='saving', payload={
            'filename': filename,
            'bytes': result_meta['video_size_bytes'],
        })

        telegram_enabled = _coerce_bool(params.get('telegram_enabled', params.get('telegramEnabled')), False)
        telegram_success = False
        if telegram_enabled:
            update_task_status(task_id, 'processing', '正在发送 H3 视频到 Telegram...', stage='sending_telegram', progress=99)
            caption = f"MiniMax H3 | {result_meta['width']}×{result_meta['height']} | {result_meta['duration_seconds']:.2f}s"
            if prompt:
                caption += f"\n{str(prompt)[:700]}"
            try:
                send_tg_document(output_path, caption=caption[:1000])
                telegram_success = True
            except Exception as exc:
                print(f'❌ H3 视频 Telegram 发送失败：{exc}')

        if telegram_enabled and not telegram_success:
            final_status = 'succeeded_no_telegram'
            progress_text = 'H3 视频生成并归档完成，但 Telegram 发送失败'
        elif telegram_enabled:
            final_status = 'succeeded'
            progress_text = 'H3 视频生成、归档并发送完成'
        else:
            final_status = 'succeeded_no_telegram'
            progress_text = 'H3 视频生成并归档完成'

        _finalize_generation_task(
            task_id,
            final_status,
            run_id=run_id,
            provider=task_provider,
            route=task_route,
            task_type=H3_VIDEO_TASK_TYPE,
            result_file=filename,
            result_files=[filename],
            image_count=0,
            stage='done',
            progress_text=progress_text,
            extra={'runtime_job_id': runtime_job_id, **result_meta},
        )
        _record_generation_event(task_id, 'run_succeeded', progress_text, stage='done', payload=result_meta)
    except Exception as exc:
        raw_error = str(exc)
        error_type = type(exc).__name__
        error_info = _translate_generation_failure(
            task_id,
            raw_error,
            provider=task_provider,
            route=task_route,
            task_type=H3_VIDEO_TASK_TYPE,
            stage='failed',
            exception_name=error_type,
        )
        # Runtime messages are generally already suitable for direct display.
        error_info['display_error'] = raw_error[:500] or 'H3 视频生成失败'
        _finalize_generation_task(
            task_id,
            'failed',
            run_id=run_id,
            provider=task_provider,
            route=task_route,
            task_type=H3_VIDEO_TASK_TYPE,
            stage='failed',
            progress_text=error_info['display_error'],
            error_info=error_info,
            error_type=error_type,
        )
        print(f'❌ H3 视频任务失败：{task_id} - {raw_error}')
