from __future__ import annotations

import io
import json
import unittest

from backend.routes.runtime_generation_routes import handle_comfy_run
from backend.services.comfy_generation import process_comfy_task
from backend.services.comfy_transport import (
    build_comfy_websocket_url,
    parse_comfy_websocket_message,
    wait_for_comfy_websocket,
)


class _FakeSocket:
    def __init__(self, messages):
        self.messages = list(messages)
        self.timeout = None
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def recv(self):
        if not self.messages:
            return ''
        item = self.messages.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self):
        self.closed = True


class _FakeWebSocketModule:
    class WebSocketTimeoutException(TimeoutError):
        pass

    class WebSocketConnectionClosedException(ConnectionError):
        pass

    def __init__(self, socket=None, error=None):
        self.socket = socket
        self.error = error
        self.url = ''
        self.options = {}

    def create_connection(self, url, **options):
        self.url = url
        self.options = options
        if self.error:
            raise self.error
        return self.socket


class _Clock:
    def __init__(self):
        self.value = 100.0

    def time(self):
        return self.value

    def sleep(self, seconds):
        self.value += float(seconds)


class ComfyWebSocketTransportTest(unittest.TestCase):
    def test_build_url_supports_http_https_and_base_path(self):
        self.assertEqual(
            build_comfy_websocket_url('http://192.168.1.20:8188', 'canvas task/1'),
            'ws://192.168.1.20:8188/ws?clientId=canvas+task%2F1',
        )
        self.assertEqual(
            build_comfy_websocket_url('https://example.test/comfy/', 'abc'),
            'wss://example.test/comfy/ws?clientId=abc',
        )

    def test_wait_filters_other_tasks_and_stops_on_matching_completion(self):
        socket = _FakeSocket([
            b'preview-bytes',
            json.dumps({'type': 'progress', 'data': {'prompt_id': 'other', 'value': 1, 'max': 2}}),
            json.dumps({'type': 'progress', 'data': {'prompt_id': 'wanted', 'value': 2, 'max': 4}}),
            json.dumps({'type': 'executing', 'data': {'prompt_id': 'wanted', 'node': None}}),
        ])
        websocket_module = _FakeWebSocketModule(socket=socket)
        events = []

        result = wait_for_comfy_websocket(
            'wanted',
            'client-1',
            base_url='http://comfy.test:8188',
            deadline=200,
            is_cancelled=lambda: False,
            on_event=events.append,
            websocket_module=websocket_module,
            now=lambda: 100,
        )

        self.assertEqual(result['state'], 'completed')
        self.assertTrue(socket.closed)
        self.assertEqual(websocket_module.url, 'ws://comfy.test:8188/ws?clientId=client-1')
        self.assertEqual([event['type'] for event in events], [
            'transport_connected',
            'progress',
            'executing',
        ])

    def test_connect_failure_is_recoverable(self):
        result = wait_for_comfy_websocket(
            'prompt-1',
            'client-1',
            base_url='http://comfy.test:8188',
            deadline=200,
            is_cancelled=lambda: False,
            websocket_module=_FakeWebSocketModule(error=OSError('offline')),
            now=lambda: 100,
        )
        self.assertEqual(result['state'], 'unavailable')
        self.assertIn('offline', result['message'])

    def test_history_probe_closes_submit_to_socket_race(self):
        socket = _FakeSocket([])
        probes = []
        result = wait_for_comfy_websocket(
            'prompt-1',
            'client-1',
            base_url='http://comfy.test:8188',
            deadline=200,
            is_cancelled=lambda: False,
            completion_probe=lambda: probes.append(True) or True,
            websocket_module=_FakeWebSocketModule(socket=socket),
            now=lambda: 100,
        )
        self.assertEqual(result['state'], 'reconciled')
        self.assertEqual(probes, [True])
        self.assertTrue(socket.closed)

    def test_binary_and_invalid_messages_are_not_events(self):
        self.assertIsNone(parse_comfy_websocket_message(b'\x00\x01'))
        self.assertIsNone(parse_comfy_websocket_message('not-json'))
        self.assertEqual(
            parse_comfy_websocket_message('{"type":"status","data":{}}'),
            {'type': 'status', 'data': {}},
        )


