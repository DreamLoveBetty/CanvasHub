"""Offline, cancellable ReShot subprocess adapter with bounded runtime/logs."""
import importlib.metadata
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time


class Runtime:
    def __init__(self, component, python=None, before_load=None):
        self.before_load = before_load
        self.root = Path(component)
        self._fingerprints = {}
        self.python = python or (None if getattr(sys, 'frozen', False) else sys.executable)

    def status(self):
        expected = dict(line.split('==', 1) for line in Path(__file__).with_name('requirements-py314.txt').read_text().splitlines() if line and not line.startswith('#'))
        try: installed = all(importlib.metadata.version(name) == version for name, version in expected.items())
        except importlib.metadata.PackageNotFoundError: installed = False
        models = self.root / 'models'
        base = bool(self.python and installed and all(shutil.which(name, path=self.worker_path()) for name in ('ffmpeg', 'ffprobe')))
        return {'engine': 'ReShot 0.5.0', 'ready': base, 'modes': {
            'canny': base, 'depth': base and (models / 'depth/video_depth_anything_vits.pth').is_file(),
            'pose': base and all((models / 'pose' / name).is_file() for name in ('yolox_l.onnx', 'dw-ll_ucoco_384.onnx'))}}

    def fingerprint(self, control):
        names = {'depth': ['depth/video_depth_anything_vits.pth'], 'pose': ['pose/yolox_l.onnx', 'pose/dw-ll_ucoco_384.onnx'], 'canny': []}[control]
        paths = [self.root / 'models' / name for name in names]
        key = tuple((p.stat().st_size, p.stat().st_mtime_ns) for p in paths)
        if self._fingerprints.get(control, (None,))[0] != key:
            hashes = []
            for path in paths:
                with path.open('rb') as stream: hashes.append(hashlib.file_digest(stream, 'sha256').hexdigest())
            self._fingerprints[control] = (key, hashes)
        return self._fingerprints[control][1]

    @staticmethod
    def worker_path():
        return os.pathsep.join([os.environ.get('PATH', ''), '/opt/homebrew/bin', '/usr/local/bin'])

    def execute(self, spec, directory, asset, cancelled, progress):
        from ..runtime_resources import local_accelerator
        with local_accelerator(self.root.parent / '.local-inference.lock', cancelled, progress):
            if cancelled.is_set(): return 'cancelled', ''
            if self.before_load:
                self.before_load()
            return self._execute(spec, directory, asset, cancelled, progress)

    def _execute(self, spec, directory, asset, cancelled, progress):
        request = directory / 'request.json'; request.write_text(json.dumps(spec))
        env = {**os.environ, 'PATH': self.worker_path(), 'HF_HUB_OFFLINE': '1',
               'HF_HOME': str(self.root / 'cache'), 'PYTHONUNBUFFERED': '1'}
        process = subprocess.Popen([str(self.python), '-u', str(Path(__file__).with_name('worker.py')),
            str(os.getpid()), str(request), str(asset), str(directory / 'result'), str(self.root / 'models')],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True, env=env)
        done = threading.Event(); expired = threading.Event()
        def stop():
            deadline = time.monotonic() + 1800
            while not done.wait(.2):
                if cancelled.is_set() or time.monotonic() > deadline:
                    if not cancelled.is_set(): expired.set()
                    try: os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError: return
                    if not done.wait(3):
                        try: os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                    return
        watchdog = threading.Thread(target=stop, daemon=True); watchdog.start()
        tail = []
        try:
            with (directory / 'runtime.log').open('wb') as stream:
                written = 0
                for raw in iter(lambda: process.stdout.readline(16384), b''):
                    if written < 4 * 1024 * 1024: stream.write(raw); written += len(raw)
                    line = raw.decode('utf-8', 'replace').strip(); tail = (tail + [line])[-10:]
                    if line.startswith('CANVAS_PROGRESS '):
                        try: progress(json.loads(line[len('CANVAS_PROGRESS '):]))
                        except ValueError: pass
            code = process.wait()
        finally:
            done.set(); process.stdout.close()
            if process.poll() is None:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait()
            watchdog.join(timeout=4)
        if cancelled.is_set(): return 'cancelled', ''
        if expired.is_set(): return 'failed', '视频处理超过 30 分钟，已停止'
        if code or not (directory / 'result/control.mp4').is_file():
            return 'failed', '\n'.join(tail)[-2000:] or '未生成控制视频'
        return 'succeeded', ''
