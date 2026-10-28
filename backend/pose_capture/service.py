"""Serial photo-recognition queue with cancellation, durable state and pose-sequence results.

`body_assets` (injected by server.py) returns the installed SOMA assets directory or None; with it the
worker also writes each person's recognised body as a mannequin into `bodies/`.
"""
import atexit
import queue
import threading
import time

from .bodies import BodyStore
from .contracts import ACTIVE, identifier, normalize
from .runtime import PoseCaptureCancelled
from .storage import Store

CAPACITY = 8


class PoseCaptureService:
    def __init__(self, root, runtime, body_assets=None):
        self.store, self.runtime = Store(root), runtime
        self.bodies, self._body_assets = BodyStore(self.store.root / 'bodies'), body_assets or (lambda: None)
        self._lock = threading.RLock()
        self._queue = queue.Queue()
        self._events = {}
        self._thread = None
        self._lease = None
        self._closed = False
        atexit.register(self.close)

    def _start(self):
        if self._closed:
            raise RuntimeError('服务正在停止')
        if self._thread:
            return
        import fcntl
        lease = (self.store.root / 'service.lock').open('a+b')
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lease.close()
            raise RuntimeError('另一个服务正在管理姿态识别任务')
        self._lease = lease
        self.store.recover()
        self._thread = threading.Thread(target=self._loop, name='pose-capture-queue', daemon=True)
        self._thread.start()

    def status(self):
        return self.runtime.status()

    def upload(self, data, name):
        return self.store.upload(data, name)

    def submit(self, body):
        kind = self.store.asset_kind(identifier((body or {}).get('asset_id') if isinstance(body, dict) else None))
        spec = normalize(body, kind)
        status = self.runtime.status()
        if not status['ready']:
            raise RuntimeError('姿态识别引擎尚未安装')
        if kind == 'video' and not status['modes'].get('video'):
            raise RuntimeError(status.get('video_message') or '影片识别尚未就绪，请重新运行安装')
        if spec.get('evidence') and not status['modes'].get('evidence'):
            spec['evidence'] = False  # image evidence is an optional refinement: without it the video still runs
        if kind == 'video':
            spec['comotion'] = bool(status['modes'].get('comotion'))  # CoMotion tracking when installed; else the detector
        with self._lock:
            self._start()
            if len(self._events) >= CAPACITY:
                raise RuntimeError('识别队列已满，请稍后再试')
            job = self.store.create({**spec, 'submitted_at': int(time.time())})
            self._events[job['id']] = threading.Event()
            self._queue.put(job['id'])
            return job

    def job(self, ident):
        with self._lock:
            self._start()
        job = self.store.get(ident)
        if job['status'] == 'succeeded':
            # Photo results are small and travel with the job; a video sequence is fetched once from `result_url`.
            if job['spec'].get('mode') == 'video':
                job['result_url'] = '/api/pose_capture/result?id=' + ident
            else:
                job['result'] = self.store.result(ident)
        return job

    def result(self, ident):
        job = self.store.get(ident)
        if job['status'] != 'succeeded':
            raise FileNotFoundError('识别尚未完成')
        return self.store.result(ident)

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
            if ident is None:
                return
            with self._lock:
                event = self._events[ident]
                job = self.store.get(ident)
                if not event.is_set():
                    self.store.update(ident, status='running', started_at=time.time(), stage='准备识别')
            try:
                if event.is_set():
                    raise PoseCaptureCancelled('任务已取消')

                def progress(ratio, stage):
                    with self._lock:
                        if not event.is_set():
                            self.store.update(ident, stage=str(stage)[:120], progress=round(max(0.0, min(1.0, float(ratio))), 3))

                spec = {**job['spec'], 'image': str(self.store.asset(job['spec']['asset_id']).resolve())}
                assets = self._body_assets()
                if assets:
                    spec['bodies'] = {'dir': str(self.bodies.root.resolve()), 'soma_assets': str(assets)}
                result = self.runtime.execute(spec, self.store.path(ident), event, progress)
                with self._lock:
                    if event.is_set():
                        raise PoseCaptureCancelled('任务已取消')
                    people = int(result.get('people') or 0)
                    self.store.update(ident, status='succeeded', stage='识别完成' if people else '未检测到人物', people=people,
                                      progress=1, finished_at=time.time())
            except PoseCaptureCancelled:
                self.store.update(ident, status='cancelled', stage='已停止', finished_at=time.time())
            except Exception as exc:
                self.store.update(ident, status='cancelled' if event.is_set() else 'failed',
                                  stage='已停止' if event.is_set() else '识别失败', error=str(exc)[:2000], finished_at=time.time())
            finally:
                with self._lock:
                    self._events.pop(ident, None)
                self._queue.task_done()

    def body(self, ident):
        return self.bodies.path(ident)

    def release(self):
        """Idle-worker port for other local models: unload only when no recognition is running."""
        try:
            self.runtime.close_idle()
        except RuntimeError:
            pass

    def close(self):
        with self._lock:
            self._closed = True
            for event in self._events.values():
                event.set()
            if self._thread:
                self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=8)
        self.runtime.close()
        if self._lease and (not self._thread or not self._thread.is_alive()):
            self._lease.close()
            self._lease = None