class ComfyGenerationTransportTest(unittest.TestCase):
    @staticmethod
    def _config():
        return {
            'base_url': 'http://comfy.test:8188',
            'task_timeout_seconds': 30,
            'poll_interval_seconds': 0.25,
        }

    def test_websocket_completion_reconciles_history_and_delivers_result(self):
        clock = _Clock()
        history_calls = []
        delivered = []
        statuses = []

        def fetch(task_id):
            history_calls.append(task_id)
            if len(history_calls) == 1:
                return {}, None
            return {task_id: {'status': {'completed': True}}}, {'status': {'completed': True}}

        def wait(task_id, client_id, **kwargs):
            kwargs['on_event']({'type': 'transport_connected', 'data': {}})
            kwargs['on_event']({'type': 'progress', 'data': {'prompt_id': task_id, 'value': 3, 'max': 4}})
            return {'state': 'completed'}

        process_comfy_task(
            'prompt-1',
            'draw a cat',
            'workflow.json',
            '1:1',
            'client-1',
            _fetch_comfy_history_entry=fetch,
            _is_task_canceled=lambda _task_id: False,
            _send_comfy_result=lambda *args: delivered.append(args),
            _sync_comfy_task=lambda task_id, entry: {
                'completed': True,
                'image': {'filename': 'done.png', 'type': 'output'},
                'params': {'telegram_enabled': False},
                'progress_text': 'ComfyUI 已完成，正在整理结果...',
            },
            _wait_for_comfy_websocket=wait,
            get_comfy_config=self._config,
            send_status_notification=lambda *args: None,
            time=clock,
            update_task=lambda *args, **kwargs: None,
            update_task_status=lambda *args, **kwargs: statuses.append((args, kwargs)),
        )

        self.assertEqual(len(delivered), 1)
        self.assertEqual(history_calls, ['prompt-1', 'prompt-1'])
        self.assertTrue(any(item[1].get('progress') == 92 for item in statuses))

    def test_websocket_failure_falls_back_to_history_polling(self):
        clock = _Clock()
        history_entries = [None, None, {'status': {'completed': True}}]
        delivered = []
        statuses = []

        def fetch(task_id):
            entry = history_entries.pop(0)
            return ({task_id: entry} if entry else {}), entry

        process_comfy_task(
            'prompt-2',
            'draw a dog',
            'workflow.json',
            '1:1',
            'client-2',
            _fetch_comfy_history_entry=fetch,
            _is_task_canceled=lambda _task_id: False,
            _send_comfy_result=lambda *args: delivered.append(args),
            _sync_comfy_task=lambda task_id, entry: {
                'completed': True,
                'image': {'filename': 'fallback.png', 'type': 'output'},
                'params': {'telegram_enabled': False},
                'progress_text': 'ComfyUI 已完成，正在整理结果...',
            },
            _wait_for_comfy_websocket=lambda *args, **kwargs: {
                'state': 'unavailable',
                'message': 'offline',
            },
            get_comfy_config=self._config,
            send_status_notification=lambda *args: None,
            time=clock,
            update_task=lambda *args, **kwargs: None,
            update_task_status=lambda *args, **kwargs: statuses.append((args, kwargs)),
        )

        self.assertEqual(len(delivered), 1)
        self.assertTrue(any(
            item[1].get('transport_error_type') == 'ComfyWebSocketFallback'
            for item in statuses
        ))


class _UuidValue:
    hex = 'abcdef0123456789'


class _UuidModule:
    @staticmethod
    def uuid4():
        return _UuidValue()


class _RunHandler:
    def __init__(self, payload):
        body = json.dumps(payload).encode('utf-8')
        self.headers = {'Content-Length': str(len(body))}
        self.rfile = io.BytesIO(body)
        self.started = None
        self.response = None

    def start_generation_task(self, task_id, target, args):
        self.started = (task_id, target, args)
        return True

    def send_json(self, payload, status=200):
        self.response = (payload, status)


class ComfyRunClientIdTest(unittest.TestCase):
    def test_run_uses_a_unique_client_id_for_websocket_routing(self):
        handler = _RunHandler({'workflow': 'test.json', 'prompt': 'hello'})
        submitted = []
        created = []
        process = object()

        handle_comfy_run(
            handler,
            COMFY_CLIENT_ID='canvas',
            COMFY_RESOLUTION_LONG_EDGES={'1k': 0},
            _apply_comfy_parameter_overrides=lambda workflow, params: (workflow, {}),
            _coerce_bool=lambda value, fallback: fallback if value is None else bool(value),
            _collect_comfy_workflows=lambda include_disabled=False: {'items': [{
                'id': 'test.json',
                'enabled': True,
                'accepts_text': True,
                'accepts_image': False,
                'max_images': 0,
                'output_count': 1,
                'default_width': 1024,
                'default_height': 1024,
            }]},
            _comfy_ratio_from_size=lambda width, height: '1:1',
            _load_comfy_workflow=lambda name: ({'1': {'class_type': 'SaveImage'}}, 'test.json'),
            _normalize_comfy_dimension=lambda value, fallback: int(value or fallback),
            _prepare_comfy_workflow=lambda *args, **kwargs: {'prepared': True},
            _proxy_comfy_json=lambda method, path, payload=None: submitted.append(payload) or {'prompt_id': 'prompt-1'},
            _resolve_comfy_size=lambda ratio, resolution: (1024, 1024),
            _upload_comfy_image=lambda image: 'unused.png',
            create_task=lambda *args, **kwargs: created.append((args, kwargs)),
            json=json,
            process_comfy_task=process,
            uuid=_UuidModule,
        )

        client_id = 'canvas-abcdef012345'
        self.assertEqual(submitted[0]['client_id'], client_id)
        self.assertEqual(created[0][0][2]['comfy_client_id'], client_id)
        self.assertEqual(created[0][0][2]['comfy_transport'], 'websocket_history')
        self.assertEqual(handler.started[2][-1], client_id)
        self.assertEqual(handler.response[0]['status'], 'queued')


if __name__ == '__main__':
    unittest.main()
