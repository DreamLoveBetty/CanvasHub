"""ComfyUI archive, uncompressed delivery and task lifecycle.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _comfy_archive_date(params, *, datetime):
    manifest = params.get('comfy_archive_manifest') if isinstance(params.get('comfy_archive_manifest'), dict) else {}
    for value in (params.get('comfy_archive_date'), manifest.get('archive_date')):
        text = str(value or '').strip()
        try:
            parsed = datetime.strptime(text, '%Y-%m-%d')
        except (TypeError, ValueError):
            continue
        if parsed.strftime('%Y-%m-%d') == text:
            return text
    return datetime.now().strftime('%Y-%m-%d')


def _comfy_archive_source_key(task_id, item, *, hashlib, json):
    payload = [
        str(task_id or ''),
        str(item.get('filename') or '').strip(),
        str(item.get('subfolder') or '').strip(),
        str(item.get('type') or 'output').strip() or 'output',
    ]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _comfy_archive_filename(task_id, item, source_key, *, Path, hashlib, re):
    filename = str(item.get('filename') or '').strip()
    suffix = Path(filename).suffix or '.png'
    if suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
        suffix = '.png'
    else:
        suffix = suffix.lower()
    source_stem = re.sub(r'[^A-Za-z0-9_-]+', '_', Path(filename).stem).strip('_')[:48] or 'output'
    task_key = hashlib.sha256(str(task_id or '').encode('utf-8')).hexdigest()[:16]
    return f'comfy_{task_key}_{source_stem}_{source_key[:16]}{suffix}'


def _comfy_archive_file_ready(path):
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _build_comfy_archive_manifest(
    task_id,
    params,
    comfy_images,
    archive_date,
    *,
    _COMFY_ARCHIVE_MANIFEST_VERSION,
    _COMFY_TELEGRAM_STATES,
    _comfy_archive_filename,
    _comfy_archive_source_key,
):
    previous = params.get('comfy_archive_manifest') if isinstance(params.get('comfy_archive_manifest'), dict) else {}
    previous_items = previous.get('items') if isinstance(previous.get('items'), list) else []
    previous_by_key = {
        str(item.get('source_key')): item
        for item in previous_items
        if isinstance(item, dict) and item.get('source_key')
    }
    legacy_all_sent = bool(params.get('comfy_telegram_sent'))
    items = []
    for image in comfy_images:
        source_key = _comfy_archive_source_key(task_id, image)
        old_item = previous_by_key.get(source_key) or {}
        telegram_state = str(old_item.get('telegram_state') or '').strip().lower()
        if telegram_state not in _COMFY_TELEGRAM_STATES:
            telegram_state = 'sent' if old_item.get('telegram_sent') or legacy_all_sent else 'pending'
        item = {
            'source_key': source_key,
            'filename': str(image.get('filename') or '').strip(),
            'subfolder': str(image.get('subfolder') or '').strip(),
            'type': str(image.get('type') or 'output').strip() or 'output',
            'archive_file': _comfy_archive_filename(task_id, image, source_key),
            'archived': bool(old_item.get('archived')),
            'telegram_state': telegram_state,
            'telegram_sent': telegram_state == 'sent',
        }
        for key in ('archived_at', 'telegram_attempted_at', 'telegram_sent_at'):
            if old_item.get(key) is not None:
                item[key] = old_item.get(key)
        items.append(item)
    return {
        'version': _COMFY_ARCHIVE_MANIFEST_VERSION,
        'archive_date': archive_date,
        'items': items,
    }


def _atomic_write_comfy_text(path, text, *, os, tempfile):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(text)
        os.replace(temp_name, path)
    finally:
        try:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        except Exception:
            pass


def _send_comfy_result(
    task_id,
    prompt,
    workflow,
    ratio,
    comfy_image,
    params,
    *,
    Path,
    _atomic_write_comfy_text,
    _build_comfy_archive_manifest,
    _coerce_bool,
    _comfy_archive_date,
    _comfy_archive_file_ready,
    _fetch_comfy_binary,
    _is_task_canceled,
    _normalize_comfy_dimension,
    _save_task_params,
    daily_output_dir,
    datetime,
    json,
    os,
    save_thumbnail,
    send_status_notification,
    send_telegram,
    tempfile,
    time,
    update_task,
    update_task_status,
    write_obsidian_prompt_sidecar,
):
    if _is_task_canceled(task_id):
        return
    params = dict(params or {})
    width = _normalize_comfy_dimension(params.get('width'), 1024)
    height = _normalize_comfy_dimension(params.get('height'), 1024)
    size_label = f'{width}×{height}'
    comfy_images = params.get('comfy_images') if isinstance(params.get('comfy_images'), list) else []
    if not comfy_images and isinstance(comfy_image, dict):
        comfy_images = [comfy_image]
    try:
        expected_count = max(1, min(8, int(params.get('comfy_expected_output_count') or len(comfy_images) or 1)))
    except (TypeError, ValueError):
        expected_count = 1
    comfy_images = [
        item for item in comfy_images
        if isinstance(item, dict) and str(item.get('filename') or '').strip()
    ][:expected_count]
    if not comfy_images:
        raise RuntimeError('ComfyUI 输出缺少图片')

    archive_date = _comfy_archive_date(params)
    output_dir = daily_output_dir(datetime.strptime(archive_date, '%Y-%m-%d'))
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = _build_comfy_archive_manifest(task_id, params, comfy_images, archive_date)
    manifest_items = manifest['items']
    params['comfy_image'] = comfy_images[0]
    params['comfy_images'] = comfy_images
    params['archive_enabled'] = True
    params['archive_dir'] = str(output_dir)
    params['comfy_archive_date'] = archive_date
    params['comfy_archive_manifest'] = manifest

    def persist_manifest():
        archived_names = []
        for manifest_item in manifest_items:
            archive_path = output_dir / manifest_item['archive_file']
            if manifest_item.get('archived') and _comfy_archive_file_ready(archive_path):
                archived_names.append(manifest_item['archive_file'])
        params['archive_files'] = archived_names
        if archived_names:
            params['archive_file'] = archived_names[0]
        else:
            params.pop('archive_file', None)
        params['comfy_archive_manifest'] = manifest
        _save_task_params(task_id, params)

    # Fix the archive date and deterministic names before touching final storage.
    persist_manifest()

    staged_files = {}
    with tempfile.TemporaryDirectory(prefix='.comfy-stage-', dir=str(output_dir)) as stage_dir_name:
        stage_dir = Path(stage_dir_name)
        for item in manifest_items:
            if _is_task_canceled(task_id):
                return
            archive_path = output_dir / item['archive_file']
            if _comfy_archive_file_ready(archive_path):
                continue
            image_bytes, _ = _fetch_comfy_binary(item['filename'], item['subfolder'], item['type'])
            if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
                raise RuntimeError(f"ComfyUI 输出图片为空：{item['filename']}")
            stage_path = stage_dir / f"{item['archive_file']}.tmp"
            stage_path.write_bytes(image_bytes)
            staged_files[item['source_key']] = stage_path

        # All remote downloads succeeded. Only now expose files in the archive.
        if _is_task_canceled(task_id):
            return
        for item in manifest_items:
            stage_path = staged_files.get(item['source_key'])
            if stage_path is not None:
                os.replace(stage_path, output_dir / item['archive_file'])

    archive_paths = []
    archive_names = []
    total = len(comfy_images)
    workflow_parameters = params.get('workflow_parameters') if isinstance(params.get('workflow_parameters'), dict) else {}
    for index, item in enumerate(manifest_items, start=1):
        if _is_task_canceled(task_id):
            return
        archive_name = item['archive_file']
        archive_path = output_dir / archive_name
        if not _comfy_archive_file_ready(archive_path):
            raise RuntimeError(f"ComfyUI 归档文件写入失败：{archive_name}")
        archive_paths.append(archive_path)
        archive_names.append(archive_name)

        sidecar = archive_path.with_suffix('.txt')
        sidecar_lines = [
            str(prompt or '').strip(),
            '',
            f'workflow: {workflow}',
            f'ratio: {ratio}',
            f'size: {width}x{height}',
            'provider: comfy',
            f'candidate: {index}/{total}',
        ]
        if workflow_parameters:
            sidecar_lines.append('parameters:')
            sidecar_lines.extend(f'- {key}: {value}' for key, value in workflow_parameters.items())
        sidecar_text = '\n'.join(sidecar_lines).strip()
        _atomic_write_comfy_text(sidecar, sidecar_text + '\n')
        try:
            write_obsidian_prompt_sidecar(archive_path, sidecar_text, txt_path=sidecar)
        except Exception as exc:
            print(f"⚠️ 写入 ComfyUI sidecar 失败: {exc}")
        try:
            save_thumbnail(str(archive_path), archive_name)
        except Exception as exc:
            print(f"⚠️ 保存 ComfyUI 缩略图失败: {exc}")
        item['archived'] = True
        item.setdefault('archived_at', int(time.time()))
        persist_manifest()

    if not archive_paths:
        raise RuntimeError('ComfyUI 输出没有可归档的图片')

    telegram_enabled = _coerce_bool(params.get('telegram_enabled', params.get('telegramEnabled')), True)
    has_pending_telegram = telegram_enabled and any(
        item.get('telegram_state') == 'pending'
        for item in manifest_items
    )
    if _is_task_canceled(task_id):
        return
    if has_pending_telegram:
        update_task_status(task_id, 'processing', 'ComfyUI 已归档，正在发送到 Telegram...', stage='sending_telegram')
        send_status_notification(task_id, 'ComfyUI 已完成，正在发送图片...', '📤')
    for index, (item, archive_path) in enumerate(zip(manifest_items, archive_paths), start=1):
        caption_parts = [part for part in (f'ComfyUI {workflow}'.strip(), size_label, f'{index}/{len(archive_paths)}' if len(archive_paths) > 1 else '') if part]
        caption = ' | '.join(caption_parts)
        if prompt:
            caption = f"{caption}\n{prompt}" if caption else prompt
        caption = caption[:500] + '...' if len(caption) > 500 else caption
        if not telegram_enabled or item.get('telegram_state') != 'pending':
            continue
        if _is_task_canceled(task_id):
            return
        item['telegram_state'] = 'sending'
        item['telegram_sent'] = False
        item['telegram_attempted_at'] = int(time.time())
        persist_manifest()
        sent = bool(send_telegram(None, str(archive_path), caption))
        item['telegram_state'] = 'sent' if sent else 'failed'
        item['telegram_sent'] = sent
        if sent:
            item['telegram_sent_at'] = int(time.time())
        persist_manifest()

    if _is_task_canceled(task_id):
        return
    telegram_success = telegram_enabled and all(
        item.get('telegram_state') == 'sent'
        for item in manifest_items
    )
    params['archive_file'] = archive_names[0]
    params['archive_files'] = archive_names
    params['telegram_enabled'] = telegram_enabled
    params['comfy_telegram_sent'] = telegram_success
    params['comfy_telegram_sent_at'] = int(time.time()) if telegram_success else None

    if telegram_enabled and telegram_success:
        final_status = 'succeeded'
        progress_text = 'ComfyUI 生成成功'
    elif telegram_enabled:
        final_status = 'succeeded_no_telegram'
        progress_text = 'ComfyUI 已生成，但 Telegram 发送未全部成功'
    else:
        final_status = 'succeeded_no_telegram'
        progress_text = 'ComfyUI 已生成并归档，已按节点开关跳过 Telegram'
    update_task(
        task_id,
        final_status,
        result_file=archive_names[0],
        result_files=json.dumps(archive_names, ensure_ascii=False),
        stage='done',
        progress_text=progress_text,
        params=json.dumps(params, ensure_ascii=False),
    )
    if telegram_enabled and telegram_success:
        send_status_notification(task_id, '✅ ComfyUI 图片生成成功！', '🎉')
    elif telegram_enabled:
        send_status_notification(task_id, '❌ ComfyUI 已生成，但 Telegram 发送未全部成功', '⚠️')


def process_comfy_task(
    task_id,
    prompt,
    workflow,
    ratio,
    client_id=None,
    *,
    _fetch_comfy_history_entry,
    _is_task_canceled,
    _send_comfy_result,
    _sync_comfy_task,
    _wait_for_comfy_websocket,
    get_comfy_config,
    send_status_notification,
    time,
    update_task,
    update_task_status,
):
    config = get_comfy_config()
    if _is_task_canceled(task_id):
        return
    deadline = time.time() + config['task_timeout_seconds']
    update_task_status(task_id, 'processing', 'ComfyUI 任务已提交，等待执行...', stage='queued', progress=2)
    send_status_notification(task_id, f'已提交 ComfyUI 任务：{workflow}', '✅')
    last_notified_text = None
    websocket_progress = 2.0

    def notify_once(progress_text, icon='⏳'):
        nonlocal last_notified_text
        if progress_text and progress_text != last_notified_text:
            send_status_notification(task_id, progress_text, icon)
            last_notified_text = progress_text

    def reconcile_history():
        """Merge the authoritative history record into the local task."""
        _, entry = _fetch_comfy_history_entry(task_id)
        if not isinstance(entry, dict):
            return None
        sync_state = _sync_comfy_task(task_id, entry) or {}
        progress_text = sync_state.get('progress_text')
        if progress_text:
            status_text = str(entry.get('status', {}).get('status_str', '')).lower()
            notify_once(progress_text, '⏳' if status_text in ('', 'success', 'succeeded') else '🤖')
        if not sync_state.get('completed'):
            return False
        comfy_image = sync_state.get('image')
        if comfy_image:
            if _is_task_canceled(task_id):
                return True
            params = sync_state.get('params') or {}
            if not params.get('comfy_telegram_sent'):
                _send_comfy_result(task_id, prompt, workflow, ratio, comfy_image, params)
        return True

    def on_websocket_event(event):
        """Project remote node events onto the existing unified task fields."""
        nonlocal websocket_progress
        if _is_task_canceled(task_id):
            return
        event_type = str((event or {}).get('type') or '')
        data = (event or {}).get('data') if isinstance((event or {}).get('data'), dict) else {}
        progress_text = ''
        stage = 'processing'
        next_progress = websocket_progress
        if event_type == 'transport_connected':
            progress_text = 'ComfyUI 实时通道已连接，等待执行...'
            stage = 'queued'
            next_progress = max(next_progress, 3)
        elif event_type == 'execution_start':
            progress_text = 'ComfyUI 已开始执行...'
            next_progress = max(next_progress, 5)
        elif event_type == 'execution_cached':
            progress_text = 'ComfyUI 命中缓存，正在整理结果...'
            next_progress = max(next_progress, 70)
        elif event_type == 'executing' and data.get('node') is not None:
            progress_text = f"ComfyUI 正在执行节点 {data.get('node')}..."
            next_progress = max(next_progress, 8)
        elif event_type == 'executed':
            progress_text = 'ComfyUI 节点执行完成，继续处理中...'
            next_progress = max(next_progress, 15)
        elif event_type == 'progress':
            try:
                value = max(0.0, float(data.get('value') or 0))
                maximum = max(1.0, float(data.get('max') or 1))
                ratio_value = min(1.0, value / maximum)
                next_progress = max(next_progress, 10 + ratio_value * 78)
                progress_text = f'ComfyUI 节点进度 {int(value)}/{int(maximum)}...'
            except (TypeError, ValueError):
                progress_text = 'ComfyUI 生成中...'
        elif event_type == 'status':
            status = data.get('status') if isinstance(data.get('status'), dict) else {}
            exec_info = status.get('exec_info') if isinstance(status.get('exec_info'), dict) else {}
            queue_remaining = exec_info.get('queue_remaining')
            if queue_remaining is not None:
                progress_text = f'ComfyUI 队列等待（剩余 {queue_remaining}）...'
                stage = 'queued'
        if not progress_text:
            return
        websocket_progress = min(90.0, next_progress)
        update_task_status(
            task_id,
            'processing',
            progress_text,
            stage=stage,
            progress=round(websocket_progress, 2),
        )

    # A history snapshot closes the small race between POST /prompt and opening
    # the WebSocket. It also handles an instant cache hit without a socket.
    try:
        if reconcile_history():
            return
    except Exception:
        pass

    if client_id and time.time() < deadline:
        websocket_state = _wait_for_comfy_websocket(
            task_id,
            client_id,
            base_url=config['base_url'],
            deadline=deadline,
            is_cancelled=lambda: _is_task_canceled(task_id),
            on_event=on_websocket_event,
            completion_probe=lambda: reconcile_history() is True,
            probe_interval=15.0,
            receive_timeout=max(0.25, min(1.0, config['poll_interval_seconds'])),
        ) or {}
        state = str(websocket_state.get('state') or '')
        if state == 'canceled' or _is_task_canceled(task_id):
            return
        if state == 'reconciled':
            return
        if state == 'failed':
            # History remains authoritative when ComfyUI has already persisted
            # the failure, but the event message prevents an indefinite wait on
            # servers that do not retain failed history entries.
            try:
                if reconcile_history():
                    return
            except Exception:
                pass
            error_text = str(websocket_state.get('message') or 'ComfyUI 执行失败')[:1000]
            update_task(
                task_id,
                'failed',
                error=error_text,
                stage='failed',
                progress_text=error_text,
                progress=100,
                transport_error_type='ComfyExecutionError',
            )
            notify_once(f'❌ {error_text}', '⚠️')
            return
        if state == 'timeout':
            update_task(
                task_id,
                'failed',
                error='ComfyUI 任务超时',
                stage='failed',
                progress_text='ComfyUI 任务超时',
                progress=100,
                transport_error_type='ComfyTimeout',
            )
            notify_once('❌ ComfyUI 任务超时', '⚠️')
            return
        if state == 'completed':
            update_task_status(
                task_id,
                'processing',
                'ComfyUI 执行完成，正在读取结果...',
                stage='waiting_history',
                progress=92,
            )
        elif state in ('unavailable', 'disconnected'):
            fallback_text = 'ComfyUI 实时通道不可用，已切换兼容轮询...'
            update_task_status(
                task_id,
                'processing',
                fallback_text,
                stage='waiting_history',
                progress=max(3, websocket_progress),
                transport_error_type='ComfyWebSocketFallback',
            )
            notify_once(fallback_text, '⚠️')

    while time.time() < deadline:
        if _is_task_canceled(task_id):
            return
        try:
            history_state = reconcile_history()
            if history_state:
                return
            if history_state is None:
                progress_text = 'ComfyUI 排队中...'
                update_task_status(
                    task_id,
                    'processing',
                    progress_text,
                    stage='waiting_history',
                    progress=max(3, websocket_progress),
                )
                notify_once(progress_text, '⏳')
        except Exception as e:
            msg = f'等待 ComfyUI 状态失败：{str(e)[:120]}'
            update_task_status(
                task_id,
                'processing',
                msg,
                stage='waiting_history',
                progress=max(3, websocket_progress),
            )
            notify_once(msg, '⚠️')

        time.sleep(config['poll_interval_seconds'])

    if _is_task_canceled(task_id):
        return
    update_task(
        task_id,
        'failed',
        error='ComfyUI 任务超时',
        stage='failed',
        progress_text='ComfyUI 任务超时',
        progress=100,
        transport_error_type='ComfyTimeout',
    )
    send_status_notification(task_id, '❌ ComfyUI 任务超时', '⚠️')
