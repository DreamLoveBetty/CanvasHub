"""ASR domain (backend.asr): contracts, environment preparation/status, the one-shot runtime and routes.

No model, venv or network: preparation gets fake uv/run/fetch, the runtime runs a tiny fake worker
with this interpreter, and the worker's pure helpers are imported directly.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock

from backend.asr import contracts, environment, runtime, service, worker
from backend.routes.asr_routes import create_router


class ContractTests(unittest.TestCase):
    def test_generation_cap_and_timeout_grow_with_audio(self):
        self.assertEqual(contracts.max_new_tokens(0), 32)
        self.assertEqual(contracts.max_new_tokens(12), 128)
        self.assertEqual(contracts.max_new_tokens(10_000), 2048)
        self.assertEqual(contracts.timeout_seconds(180), 720)

    def test_fillers_are_not_speech(self):
        for text in ('', '  ', '啊。', '嗯嗯', 'Oh.', 'uh, um', '。！'):
            self.assertTrue(contracts.is_filler(text), text)
        for text in ('你好', '啊，今天天气很好', 'Hello there', 'yeah', 'oh oh oh oh oh', '好的 OK'):
            self.assertFalse(contracts.is_filler(text), text)

    def test_script_only_converts_chinese(self):
        self.assertEqual(contracts.script_config('traditional', 'Chinese'), 's2tw')
        self.assertEqual(contracts.script_config('simplified', 'Cantonese'), 't2s')
        self.assertEqual(contracts.script_config('traditional', 'English'), '')
        self.assertEqual(contracts.script_config('original', 'Chinese'), '')
        with self.assertRaises(ValueError):
            contracts.script_config('pinyin', 'Chinese')


class WorkerHelperTests(unittest.TestCase):
    class Item:
        def __init__(self, text, start, end):
            self.text, self.start_time, self.end_time = text, start, end

    def test_tokens_carry_following_punctuation_and_spaces(self):
        items = [self.Item('你', 0, .2), self.Item('好', .2, .4), self.Item('Hello', .5, .9), self.Item('world', 1, 1.4)]
        tokens = worker.attach_text('你好，Hello world!', items)
        self.assertEqual([t[2] for t in tokens], ['你', '好，', 'Hello ', 'world!'])
        self.assertEqual(tokens[1][3], (1, 3))

    def test_unlocated_unit_keeps_its_own_text(self):
        tokens = worker.attach_text('甲乙', [self.Item('甲', 0, 1), self.Item('丙', 1, 2), self.Item('乙', 2, 3)])
        self.assertEqual([t[2] for t in tokens], ['甲', '丙', '乙'])
        self.assertIsNone(tokens[1][3])

    def test_no_conversion_passes_tokens_through(self):
        text, tokens = worker.convert('好', [(0.0, 1.0, '好', (0, 1))], '')
        self.assertEqual((text, tokens), ('好', [{'start': 0.0, 'end': 1.0, 'text': '好'}]))


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'asr'
        self.assets = {'models': {'asr': {'repo': 'Q/A', 'huggingface_revision': 'h1', 'files': {
            'a.bin': {'size': 3, 'sha256': 'x', 'modelscope_revision': 'm1'}}}}}
        patches = [mock.patch.object(environment, 'load_assets', return_value=self.assets),
                   mock.patch.object(environment, 'supported_platform', return_value=True)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self.temp.cleanup)

    def fake_run(self, argv, check):
        if argv[1] == 'venv':
            python = Path(argv[-1]) / 'bin' / 'python'
            python.parent.mkdir(parents=True)
            python.write_text('')
        self.commands.append(argv)

    def test_prepare_builds_env_falls_back_to_hugging_face_and_writes_receipt_last(self):
        self.commands, urls = [], []

        def fetch(url, target, *, size, sha256_value, progress, proxies):
            urls.append((url, proxies))
            if 'modelscope' in url:
                raise OSError('timeout')
            self.assertFalse((self.root / 'installed.json').exists())
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'abc')
            progress(3, 3)

        with mock.patch('builtins.print'):
            result = environment.prepare(root=self.root, uv='/bin/uv', run=self.fake_run, fetch=fetch)
        self.assertIn('--require-hashes', self.commands[1])
        self.assertIn('--no-deps', self.commands[1])
        self.assertEqual(urls, [('https://www.modelscope.cn/models/Q/A/resolve/m1/a.bin', environment.DIRECT),
                                ('https://huggingface.co/Q/A/resolve/h1/a.bin', None)])
        receipt = environment.read_receipt(self.root)
        self.assertEqual(receipt['python'], str(self.root / 'venv' / 'bin' / 'python'))
        self.assertIn('qwen-asr', receipt['versions'])
        self.assertEqual(result['download_bytes'], 3)

    def test_prepare_failure_leaves_no_receipt(self):
        self.commands = []

        def fetch(*_args, **_kwargs):
            raise OSError('offline')

        with mock.patch('builtins.print'), self.assertRaisesRegex(RuntimeError, 'a.bin 下载失败'):
            environment.prepare(root=self.root, uv='/bin/uv', run=self.fake_run, fetch=fetch)
        self.assertEqual(environment.read_receipt(self.root), {})

    def test_status_reports_missing_pieces_without_paths(self):
        self.assertEqual(environment.status(self.root)['reasons'], ['语音识别环境尚未准备'])
        python = self.root / 'venv' / 'bin' / 'python'
        python.parent.mkdir(parents=True)
        python.write_text('')
        (self.root / 'installed.json').write_text(json.dumps({'python': str(python), 'prepared_at': 5}))
        state = environment.status(self.root, probe=lambda *_: ['torch'])
        self.assertFalse(state['ready'])
        self.assertEqual(state['reasons'], ['语音识别依赖版本不符：torch', '语音识别模型文件缺失：asr/a.bin'])
        (self.root / 'assets' / 'asr').mkdir(parents=True)
        (self.root / 'assets' / 'asr' / 'a.bin').write_bytes(b'abc')
        self.assertEqual(environment.status(self.root, probe=lambda *_: [])['ready'], True)

    def test_lock_pins_every_runtime_import(self):
        pinned = environment.pinned_packages()
        for name in ('torch', 'transformers', 'accelerate', 'librosa', 'soundfile', 'nagisa', 'numpy', 'opencc',
                     'qwen-asr'):
            self.assertIn(name, pinned)
        lock = (Path(environment.__file__).with_name('requirements.lock')).read_text(encoding='utf-8')
        self.assertGreaterEqual(lock.count('--hash=sha256:'), len(pinned))
        real = json.loads(environment.ASSETS_LOCK.read_text(encoding='utf-8'))
        for model in real['models'].values():
            for item in model['files'].values():
                self.assertRegex(item['sha256'], r'^[0-9a-f]{64}$')


FAKE_WORKER = textwrap.dedent('''
    import json, sys, time
    request = json.load(open(sys.argv[1]))
    mode = open(request["audio"]).read()
    print("ASR_EVENT " + json.dumps({"event": "progress", "ratio": 0.5, "stage": "识别中"}), flush=True)
    if mode == "sleep":
        time.sleep(30)
    if mode == "fail":
        print("boom: out of memory", flush=True)
        sys.exit(3)
    text = "啊。" if mode == "music" else "你好。"
    json.dump({"language": "Chinese", "text": text,
               "tokens": [{"start": 0.1, "end": 0.4, "text": text}]}, open(sys.argv[2], "w"))
''')


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / 'components' / 'asr'
        self.root.mkdir(parents=True)
        (self.root / 'installed.json').write_text(json.dumps({'python': sys.executable}))
        self.fake = base / 'fake_worker.py'
        self.fake.write_text(FAKE_WORKER)
        self.audio = base / 'voice.wav'
        self.unloaded = []

        def popen(argv, **kwargs):
            argv = [argv[0], argv[1], str(self.fake), *argv[3:]]
            self.assertIn('CANVASHUB_IMAGE_PARENT_PID', kwargs['env'])
            self.assertTrue(kwargs['start_new_session'])
            return subprocess.Popen(argv, **kwargs)

        self.runtime = runtime.Runtime(self.root, before_load=lambda: self.unloaded.append(1), popen=popen)

    def run_mode(self, mode, cancelled=None, seconds=5):
        self.audio.write_text(mode)
        events = []
        result = self.runtime.transcribe(self.audio, seconds=seconds, script='original',
                                         cancelled=cancelled or threading.Event(),
                                         progress=lambda ratio, stage: events.append((ratio, stage)))
        return result, events

    def test_result_progress_unload_and_lock_release(self):
        result, events = self.run_mode('speech')
        self.assertEqual(result, {'language': 'Chinese', 'text': '你好。', 'speech': True,
                                  'tokens': [{'start': 0.1, 'end': 0.4, 'text': '你好。'}]})
        self.assertIn((0.5, '识别中'), events)
        self.assertEqual(self.unloaded, [1])
        self.assertTrue((self.root / 'runtime' / 'last-run.log').is_file())
        import fcntl
        with (self.root.parent / '.local-inference.lock').open('a+b') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)  # released after the run

    def test_music_is_not_speech(self):
        self.assertFalse(self.run_mode('music')[0]['speech'])

    def test_failure_reports_the_last_worker_line(self):
        with self.assertRaisesRegex(runtime.AsrError, 'boom: out of memory'):
            self.run_mode('fail')

    def test_cancel_kills_the_worker(self):
        cancelled = threading.Event()
        threading.Timer(0.5, cancelled.set).start()
        started = time.monotonic()
        with self.assertRaises(runtime.AsrCancelled):
            self.run_mode('sleep', cancelled)
        self.assertLess(time.monotonic() - started, 10)

    def test_timeout_kills_the_worker(self):
        with mock.patch.object(runtime, 'timeout_seconds', return_value=1), \
                self.assertRaisesRegex(runtime.AsrError, '超过 1 秒'):
            self.run_mode('sleep')

    def test_relative_component_becomes_absolute(self):
        # The worker runs with cwd=component, so a relative model path would be read as a hub repo id.
        self.assertTrue(runtime.Runtime(Path('components/asr')).root.is_absolute())

    def test_refuses_long_audio_and_missing_environment(self):
        with self.assertRaisesRegex(runtime.AsrError, '180'):
            self.run_mode('speech', seconds=181)
        (self.root / 'installed.json').unlink()
        with self.assertRaisesRegex(runtime.AsrError, '尚未准备'):
            self.run_mode('speech')


class ServiceAndRouteTests(unittest.TestCase):
    class Preparation:
        def __init__(self):
            self.state = {'status': 'idle'}
            self.started = []

        def status(self):
            return dict(self.state)

        def start(self, command, cwd, metadata):
            self.started.append(command)
            return {'status': 'running'}

        def close(self):
            pass

    def make(self):
        self.reads = []
        self.preparation = self.Preparation()
        return service.AsrService(
            '/nonexistent/asr', runtime=mock.Mock(), preparation=self.preparation,
            status_reader=lambda root: self.reads.append(root) or {'ready': True, 'reasons': [], 'prepared_at': 1,
                                                                     'download_bytes': 9})

    def test_status_is_cached_until_preparation_changes(self):
        asr = self.make()
        state = asr.status()
        self.assertEqual((state['ready'], state['engine'], state['max_seconds']), (True, 'Qwen3-ASR 1.7B', 180))
        self.assertEqual(state['scripts'], ['original', 'traditional', 'simplified'])
        asr.status()
        self.assertEqual(len(self.reads), 1)
        self.preparation.state = {'status': 'running', 'stage': 'assets'}
        self.assertFalse(asr.status()['ready'])
        self.assertEqual(len(self.reads), 2)
        with self.assertRaisesRegex(RuntimeError, '正在准备'):
            asr.transcribe('x.wav', seconds=1, script='original', cancelled=threading.Event(), progress=print)

    def test_prepare_runs_the_environment_module(self):
        asr = self.make()
        asr.prepare()
        self.assertEqual(self.preparation.started[0][-3:], ['-m', 'backend.asr.environment', 'prepare'])

    def test_routes(self):
        asr = self.make()
        router = create_router(asr)

        class Handler:
            def __init__(self, body=b''):
                self.headers = {'Content-Length': str(len(body))}
                self.rfile = io.BytesIO(body)
                self.sent = self.status = None

            def require_auth(self):
                return True

            def send_json(self, payload, status=200, headers=None):
                self.sent, self.status = payload, status

        handler = Handler()
        self.assertTrue(router.dispatch(handler, 'GET', '/api/asr/status'))
        self.assertEqual(handler.status, 200)
        self.assertNotIn('/nonexistent', json.dumps(handler.sent))
        handler = Handler(b'{}')
        self.assertTrue(router.dispatch(handler, 'POST', '/api/asr/prepare'))
        self.assertEqual(handler.status, 202)
        handler = Handler(b'x' * 5000)
        router.dispatch(handler, 'POST', '/api/asr/prepare')
        self.assertEqual(handler.status, 400)

    def test_server_wires_asr_under_the_shared_unload(self):
        server = (Path(__file__).resolve().parents[1] / 'backend' / 'server.py').read_text(encoding='utf-8')
        self.assertIn("AsrService(APP_DATA_DIR / 'components' / 'asr'", server)
        self.assertIn('before_load=_LOCAL_IMAGE_MEMORY.release_all))\n_ASR_ROUTES', server)
        self.assertIn("_ASR_ROUTES.dispatch(self, 'GET', path)", server)
        self.assertIn("_ASR_ROUTES.dispatch(self, 'POST', path)", server)


if __name__ == '__main__':
    unittest.main()
