"""Generation progress, wait and download callback adapters.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _make_gpt_image_progress_callback(
    task_id,
    requested_count,
    *,
    _is_task_canceled,
    _result_image_filenames,
    json,
    update_task_status,
):
    try:
        total = max(1, int(requested_count or 1))
    except (TypeError, ValueError):
        total = 1

    def on_image_saved(partial_result, saved_count, total_count):
        if _is_task_canceled(task_id):
            return
        result_files = _result_image_filenames(partial_result)
        if not result_files:
            return
        expected_total = max(1, int(total_count or total))
        visible_count = len(result_files)
        progress_text = f'GPT 图片生成中（已完成 {visible_count}/{expected_total} 张）'
        update_task_status(
            task_id,
            'processing',
            progress_text,
            stage='generating_images',
            result_file=result_files[0],
            result_files=json.dumps(result_files, ensure_ascii=False),
        )

    return on_image_saved


def _make_gpt_provider_wait_callback(task_id, *, time, update_task_fields):
    def on_wait(label, elapsed_seconds, remaining_seconds):
        update_task_fields(
            task_id,
            stage='calling_gpt',
            progress_text=f'正在等待本地 GPT provider 返回（已等待 {elapsed_seconds}s）...',
            heartbeat_at=int(time.time()),
        )

    return on_wait


def _make_gpt_pool_wait_callback(task_id, *, time, update_task_fields):
    def on_wait(label, elapsed_seconds, remaining_seconds):
        update_task_fields(
            task_id,
            stage='fallback_running',
            progress_text=f'正在等待 ChatGPT 账号池返回（已等待 {elapsed_seconds}s）...',
            heartbeat_at=int(time.time()),
        )

    return on_wait


def _format_download_bytes(value):
    try:
        size = max(0, int(value or 0))
    except (TypeError, ValueError):
        size = 0
    if size >= 1024 * 1024:
        return f'{size / 1024 / 1024:.1f} MB'
    if size >= 1024:
        return f'{size / 1024:.0f} KB'
    return f'{size} B'


def _third_party_download_progress_percent(event):
    try:
        count = max(1, int(event.get('item_count') or 1))
    except (TypeError, ValueError):
        count = 1
    try:
        index = max(1, min(count, int(event.get('item_index') or 1)))
    except (TypeError, ValueError):
        index = 1
    try:
        bytes_received = max(0, int(event.get('bytes_received') or 0))
    except (TypeError, ValueError):
        bytes_received = 0
    try:
        total_bytes = max(0, int(event.get('total_bytes') or 0))
    except (TypeError, ValueError):
        total_bytes = 0

    name = str(event.get('event') or '')
    if name.startswith('response_'):
        if name == 'response_complete':
            response_ratio = 1.0
        elif total_bytes > 0:
            response_ratio = max(0.0, min(0.98, bytes_received / total_bytes))
        elif bytes_received > 0:
            response_ratio = max(0.0, min(0.9, bytes_received / (16 * 1024 * 1024)))
        else:
            return 54 if name == 'response_headers' else (55 if name == 'response_first_byte' else 52)
        return max(52, min(69, round(55 + response_ratio * 14)))
    if name == 'download_complete':
        item_ratio = 1.0
    elif total_bytes > 0:
        item_ratio = max(0.0, min(0.98, bytes_received / total_bytes))
    elif bytes_received > 0:
        item_ratio = max(0.0, min(0.85, bytes_received / (12 * 1024 * 1024)))
    else:
        item_ratio = 0.0
    overall_ratio = ((index - 1) + item_ratio) / count
    return max(70, min(95, round(70 + overall_ratio * 25)))


def _make_third_party_download_progress_callback(
    task_id,
    *,
    _format_download_bytes,
    _is_task_canceled,
    _merge_task_params,
    _record_generation_event,
    _third_party_download_progress_percent,
    time,
    update_task_status,
):
    recorded_events = set()
    recorded_request_ids = set()

    def on_progress(event):
        if _is_task_canceled(task_id):
            return
        if not isinstance(event, dict):
            return
        name = str(event.get('event') or '').strip()
        if not name:
            return
        try:
            index = max(1, int(event.get('item_index') or 1))
        except (TypeError, ValueError):
            index = 1
        try:
            count = max(1, int(event.get('item_count') or 1))
        except (TypeError, ValueError):
            count = 1
        try:
            bytes_received = max(0, int(event.get('bytes_received') or 0))
        except (TypeError, ValueError):
            bytes_received = 0
        try:
            total_bytes = max(0, int(event.get('total_bytes') or 0))
        except (TypeError, ValueError):
            total_bytes = 0
        progress = _third_party_download_progress_percent(event)
        size_text = _format_download_bytes(bytes_received)
        total_text = _format_download_bytes(total_bytes) if total_bytes else ''
        image_suffix = f' {index}/{count}' if count > 1 else ''
        is_response_event = name.startswith('response_')
        stage = 'receiving_third_party_response' if is_response_event else 'downloading_third_party_image'
        extra = {
            'progress': progress,
            'bytes_received': bytes_received,
        }
        severity = 'info'
        event_type = ''

        request_id = str(event.get('request_id') or '').strip()
        if request_id and request_id not in recorded_request_ids:
            recorded_request_ids.add(request_id)
            _merge_task_params(task_id, {'third_party_request_id': request_id})

        if name == 'response_start':
            message = '正在连接并发送第三方请求，等待生成结果...'
            event_type = 'third_party_response_started'
        elif name == 'response_headers':
            message = '第三方 API 已建立响应，正在等待结果数据...'
            event_type = 'third_party_response_headers'
        elif name == 'response_first_byte':
            message = '第三方 API 已返回首字节，正在接收结果...'
            extra['first_byte_at'] = int(time.time())
            if event.get('ttfb_ms') is not None:
                extra['ttfb_ms'] = max(0, int(event.get('ttfb_ms') or 0))
            event_type = 'third_party_response_first_byte'
        elif name == 'response_progress':
            if total_text:
                message = f'正在接收第三方 API 结果：{size_text}/{total_text}'
            else:
                message = f'正在接收第三方 API 结果：已接收 {size_text}'
        elif name == 'response_complete':
            message = '第三方 API 结果已完整接收，正在解析并保存...'
            event_type = 'third_party_response_completed'
        elif name == 'download_start':
            message = f'正在下载第三方图片{image_suffix}...'
            event_type = 'third_party_download_started'
        elif name == 'download_first_byte':
            message = f'第三方图片{image_suffix}已开始返回，正在下载...'
            extra['first_byte_at'] = int(time.time())
        elif name == 'download_progress':
            if total_text:
                message = f'正在下载第三方图片{image_suffix}：{size_text}/{total_text}'
            else:
                message = f'正在下载第三方图片{image_suffix}：已接收 {size_text}'
        elif name == 'download_retry':
            next_attempt = event.get('next_attempt') or event.get('attempt') or 1
            max_attempts = event.get('max_attempts') or 1
            message = f'第三方图片下载中断，正在重试 {next_attempt}/{max_attempts}...'
            extra['transport_error_type'] = str(event.get('error_type') or 'download_retry')
            severity = 'warning'
            event_type = 'third_party_download_retry'
        elif name == 'download_complete':
            message = f'第三方图片{image_suffix}下载完成，正在保存...'
            event_type = 'third_party_download_completed'
        else:
            return

        update_task_status(task_id, 'processing', message, stage=stage, **extra)
        if event_type:
            event_key = (event_type, index, event.get('attempt'), event.get('next_attempt'))
            if event_key not in recorded_events:
                recorded_events.add(event_key)
                payload = {
                    key: event.get(key)
                    for key in (
                        'attempt',
                        'next_attempt',
                        'max_attempts',
                        'item_index',
                        'item_count',
                        'bytes_received',
                        'total_bytes',
                        'error_type',
                        'request_id',
                        'content_type',
                        'deadline_seconds',
                        'headers_elapsed_ms',
                        'ttfb_ms',
                        'completed_before_eof',
                    )
                    if event.get(key) is not None
                }
                _record_generation_event(task_id, event_type, message, stage=stage, severity=severity, payload=payload)

    return on_progress
