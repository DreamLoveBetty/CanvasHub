"""Portable video-control contract, lifecycle and HTTP tests; no model/service required."""
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from backend.video_control.contracts import normalize
from backend.video_control.storage import Store
from backend.video_control.service import VideoControlService
from backend.routes.video_control_routes import create_router
from backend.runtime_resources import local_accelerator
from backend.video_control.pose_quality import coverage_summary, validate_pose_video


class PoseQualityTests(unittest.TestCase):
    def test_sparse_robot_clip_is_not_success(self):
        summary = coverage_summary(360, 4)
        self.assertFalse(summary['usable'])
        self.assertEqual(summary['visible_frames'], 4)

    def test_black_empty_and_usable_coverage(self):
        self.assertFalse(coverage_summary(24, 0)['usable'])
        self.assertTrue(coverage_summary(24, 24)['usable'])
        self.assertTrue(coverage_summary(100, 10)['usable'])
        self.assertFalse(coverage_summary(100, 9)['usable'])
        for counts in ((0, 0), (10, 11), (10, -1)):
            with self.assertRaises(ValueError): coverage_summary(*counts)

    def test_rejected_output_removed_and_diagnostics_preserved(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        frame = SimpleNamespace(shape=(100, 100, 3))
        capture = Mock()
        capture.read.side_effect = [(True, frame), (True, frame), (False, None)]
        cv2 = SimpleNamespace(VideoCapture=lambda _: capture)
        numpy = SimpleNamespace(max=lambda *a, **kw: 0, count_nonzero=lambda _: 0)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'control.mp4'; path.write_bytes(b'synthetic')
            reporter = Mock()
            with patch.dict('sys.modules', {'cv2': cv2, 'numpy': numpy}):
                with self.assertRaisesRegex(ValueError, '未能持续识别人物'):
                    validate_pose_video(path, reporter)
            self.assertFalse(path.exists())
            self.assertEqual(json.loads(path.with_name('metrics.json').read_text())['pose_coverage']['visible_frames'], 0)
            capture.release.assert_called_once()

    def test_visible_output_is_preserved_and_partial_coverage_warns(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        frame = SimpleNamespace(shape=(100, 100, 3))
        for counts, warns in (([100, 100], False), ([100, 0], True)):
            capture = Mock()
            capture.read.side_effect = [(True, frame), (True, frame), (False, None)]
            numpy = SimpleNamespace(max=lambda *a, **kw: 50, count_nonzero=Mock(side_effect=counts))
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'control.mp4'; path.write_bytes(b'synthetic')
                path.with_name('metrics.json').write_text('{"control":"pose"}')
                reporter = Mock()
                with patch.dict('sys.modules', {'cv2': SimpleNamespace(VideoCapture=lambda _: capture), 'numpy': numpy}):
                    result = validate_pose_video(path, reporter)
                self.assertTrue(result['usable'])
                self.assertTrue(path.exists())
                self.assertEqual(json.loads(path.with_name('metrics.json').read_text())['control'], 'pose')
                self.assertEqual(any(call.args[0] == 'warn' for call in reporter.step.call_args_list), warns)


class FakeRuntime:
    def __init__(self): self.gate = threading.Event(); self.gate.set(); self.calls = 0
    def fingerprint(self, control): return ['synthetic-model-v1']
    def status(self): return {'modes': dict.fromkeys(('depth', 'pose', 'canny'), True)}
    def execute(self, spec, directory, asset, cancelled, progress):
        self.calls += 1
        progress({'stage': 'infer', 'message': 'synthetic processing'})
        while not self.gate.wait(.01):
            if cancelled.is_set(): return 'cancelled', ''
        if cancelled.is_set(): return 'cancelled', ''
        result = directory / 'result'; result.mkdir()
        (result / 'control.mp4').write_bytes(b'synthetic result')
        (result / 'result.json').write_text(json.dumps({'width': 320, 'height': 192, 'fps': 24}))
        return 'succeeded', ''


class VideoControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.runtime = FakeRuntime(); self.service = VideoControlService(self.root, self.runtime)
        self.asset = self.service.store.upload(b'synthetic input', 'clip.mp4')
    def tearDown(self): self.service.close(); self.temp.cleanup()
    def submit(self, **params): return self.service.submit({'asset_id': self.asset['asset_id'], **params})
    def finished(self, job):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = self.service.job(job['id'])
            if state['status'] not in {'queued', 'running', 'cancelling'}: return state
            time.sleep(.01)
        self.fail('synthetic job did not finish')
    def test_defaults(self):
        spec = normalize({'asset_id': self.asset['asset_id']})
        self.assertEqual((spec['control'], spec['max_seconds'], spec['max_res']), ('depth', 15, 640))
    def test_invalid_controls_and_untrusted_paths(self):
        for extra in ({'control':'fake'}, {'input':'/etc/passwd'}, {'max_seconds':float('nan')},
                      {'max_res':True}, {'max_seconds':31}, {'pose_face':'false'}, {'control':'canny', 'canny_low':500}, {'quality':'bad'}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                normalize({'asset_id':self.asset['asset_id'], **extra})
        with self.assertRaises(ValueError): self.service.store.asset('../private')
    def test_success_cache_and_parameter_invalidation(self):
        first = self.finished(self.submit())
        self.assertEqual(first['status'], 'succeeded')
        self.assertTrue(self.service.store.artifact(first['id'], 'result/control.mp4').is_file())
        self.assertEqual(self.submit()['id'], first['id'])
        second = self.finished(self.submit(control='canny'))
        self.assertNotEqual(first['id'], second['id']); self.assertEqual(self.runtime.calls, 2)
        with self.assertRaises(FileNotFoundError): self.service.store.artifact(first['id'], '../jobs.sqlite3')
    def test_model_fingerprint_invalidates_cache(self):
        first = self.finished(self.submit())
        self.runtime.fingerprint = lambda control: ['synthetic-model-v2']
        second = self.finished(self.submit())
        self.assertNotEqual(first['id'], second['id'])

    def test_reject_playlists_before_spawning_decoder(self):
        with patch('backend.video_control.service.subprocess.run') as run:
            with self.assertRaises(ValueError): self.service.upload(b'#EXTM3U\nhttp://example.invalid/private', 'clip.mp4')
            run.assert_not_called()

    def test_cancel_running_and_queued(self):
        self.runtime.gate.clear()
        a = self.submit(); b = self.submit(control='pose')
        self.service.cancel(a['id']); self.service.cancel(b['id'])
        for job in (a,b):
            result = self.finished(job); self.assertEqual(result['status'], 'cancelled'); self.assertEqual(result['artifacts'], [])
    def test_restore_marks_unfinished_interrupted(self):
        pending = self.service.store.create(normalize({'asset_id':self.asset['asset_id']}))
        self.service.store.recover()
        self.assertEqual(self.service.store.get(pending['id'])['status'], 'interrupted')
    def test_cancel_completed_does_not_delete_result(self):
        job = self.finished(self.submit()); self.assertEqual(self.service.cancel(job['id'])['status'], 'succeeded')
    def test_failed_job_keeps_original_source(self):
        self.runtime.execute = lambda *args: ('failed', 'synthetic failure')
        result = self.finished(self.submit())
        self.assertEqual(result['status'], 'failed'); self.assertEqual(result['error'], 'synthetic failure')
        self.assertEqual(self.service.store.asset(self.asset['asset_id']).read_bytes(), b'synthetic input')
    def test_symlink_artifact_rejected(self):
        job = self.finished(self.submit()); target = self.service.store.artifact(job['id'],'result/control.mp4')
        target.unlink(); target.symlink_to(self.root/'jobs.sqlite3')
        with self.assertRaises(FileNotFoundError): self.service.store.artifact(job['id'],'result/control.mp4')
    def test_http_requires_auth_and_rejects_unknown_routes(self):
        class Handler:
            path = '/api/video_control/submit'
            headers = {'Content-Length':'2'}
            rfile = io.BytesIO(b'{}')
            def require_auth(self): return False
            def send_json(self, *args): raise AssertionError('unauthenticated dispatch')
        router = create_router(self.service)
        self.assertTrue(router.dispatch(Handler(),'POST',Handler.path))
        self.assertFalse(router.dispatch(Handler(),'POST','/api/unknown'))
    def test_lease_wait_can_be_cancelled(self):
        holder = threading.Event(); release = threading.Event(); path = self.root/'lock'; reports=[]
        def hold():
            with local_accelerator(path, threading.Event(), lambda x:None): holder.set(); release.wait(2)
        thread=threading.Thread(target=hold);thread.start();self.assertTrue(holder.wait(1))
        stop=threading.Event()
        def progress(event): reports.append(event); stop.set()
        with local_accelerator(path,stop,progress): self.assertTrue(stop.is_set())
        release.set();thread.join();self.assertEqual(len(reports),1)


if __name__ == '__main__': unittest.main()
