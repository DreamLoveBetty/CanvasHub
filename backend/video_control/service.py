"""Serial queue, cancellation and durable outputs for local video preprocessing."""
import atexit
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import os
import threading
import time
from urllib.parse import urlencode

from .contracts import ACTIVE, ENGINE, normalize
from .storage import Store


class VideoControlService:
    def __init__(self, root, runtime):
        self.store = Store(root); self.runtime = runtime
        self._lock = threading.RLock(); self._queue = queue.Queue()
        self._events = {}; self._thread = None; self._lease = None; self._closed = False
        atexit.register(self.close)

    def _start(self):
        if self._closed: raise RuntimeError('服务正在停止')
        if self._thread: return
        import fcntl
        lease = (self.store.root / 'service.lock').open('a+b')
        try: fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lease.close(); raise RuntimeError('另一个服务正在管理视频控制任务')
        self._lease = lease; self.store.recover()
        self._thread = threading.Thread(target=self._loop, daemon=True); self._thread.start()

    def status(self): return self.runtime.status()
    def upload(self, data, name):
        if not (data[:4] == b'\x1aE\xdf\xa3' or data[4:8] in {b'ftyp', b'moov', b'mdat', b'wide', b'free'}):
            raise ValueError('仅接受 MP4 / MOV / WebM / MKV 视频容器')
        info = self.store.upload(data, name)
        path = self.store.asset(info['asset_id'])
        try:
            result = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height', '-of', 'json', str(path)],
                capture_output=True, text=True, timeout=20,
                env={**os.environ, 'PATH': self.runtime.worker_path()})
            streams = json.loads(result.stdout).get('streams', []) if result.returncode == 0 else []
            if not streams or not 0 < streams[0].get('width', 0) <= 7680 or not 0 < streams[0].get('height', 0) <= 7680:
                raise ValueError('无法读取视频或视频尺寸超过 7680 像素')
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            path.unlink(missing_ok=True); path.with_suffix('.json').unlink(missing_ok=True)
            raise ValueError('无法读取视频，请导入有效的本地 MP4 / MOV / WebM 视频') from exc
        return info

    def submit(self, body):
        spec = normalize(body); asset = self.store.asset(spec['asset_id'])
        if not self.runtime.status()['modes'].get(spec['control']):
            raise RuntimeError('本地 ReShot 环境或对应模型尚未安装')
        fingerprint = hashlib.sha256(asset.read_bytes()).hexdigest()
        cache_key = hashlib.sha256(json.dumps([ENGINE, self.runtime.fingerprint(spec['control']), fingerprint,
            {k: v for k, v in spec.items() if k != 'asset_id'}], sort_keys=True).encode()).hexdigest()
        with self._lock:
            self._start()
            if len(self._events) >= 8: raise RuntimeError('视频控制队列已满，请稍后提交')
            with self.store.db() as db:
                rows = db.execute('SELECT data FROM jobs ORDER BY rowid DESC LIMIT 100').fetchall()
            for (raw,) in rows:
                old = json.loads(raw)
                if old.get('cache_key') == cache_key and old['status'] == 'succeeded':
                    try: self.store.artifact(old['id'], 'result/control.mp4')
                    except FileNotFoundError: continue
                    return old
            job = self.store.create(spec)
            job = self.store.update(job['id'], cache_key=cache_key, engine=ENGINE)
            self._events[job['id']] = threading.Event(); self._queue.put(job['id'])
            return job

    def job(self, ident):
        with self._lock: self._start()
        return self.store.get(ident)

    def cancel(self, ident):
        with self._lock:
            job = self.store.get(ident)
            event = self._events.get(ident)
            if event and job['status'] in ACTIVE:
                event.set()
                return self.store.update(ident, status='cancelling', stage='正在停止')
            return job

    def _loop(self):
        while True:
            ident = self._queue.get()
            if ident is None: return
            with self._lock:
                event = self._events[ident]
                job = self.store.get(ident)
                if not event.is_set(): self.store.update(ident, status='running', started_at=time.time(), stage='准备本地处理')
            try:
                def progress(info):
                    with self._lock:
                        if event.is_set(): return
                        observation = {'stage': str(info.get('stage', ''))[:200], 'message': str(info.get('message', ''))[:1000]}
                        events = (self.store.get(ident).get('events', []) + [observation])[-50:]
                        self.store.update(ident, stage=observation['stage'], progress_message=observation['message'], events=events)
                status, error = ('cancelled', '') if event.is_set() else self.runtime.execute(job['spec'],
                    self.store.path(ident), self.store.asset(job['spec']['asset_id']), event, progress)
                with self._lock:
                    if event.is_set(): status, error = 'cancelled', ''
                    artifacts = []
                    if status == 'succeeded':
                        result = self.store.path(ident) / 'result'
                        meta = json.loads((result / 'result.json').read_text())
                        for name in ('control.mp4', 'metrics.json', 'result.json'):
                            file = result / name
                            if file.is_file():
                                relative = 'result/' + name
                                artifacts.append({'name': relative, 'file_size': file.stat().st_size,
                                    'url': '/api/video_control/artifact?' + urlencode({'id': ident, 'name': relative})})
                        self.store.update(ident, media=meta)
                    self.store.update(ident, status=status, error=error,
                        stage={'succeeded': '处理完成', 'failed': '处理失败', 'cancelled': '已停止'}.get(status, status),
                        finished_at=time.time(), artifacts=artifacts)
            except Exception as exc:
                self.store.update(ident, status='cancelled' if event.is_set() else 'failed',
                                  stage='已停止' if event.is_set() else '处理失败', error=str(exc)[:2000], finished_at=time.time())
            finally:
                with self._lock: self._events.pop(ident, None)
                self._queue.task_done()

    def close(self):
        with self._lock:
            self._closed = True
            for event in self._events.values(): event.set()
            if self._thread: self._queue.put(None)
        if self._thread: self._thread.join(timeout=8)
        if self._lease and (not self._thread or not self._thread.is_alive()):
            self._lease.close(); self._lease = None
