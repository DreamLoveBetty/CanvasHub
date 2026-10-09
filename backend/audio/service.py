"""Audio queue and asset orchestration. Explicit runtime/storage ports; no image imports."""
import atexit
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import queue
import tempfile
import threading
import time
from urllib.parse import urlencode

from .contracts import MAX_UPLOAD, normalize_job, text
from .storage import Store
from .progress import normalize_progress
from .vendor import yue_abc


def score_action(body):
    abc = text(body.get('abc', ''), 'ABC', 131072, True)
    operation = body.get('operation', 'inspect')
    if operation == 'strip-chords':
        voice = body.get('voice', 'both')
        if voice not in ('both', 'Vocal', 'Ins'):
            raise ValueError('未知声部')
        return {'abc': yue_abc.strip_chords(abc, voice)}
    before = yue_abc.parse_abc(abc)
    if operation == 'inspect':
        return json.loads(json.dumps(yue_abc.report(before), default=yue_abc.json_value))
    if operation == 'compare':
        other = yue_abc.parse_abc(text(body.get('other', ''), '另一份 ABC', 131072, True))
        return yue_abc.compare(before, other)
    raise ValueError('未知乐谱操作')


class AudioService:
    def __init__(self, root, runtime):
        self.root, self.runtime = Path(root), runtime
        self._store = None
        self._lock = threading.RLock()
        self._queue = queue.Queue(maxsize=16)
        self._events = {}
        self._thread = None
        self._closed = False
        self._lease = None
        atexit.register(self.close)

    @property
    def store(self):
        with self._lock:
            if self._store is None:
                # A second server must not mark a live server's jobs interrupted.
                self.root.mkdir(parents=True, exist_ok=True)
                lease = (self.root / 'service.lock').open('a+b')
                try:
                    if os.name == 'nt':
                        import msvcrt
                        lease.write(b'0'); lease.flush(); lease.seek(0)
                        msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    lease.close()
                    raise RuntimeError('音频任务存储已由另一服务使用') from exc
                try:
                    self._store = Store(self.root)
                except Exception:
                    lease.close()
                    raise
                self._lease = lease
            return self._store

    def status(self):
        return self.runtime.status()

    def upload(self, content, filename):
        suffix = Path(filename).suffix.lower()
        if suffix not in ('.wav', '.mp3', '.flac', '.m4a', '.ogg', '.aac', '.webm', '.opus'):
            raise ValueError('不支持的音频扩展名')
        if not content or len(content) > MAX_UPLOAD:
            raise ValueError('音频大小须为 1 字节至 100 MB')
        signatures = {
            '.wav': content[:4] in (b'RIFF', b'RF64') and content[8:12] == b'WAVE',
            '.flac': content.startswith(b'fLaC'), '.ogg': content.startswith(b'OggS'),
            '.opus': content.startswith(b'OggS'), '.m4a': content[4:8] == b'ftyp',
            '.webm': content.startswith(b'\x1a\x45\xdf\xa3'),
            '.mp3': content.startswith(b'ID3') or len(content) > 1 and content[0] == 255 and content[1] & 0xe0 == 0xe0,
            '.aac': len(content) > 1 and content[0] == 255 and content[1] & 0xf6 == 0xf0,
        }
        if not signatures[suffix]:
            raise ValueError('文件内容与音频格式不匹配；不接受播放列表或远程文件引用')
        asset_id = hashlib.sha256(content).hexdigest() + suffix
        root = self.root / 'assets'
        root.mkdir(parents=True, exist_ok=True)
        target = root / asset_id
        if not target.exists():
            with tempfile.NamedTemporaryFile(dir=root, delete=False) as stream:
                temp = Path(stream.name)
                stream.write(content)
            temp.replace(target)
        return {'asset_id': asset_id, 'file_size': len(content)}

    def submit(self, body):
        spec = normalize_job(body)
        status = self.runtime.status()
        kind = 'transcription_ready' if spec['operation'] == 'transcribe' else 'generation_ready'
        if not status[kind]:
            raise RuntimeError('音频引擎未就绪：' + '；'.join(status['reasons']))
        if spec['operation'] == 'transcribe' and not (self.root / 'assets' / spec['asset_id']).is_file():
            raise ValueError('音频素材不存在，请重新上传')
        with self._lock:
            if self._closed or self._queue.full():
                raise RuntimeError('音频队列繁忙，请稍后重试')
            job = self.store.create(spec)
            self._events[job['id']] = threading.Event()
            self._queue.put_nowait(job['id'])
            if self._thread is None:
                self._thread = threading.Thread(target=self._work, name='audio-yue', daemon=True)
                self._thread.start()
        return job

    def cancel(self, job_id):
        with self._lock:
            job = self.store.get(job_id)
            if job['status'] in ('queued', 'running', 'cancelling'):
                event = self._events.get(job_id)
                if event: event.set()
                return self.store.update(job_id, status='cancelling', stage='正在停止音频任务')
            return job

    def _manifest(self, job_id):
        directory = self.store.path(job_id)
        artifacts = []
        for path in sorted(directory.rglob('*')):
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(directory.resolve()):
                continue
            name = path.relative_to(directory).as_posix()
            kind = 'audio' if path.suffix in ('.flac', '.wav') else 'score' if path.suffix == '.abc' else 'file'
            artifacts.append(dict(name=name, kind=kind, file_size=path.stat().st_size,
                                  mime_type=mimetypes.guess_type(name)[0] or 'application/octet-stream',
                                  url='/api/audio/artifact?' + urlencode({'id': job_id, 'name': name})))
        return artifacts

    def _work(self):
        # Lifetime belongs to this service, not to a browser tab or canvas node.
        while not self._closed:
            try: job_id = self._queue.get(timeout=.5)
            except queue.Empty: continue
            cancel = self._events[job_id]
            try:
                spec = self.store.get(job_id)['spec']
                if cancel.is_set():
                    state, error = 'cancelled', ''
                else:
                    self.store.update(job_id, status='running', stage='加载模型 / 推理中', started_at=time.time())
                    directory = self.store.path(job_id)
                    (directory / 'submission.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2))
                    asset = self.root / 'assets' / spec['asset_id'] if spec['operation'] == 'transcribe' else None
                    def progress(event):
                        # Only actual engine observations, no invented completion percentages.
                        safe = normalize_progress(event)
                        if safe:
                            self.store.update(job_id, stage=safe['stage'], progress=safe)
                    state, error = self.runtime.execute(spec, directory, asset, cancel, progress)
                with self._lock:
                    if cancel.is_set(): state, error = 'cancelled', ''
                    self.store.update(job_id, status=state, stage=state, error=error,
                                      artifacts=self._manifest(job_id), finished_at=time.time())
            except Exception as exc:
                self.store.update(job_id, status='cancelled' if cancel.is_set() else 'failed',
                                  stage='任务中止', error=str(exc)[:2000],
                                  artifacts=self._manifest(job_id), finished_at=time.time())
            finally:
                with self._lock: self._events.pop(job_id, None)
                self._queue.task_done()

    def close(self):
        self._closed = True
        with self._lock:
            for event in self._events.values(): event.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
        if self._lease and (not self._thread or not self._thread.is_alive()):
            self._lease.close()
            self._lease = None
