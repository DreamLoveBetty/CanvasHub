#!/usr/bin/env python3
"""ComfyUI video workflows: detection, video inputs, video outputs, archiving and status payloads."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import database, server
from backend.routes import runtime_generation_routes
from backend.services import comfy_video

MP4_BYTES = b'\x00\x00\x00\x18ftypisom' + b'\x00' * 32

WAN_I2V = {
    '1': {'class_type': 'LoadImage', 'inputs': {'image': 'placeholder.png'}},
    '2': {'class_type': 'CLIPTextEncode', 'inputs': {'text': '{{PROMPT}}'}},
    '3': {'class_type': 'WanImageToVideo', 'inputs': {'width': 832, 'height': 480, 'length': 81}},
    '4': {'class_type': 'SaveVideo', 'inputs': {'filename_prefix': 'video/wan', 'format': 'mp4'}},
}
V2V = {
    '1': {'class_type': 'LoadVideo', 'inputs': {'file': 'placeholder.mp4'}},
    '2': {'class_type': 'VHS_LoadVideo', 'inputs': {'video': 'placeholder.mp4', 'force_rate': 0}},
    '3': {'class_type': 'VHS_LoadVideoPath', 'inputs': {'video': '/abs/path.mp4'}},
    '4': {'class_type': 'Note', 'inputs': {'text': 'second={{VIDEO_2}}'}},
    '5': {'class_type': 'VHS_VideoCombine', 'inputs': {'format': 'video/h264-mp4'}},
}


class WorkflowDetectionTest(unittest.TestCase):
    def test_video_savers_and_loaders_are_detected(self) -> None:
        self.assertEqual(comfy_video.workflow_video_io(WAN_I2V), {'output_kind': 'video', 'accepts_video': False})
        self.assertEqual(comfy_video.workflow_video_io(V2V), {'output_kind': 'video', 'accepts_video': True})
        image_only = {'1': {'class_type': 'SaveImage', 'inputs': {}}}
        self.assertEqual(comfy_video.workflow_video_io(image_only), {'output_kind': 'image', 'accepts_video': False})
        self.assertTrue(comfy_video.workflow_video_io(image_only, '"{{VIDEO}}"')['accepts_video'])

    def test_path_loader_alone_does_not_accept_uploads(self) -> None:
        path_only = {'1': {'class_type': 'VHS_LoadVideoPath', 'inputs': {'video': '/x.mp4'}}}
        self.assertFalse(comfy_video.workflow_video_io(path_only)['accepts_video'])

    def test_catalog_reports_video_fields_and_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'wan_i2v.json').write_text(json.dumps(WAN_I2V), encoding='utf-8')
            (root / 'v2v.json').write_text(json.dumps(V2V), encoding='utf-8')
            (root / 'sd15.json').write_text(json.dumps({'1': {'class_type': 'SaveImage', 'inputs': {}}}), encoding='utf-8')
            with patch.object(server, 'COMFY_WORKFLOW_DIR', root), \
                    patch.object(server, '_comfy_workflow_catalog_settings', return_value={'v2v.json': {'max_videos': 9}}):
                items = {item['id']: item for item in server._collect_comfy_workflows(include_disabled=True)['items']}

        self.assertEqual(items['wan_i2v.json']['output_kind'], 'video')
        self.assertEqual(items['wan_i2v.json']['summary'], '图生视频 · 需要参考图')
        self.assertFalse(items['wan_i2v.json']['accepts_video'])
        self.assertEqual(items['wan_i2v.json']['max_videos'], 0)
        self.assertTrue(items['v2v.json']['accepts_video'])
        self.assertEqual(items['v2v.json']['max_videos'], comfy_video.MAX_VIDEOS)
        self.assertEqual(items['v2v.json']['summary'], '视频转视频 · 需要视频')
        self.assertEqual(items['sd15.json']['output_kind'], 'image')
        self.assertEqual(items['sd15.json']['summary'], '文生图 · 单图')
        v2v_parameter_ids = {parameter['id'] for parameter in items['v2v.json']['parameters']}
        self.assertNotIn('1:file', v2v_parameter_ids)
        self.assertNotIn('2:video', v2v_parameter_ids)
        self.assertIn('2:force_rate', v2v_parameter_ids)
        self.assertIn('3:video', v2v_parameter_ids)  # path loaders stay user-editable


class VideoInputTest(unittest.TestCase):
    def test_prepare_fills_upload_loaders_and_tokens(self) -> None:
        prepared = server._prepare_comfy_workflow(V2V, 'p', '16:9', uploaded_video_names=['a.mp4', 'b.mp4'])

        self.assertEqual(prepared['1']['inputs']['file'], 'a.mp4')
        self.assertEqual(prepared['2']['inputs']['video'], 'b.mp4')
        self.assertEqual(prepared['3']['inputs']['video'], '/abs/path.mp4')
        self.assertEqual(prepared['4']['inputs']['text'], 'second=b.mp4')

    def test_image_workflows_are_unchanged_without_videos(self) -> None:
        workflow = {'1': {'class_type': 'LoadImage', 'inputs': {'image': 'x.png'}}}
        prepared = server._prepare_comfy_workflow(workflow, 'p', '1:1', 'up.png', ['up.png'])
        self.assertEqual(prepared['1']['inputs']['image'], 'up.png')

    def test_input_names_must_come_from_upload(self) -> None:
        self.assertEqual(comfy_video.normalize_video_input_names(['miniapp_1_a.mp4', 'b.webm'], 1), ['miniapp_1_a.mp4'])
        for bad in (['../secret.mp4'], ['/abs.mp4'], ['clip.png'], ['sub/clip.mp4']):
            with self.assertRaises(ValueError):
                comfy_video.normalize_video_input_names(bad, 4)

    def test_upload_forwards_video_bytes_to_comfy_input(self) -> None:
        calls = []

        class Response:
            content = b'{}'
            def raise_for_status(self): pass
            def json(self): return {'name': 'miniapp_1_clip.mp4', 'subfolder': '', 'type': 'input'}

        class Session:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def post(self, url, **kwargs):
                calls.append((url, kwargs))
                return Response()

        uploads = comfy_video.ComfyVideoUploads(Session, lambda: {'base_url': 'http://comfy:8188', 'timeout_seconds': 30})
        self.assertEqual(uploads.upload(MP4_BYTES, '我的 clip.mp4'), {'name': 'miniapp_1_clip.mp4'})
        url, kwargs = calls[0]
        self.assertEqual(url, 'http://comfy:8188/upload/image')
        filename, data, mime = kwargs['files']['image']
        self.assertTrue(filename.endswith('_clip.mp4'))
        self.assertEqual((data, mime), (MP4_BYTES, 'video/mp4'))
        with self.assertRaises(ValueError):
            uploads.upload(b'\x89PNG\r\n\x1a\n' + b'\x00' * 16, 'x.png')


class FakeHandler:
    def __init__(self, body: dict):
        raw = json.dumps(body).encode('utf-8')
        self.headers = {'Content-Length': str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.responses = []
        self.started = []

    def send_json(self, payload, status=200):
        self.responses.append((status, payload))

    def start_generation_task(self, *args):
        self.started.append(args)
        return True


class RunRouteTest(unittest.TestCase):
    def run_route(self, body: dict, item: dict):
        created, submitted = [], []
        handler = FakeHandler(body)
        runtime_generation_routes.handle_comfy_run(
            handler,
            COMFY_CLIENT_ID='test', COMFY_RESOLUTION_LONG_EDGES={'1k': 1024},
            _apply_comfy_parameter_overrides=lambda workflow, overrides: (workflow, {}),
            _coerce_bool=server._coerce_bool,
            _collect_comfy_workflows=lambda include_disabled=False: {'items': [item]},
            _comfy_ratio_from_size=lambda w, h: '16:9',
            _load_comfy_workflow=lambda name: (V2V, name),
            _normalize_comfy_dimension=server._normalize_comfy_dimension,
            _prepare_comfy_workflow=server._prepare_comfy_workflow,
            _proxy_comfy_json=lambda method, path, payload=None: submitted.append(payload) or {'prompt_id': 'pid-1'},
            _resolve_comfy_size=lambda ratio, resolution: (1024, 576),
            _upload_comfy_image=lambda data: 'up.png',
            create_task=lambda *args, **kwargs: created.append((args, kwargs)),
            json=json, process_comfy_task=lambda *args: None, uuid=__import__('uuid'),
        )
        return handler, created, submitted

    def test_video_workflow_requires_and_forwards_video_inputs(self) -> None:
        item = {'id': 'v2v.json', 'enabled': True, 'accepts_text': True, 'accepts_image': False,
                'accepts_video': True, 'max_videos': 1, 'output_kind': 'video', 'output_count': 1}
        handler, created, _ = self.run_route({'workflow': 'v2v.json', 'prompt': 'p'}, item)
        self.assertEqual(handler.responses[0][0], 400)
        self.assertIn('视频节点', handler.responses[0][1]['error'])
        self.assertEqual(created, [])

        handler, created, submitted = self.run_route(
            {'workflow': 'v2v.json', 'prompt': 'p', 'videos': ['miniapp_1_a.mp4', 'miniapp_1_b.mp4']}, item)
        self.assertEqual(handler.responses[0][1]['output_kind'], 'video')
        params = created[0][0][2]
        self.assertEqual(params['comfy_output_kind'], 'video')
        self.assertEqual(params['comfy_uploaded_videos'], ['miniapp_1_a.mp4'])
        self.assertEqual(submitted[0]['prompt']['1']['inputs']['file'], 'miniapp_1_a.mp4')


class VideoOutputTest(unittest.TestCase):
    HISTORY_OUTPUTS = {
        '9': {'images': [{'filename': 'wan_00001.mp4', 'subfolder': 'video', 'type': 'output'}], 'animated': [True]},
        '10': {'gifs': [{'filename': 'combine_00001.mp4', 'subfolder': '', 'type': 'output', 'format': 'video/h264-mp4'},
                        {'filename': 'combine_00001.png', 'subfolder': '', 'type': 'output'}]},
        '11': {'images': [{'filename': 'preview.png', 'subfolder': '', 'type': 'temp'}]},
    }

    def test_find_videos_reads_core_and_vhs_outputs_only(self) -> None:
        names = [item['filename'] for item in comfy_video.find_comfy_videos(self.HISTORY_OUTPUTS)]
        self.assertEqual(names, ['wan_00001.mp4', 'combine_00001.mp4'])
        temp_only = {'1': {'gifs': [{'filename': 'p.webm', 'type': 'temp'}]}}
        self.assertEqual(comfy_video.find_comfy_videos(temp_only)[0]['type'], 'temp')

    def test_sync_uses_video_finder_and_explains_missing_video(self) -> None:
        updates = []
        def sync(params, outputs):
            return server._domain_services_comfy_gateway._sync_comfy_task(
                'pid', {'status': {'completed': True, 'status_str': 'success'}, 'outputs': outputs},
                _extract_comfy_error=server._extract_comfy_error, _find_comfy_images=server._find_comfy_images,
                _find_comfy_videos=comfy_video.find_comfy_videos, get_task=lambda _id: {'params': params}, json=json,
                update_task=lambda *a, **k: updates.append(('failed', k)),
                update_task_status=lambda *a, **k: updates.append(('status', k)),
            )

        state = sync({'comfy_output_kind': 'video'}, self.HISTORY_OUTPUTS)
        self.assertEqual(state['image']['filename'], 'wan_00001.mp4')
        self.assertEqual(len(state['images']), 2)
        image_state = sync({}, self.HISTORY_OUTPUTS)
        self.assertEqual(image_state['image']['filename'], 'wan_00001.mp4')  # image path untouched
        failed = sync({'comfy_output_kind': 'video'}, {'1': {'images': [{'filename': 'a.png', 'type': 'output'}]}})
        self.assertIn('没有输出视频', failed['error'])

    def test_video_result_is_archived_sent_and_reported_as_video(self) -> None:
        video = {'filename': 'wan_00001.mp4', 'subfolder': 'video', 'type': 'output'}
        params = {'comfy_images': [video], 'comfy_output_kind': 'video', 'telegram_enabled': True,
                  'width': 832, 'height': 480}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_dir = root / 'archive'
            archive_dir.mkdir()
            with patch.object(database, 'DB_PATH', str(root / 'tasks.db')):
                database.init_db()
                server.create_task('pid-video', 'a cat walks', params, task_type='comfy')
                with patch.object(server, 'daily_output_dir', return_value=archive_dir), \
                        patch.object(server, '_fetch_comfy_binary', return_value=(MP4_BYTES, 'video/mp4')), \
                        patch.object(server, '_probe_archive_video_metadata', return_value={'width': 848, 'height': 480, 'fps': 16.0, 'duration_seconds': 5.06}), \
                        patch.object(server, 'save_thumbnail') as thumbnail, \
                        patch.object(server, 'write_obsidian_prompt_sidecar'), \
                        patch.object(server, 'send_status_notification') as notify, \
                        patch.object(server, 'send_telegram', return_value=True) as send_telegram:
                    server._send_comfy_result('pid-video', 'a cat walks', 'wan_i2v.json', '16:9', video, params)

                archived = list(archive_dir.glob('*.mp4'))
                self.assertEqual(len(archived), 1)
                self.assertEqual(archived[0].read_bytes(), MP4_BYTES)
                self.assertTrue(archived[0].with_suffix('.txt').exists())
                thumbnail.assert_not_called()
                self.assertEqual(send_telegram.call_args.args[1], str(archived[0]))
                self.assertIn('视频', notify.call_args_list[-1].args[1])

                task = server.get_task('pid-video')
                self.assertEqual(task['status'], 'succeeded')
                payload = server._status_response_task(task)
                self.assertEqual(payload['image_paths'], [])
                self.assertEqual(payload['image_count'], 0)
                self.assertEqual(payload['video_paths'], [f'/video/{archived[0].name}'])
                self.assertEqual(payload['video_metadata']['fps'], 16.0)
                self.assertEqual(payload['video_metadata']['width'], 848)
                history = server._format_history_task(task)
                self.assertEqual(history['video_paths'], [f'/video/{archived[0].name}'])
                self.assertEqual(history['image_paths'], [])


if __name__ == '__main__':
    unittest.main()
