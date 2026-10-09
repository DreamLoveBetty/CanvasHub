"""ComfyUI WebSocket event transport.

This module owns only the remote event channel. HTTP submission, history
reconciliation, result download and local task state stay in their existing
modules.  Callers can therefore fall back to history polling without changing
the browser-facing task contract.
"""
from __future__ import annotations

import json
import time
import urllib.parse


_COMPLETION_EVENTS = frozenset(('execution_success', 'execution_complete'))
_FAILURE_EVENTS = frozenset(('execution_error', 'execution_interrupted'))


def build_comfy_websocket_url(base_url, client_id):
    """Return the ComfyUI ``/ws`` URL for a unique task client id."""
    parsed = urllib.parse.urlsplit(str(base_url or '').strip().rstrip('/'))
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('ComfyUI Base URL 必须是完整的 http:// 或 https:// 地址')
    scheme = 'wss' if parsed.scheme == 'https' else 'ws'
    path = f"{parsed.path.rstrip('/')}/ws"
    query = urllib.parse.urlencode({'clientId': str(client_id or '').strip()})
    return urllib.parse.urlunsplit((scheme, parsed.netloc, path, query, ''))


def parse_comfy_websocket_message(raw_message):
    """Decode a JSON ComfyUI event; binary preview frames are ignored."""
    if isinstance(raw_message, (bytes, bytearray, memoryview)):
        return None
    if not isinstance(raw_message, str) or not raw_message.strip():
        return None
    try:
        payload = json.loads(raw_message)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    event_type = str(payload.get('type') or '').strip()
    data = payload.get('data') if isinstance(payload.get('data'), dict) else {}
    if not event_type:
        return None
    return {'type': event_type, 'data': data}


def _comfy_event_error_message(event):
    data = event.get('data') if isinstance(event, dict) else {}
    for key in ('exception_message', 'error', 'message', 'exception_type'):
        value = data.get(key) if isinstance(data, dict) else None
        if isinstance(value, str) and value.strip():
            message = value.strip()
            node_id = str(data.get('node_id') or '').strip()
            return f'{message}（节点 {node_id}）' if node_id else message
    event_type = str(event.get('type') or '') if isinstance(event, dict) else ''
    if event_type == 'execution_interrupted':
        return 'ComfyUI 执行已中断'
    return 'ComfyUI 执行失败'


def wait_for_comfy_websocket(
    prompt_id,
    client_id,
    *,
    base_url,
    deadline,
    is_cancelled,
    on_event=None,
    completion_probe=None,
    probe_interval=15.0,
    connect_timeout=10,
    receive_timeout=1.0,
    websocket_module=None,
    now=None,
):
    """Wait for one prompt's terminal ComfyUI WebSocket event.

    The return value always contains a ``state`` key. ``unavailable`` and
    ``disconnected`` are recoverable states: the caller should reconcile with
    ``/history/{prompt_id}`` and continue with polling.
    """
    now = now or time.time
    prompt_id = str(prompt_id or '').strip()
    client_id = str(client_id or '').strip()
    if not prompt_id or not client_id:
        return {'state': 'unavailable', 'message': '缺少 ComfyUI WebSocket 任务标识'}

    if websocket_module is None:
        try:
            import websocket as websocket_module  # type: ignore
        except Exception as exc:
            return {'state': 'unavailable', 'message': f'WebSocket 组件不可用：{exc}'}

    url = build_comfy_websocket_url(base_url, client_id)
    remaining = max(0.0, float(deadline) - float(now()))
    if remaining <= 0:
        return {'state': 'timeout', 'message': 'ComfyUI 任务超时'}

    socket = None
    try:
        socket = websocket_module.create_connection(
            url,
            timeout=max(0.25, min(float(connect_timeout), remaining)),
            http_proxy_host=None,
            http_proxy_port=None,
        )
        socket.settimeout(max(0.1, float(receive_timeout)))
        if on_event:
            on_event({'type': 'transport_connected', 'data': {'url': url}})

        def probe_history():
            if not completion_probe:
                return False
            try:
                return bool(completion_probe())
            except Exception:
                return False

        # The prompt may finish between POST /prompt and the socket handshake.
        # One immediate history probe closes that race; the sparse watchdog also
        # protects older/custom servers that omit a terminal WebSocket event.
        if probe_history():
            return {'state': 'reconciled', 'message': 'ComfyUI 历史结果已完成'}
        next_probe_at = float(now()) + max(1.0, float(probe_interval))

        timeout_error = getattr(websocket_module, 'WebSocketTimeoutException', TimeoutError)
        closed_error = getattr(websocket_module, 'WebSocketConnectionClosedException', ConnectionError)
        while float(now()) < float(deadline):
            if is_cancelled():
                return {'state': 'canceled', 'message': '任务已取消'}
            if float(now()) >= next_probe_at:
                if probe_history():
                    return {'state': 'reconciled', 'message': 'ComfyUI 历史结果已完成'}
                next_probe_at = float(now()) + max(1.0, float(probe_interval))
            try:
                raw_message = socket.recv()
            except timeout_error:
                continue
            except closed_error as exc:
                return {'state': 'disconnected', 'message': f'WebSocket 连接已断开：{exc}'}
            except Exception as exc:
                return {'state': 'disconnected', 'message': f'WebSocket 接收失败：{exc}'}

            if raw_message in (None, ''):
                return {'state': 'disconnected', 'message': 'WebSocket 连接已关闭'}
            event = parse_comfy_websocket_message(raw_message)
            if event is None:
                continue
            data = event['data']
            event_prompt_id = str(data.get('prompt_id') or '').strip()
            if event_prompt_id and event_prompt_id != prompt_id:
                continue
            if on_event:
                on_event(event)

            event_type = event['type']
            if event_type == 'executing' and data.get('node') is None and event_prompt_id == prompt_id:
                return {'state': 'completed', 'event': event}
            if event_type in _COMPLETION_EVENTS and event_prompt_id == prompt_id:
                return {'state': 'completed', 'event': event}
            if event_type in _FAILURE_EVENTS and event_prompt_id == prompt_id:
                return {
                    'state': 'failed',
                    'event': event,
                    'message': _comfy_event_error_message(event),
                }

        return {'state': 'timeout', 'message': 'ComfyUI 任务超时'}
    except Exception as exc:
        return {'state': 'unavailable', 'message': f'WebSocket 连接失败：{exc}'}
    finally:
        if socket is not None:
            try:
                socket.close()
            except Exception:
                pass
