"""Serial job service for the video-edit domain: exact frames, scene candidates, audio separation.

Jobs are short-lived and kept in memory only (a restart forgets receipts, never outputs): every
output is written straight into the archive, so a lost receipt loses nothing the user keeps.
Outputs are idempotent per source content (sha256 prefix), so repeating a request reuses files.

Ports injected by server.py:
* resolver.resolve(url) -> Path         (sources.SourceResolver)
* frame_dir() -> Path                    (today's archive folder for images)
* write_sidecar(path, prompt, txt_path=) (Obsidian `.md` note beside an archived file)
* audio_archive.find(glob) / publish_file(...) (services.archive_audio.AudioArchive)
"""
from __future__ import annotations

import atexit
from collections import OrderedDict
import hashlib
from pathlib import Path
import queue
import tempfile
import threading
import time
import uuid

from . import contracts
from .media import Cancelled, Runner, Tools
from . import media


def _write_text(path: Path, text: str) -> None:
    pending = path.with_name('.' + path.name + '.writing')
    pending.write_text(text, encoding='utf-8')
    pending.replace(path)


class VideoEditService:
    def __init__(self, *, resolver, frame_dir, write_sidecar, audio_archive, tools=None, runner=None):
        self.resolver = resolver
        self.frame_dir = frame_dir
        self.write_sidecar = write_sidecar
        self.audio_archive = audio_archive
        self.tools = tools or Tools()
        self.runner = runner or Runner()
        self._lock = threading.RLock()
        self._jobs: OrderedDict[str, dict] = OrderedDict()
        self._cancels: dict[str, threading.Event] = {}
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._probe_cache: OrderedDict[tuple, dict] = OrderedDict()
        self._digest_cache: OrderedDict[tuple, str] = OrderedDict()
        self._filmstrips: OrderedDict[tuple, bytes] = OrderedDict()
        self._previews = threading.BoundedSemaphore(2)
        self._closed = False
        atexit.register(self.close)

    # ----- synchronous reads -------------------------------------------------------------
    def status(self) -> dict:
        ready = bool(self.tools.ffmpeg and self.tools.ffprobe)
        with self._lock:
            active = sum(1 for job in self._jobs.values() if job['status'] in contracts.ACTIVE)
        return {'available': ready, 'reason': '' if ready else '未找到 FFmpeg / ffprobe，请先安装 FFmpeg',
                'active_jobs': active,
                'limits': {'max_source_seconds': contracts.MAX_SOURCE_SECONDS,
                           'max_frames_per_job': contracts.MAX_FRAMES_PER_JOB,
                           'max_queued_jobs': contracts.MAX_QUEUED_JOBS}}

    def locate(self, url: str) -> Path:
        """Whitelisted source URL -> local file, without probing it."""
        return self.resolver.resolve(contracts.source_url(url))

    def source(self, url: str) -> tuple[Path, dict]:
        path = self.locate(url)
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        with self._lock:
            cached = self._probe_cache.get(key)
            if cached is not None:
                self._probe_cache.move_to_end(key)
                return path, cached
        info = media.probe(path, self.tools, self.runner)
        with self._lock:
            self._probe_cache[key] = info
            while len(self._probe_cache) > 16:
                self._probe_cache.popitem(last=False)
        return path, info

    def digest(self, path: Path) -> str:
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        with self._lock:
            if key in self._digest_cache:
                return self._digest_cache[key]
        digest = hashlib.sha256()
        with open(path, 'rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        value = digest.hexdigest()[:12]
        with self._lock:
            self._digest_cache[key] = value
            while len(self._digest_cache) > 64:
                self._digest_cache.popitem(last=False)
        return value

    def probe(self, url: str) -> dict:
        _, info = self.source(url)
        public = {key: info[key] for key in ('width', 'height', 'duration_seconds', 'fps', 'frame_count', 'codec',
                                             'frame_times', 'audio')}
        public['has_audio'] = bool(info['audio'])
        return public

    def preview_frame(self, url: str, frame, width) -> bytes:
        path, info = self.source(url)
        index = contracts.frame_index(frame, info['frame_count'])
        if not self._previews.acquire(timeout=10):
            raise RuntimeError('预览繁忙，请稍后再试')
        try:
            return media.preview_frame(path, info, index, contracts.preview_width(width), self.tools, self.runner)
        finally:
            self._previews.release()

    def filmstrip(self, url: str, tiles) -> bytes:
        """Timeline thumbnails for one source (cached: the compose workbench asks again on every open)."""
        path, info = self.source(url)
        count = contracts.filmstrip_tiles(tiles)
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size, count)
        with self._lock:
            cached = self._filmstrips.get(key)
            if cached is not None:
                self._filmstrips.move_to_end(key)
                return cached
        if not self._previews.acquire(timeout=30):
            raise RuntimeError('预览繁忙，请稍后再试')
        try:
            data = media.filmstrip(path, info, count, contracts.FILMSTRIP_HEIGHT, self.tools, self.runner)
        finally:
            self._previews.release()
        with self._lock:
            self._filmstrips[key] = data
            while len(self._filmstrips) > 32:
                self._filmstrips.popitem(last=False)
        return data

    # ----- jobs ------------------------------------------------------------------------------
    def submit(self, body) -> dict:
        request = contracts.submit_request(body)
        self.tools.require()
        _, info = self.source(request['source_url'])
        if request['kind'] == 'frames':
            request['frames'] = contracts.frame_list(request['frames'], info['frame_count'])
        if request['kind'] == 'extract_audio' and not info['audio']:
            raise ValueError('该视频没有音轨')
        with self._lock:
            if self._closed:
                raise RuntimeError('视频剪辑服务正在停止')
            self._prune()
            if sum(1 for job in self._jobs.values() if job['status'] in contracts.ACTIVE) >= contracts.MAX_QUEUED_JOBS:
                raise RuntimeError('视频剪辑任务排队已满，请稍后再试')
            ident = uuid.uuid4().hex
            now = time.time()
            job = {'id': ident, 'task_id': ident, 'kind': request['kind'], 'status': 'queued', 'stage': '排队中',
                   'progress_percent': 0, 'error': '', 'result': None, 'created_at': now, 'updated_at': now,
                   'request': request}
            self._jobs[ident] = job
            self._cancels[ident] = threading.Event()
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, name='video-edit-jobs', daemon=True)
                self._thread.start()
            self._queue.put(ident)
            return self._public(job)

    def job(self, ident) -> dict:
        with self._lock:
            job = self._jobs.get(str(ident or ''))
            if job is None:
                raise FileNotFoundError('视频剪辑任务不存在或已过期')
            return self._public(job)

    def cancel(self, ident) -> dict:
        with self._lock:
            job = self._jobs.get(str(ident or ''))
            if job is None:
                raise FileNotFoundError('视频剪辑任务不存在或已过期')
            if job['status'] in contracts.ACTIVE:
                self._cancels[job['id']].set()
                if job['status'] == 'queued':
                    self._finish(job, 'cancelled', stage='已取消')
            return self._public(job)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for event in self._cancels.values():
                event.set()
        self._queue.put(None)

    @staticmethod
    def _public(job: dict) -> dict:
        return {key: value for key, value in job.items() if key != 'request'} | {
            'source_url': job['request']['source_url']}

    def _prune(self) -> None:
        cutoff = time.time() - contracts.JOB_TTL_SECONDS
        finished = [ident for ident, job in self._jobs.items() if job['status'] in contracts.FINISHED]
        for ident in finished:
            if self._jobs[ident]['updated_at'] < cutoff or len(self._jobs) > contracts.MAX_KEPT_JOBS:
                self._jobs.pop(ident, None)
                self._cancels.pop(ident, None)

    def _update(self, job: dict, **changes) -> None:
        with self._lock:
            job.update(changes, updated_at=time.time())

    def _finish(self, job: dict, status: str, **changes) -> None:
        self._update(job, status=status, **changes)

    def _loop(self) -> None:
        while True:
            ident = self._queue.get()
            if ident is None:
                return
            with self._lock:
                job = self._jobs.get(ident)
                if job is None or job['status'] != 'queued':
                    continue
                cancel = self._cancels[ident]
                job.update(status='running', stage='处理中', updated_at=time.time())
            try:
                result = getattr(self, '_run_' + job['kind'])(job, cancel)
                self._finish(job, 'succeeded', stage='完成', progress_percent=100, result=result)
            except Cancelled:
                self._finish(job, 'cancelled', stage='已取消')
            except (ValueError, RuntimeError, FileNotFoundError) as exc:
                self._finish(job, 'failed', stage='失败', error=str(exc))
            except OSError:
                self._finish(job, 'failed', stage='失败', error='视频剪辑读写失败')

    def _source_name(self, job: dict, path: Path) -> str:
        return job['request'].get('source_name') or path.name

    def _run_frames(self, job: dict, cancel: threading.Event) -> dict:
        request = job['request']
        path, info = self.source(request['source_url'])
        digest = self.digest(path)
        folder = Path(self.frame_dir())
        folder.mkdir(parents=True, exist_ok=True)
        frames, total = [], len(request['frames'])
        for position, index in enumerate(request['frames']):
            if cancel.is_set():
                raise Cancelled()
            self._update(job, stage=f'抽取第 {position + 1}/{total} 帧', progress_percent=round(position / total * 100))
            existing = sorted(folder.glob(f'video_frame_*_{digest}_f{index:06d}.png'))
            target = existing[0] if existing else folder / f'video_frame_{time.strftime("%H%M%S")}_{digest}_f{index:06d}.png'
            seconds = info['frame_times'][index]
            if not existing:
                media.extract_frame(path, info, index, target, self.tools, self.runner, cancel)
                prompt = (f'视频抽帧：{self._source_name(job, path)}\n'
                          f'第 {index + 1} 帧 / 共 {info["frame_count"]} 帧 · {seconds:.3f}s')
                txt = target.with_suffix('.txt')
                _write_text(txt, prompt)
                self.write_sidecar(target, prompt, txt_path=txt)
            width, height = media.png_size(target)
            frames.append({'frame': index, 'time': seconds, 'url': '/image/' + target.name, 'filename': target.name,
                           'width': width, 'height': height, 'reused': bool(existing)})
        return {'frames': frames, 'frame_count': info['frame_count']}

    def _run_scenes(self, job: dict, cancel: threading.Event) -> dict:
        path, info = self.source(job['request']['source_url'])
        self._update(job, stage='分析镜头切换')
        scenes = media.detect_scenes(path, info, self.tools, self.runner, cancel,
                                     progress=lambda share: self._update(job, progress_percent=round(share * 99)))
        return {'scenes': scenes, 'frame_count': info['frame_count'], 'threshold': contracts.SCENE_THRESHOLD}

    def _run_extract_audio(self, job: dict, cancel: threading.Event) -> dict:
        path, info = self.source(job['request']['source_url'])
        audio = info['audio']
        digest = self.digest(path)
        suffix, copy = media.audio_plan(audio['codec'])
        existing = self.audio_archive.find(f'video_audio_*_{digest}.*')
        if existing:
            return self._audio_result(existing, audio, reused=True)
        self._update(job, stage='分离音轨', progress_percent=10)
        name = self._source_name(job, path)
        with tempfile.TemporaryDirectory(prefix='video-edit-audio-') as scratch:
            target = Path(scratch) / ('track' + suffix)
            try:
                media.extract_audio(path, target, copy, self.tools, self.runner, cancel)
            except RuntimeError:
                if not copy:
                    raise
                suffix, copy = '.flac', False
                target = Path(scratch) / 'track.flac'
                media.extract_audio(path, target, copy, self.tools, self.runner, cancel)
            if cancel.is_set():
                raise Cancelled()
            self._update(job, stage='写入作品库', progress_percent=80)
            created = time.time()
            published = self.audio_archive.publish_file(
                target, name=f'video_audio_{time.strftime("%H%M%S", time.localtime(created))}_{digest}{suffix}',
                created_at=created, prompt=f'视频音轨：{name}',
                metadata=dict(source='tg-mini-app-img-gen', type='audio', engine='video_edit', title=f'{Path(name).stem} · 音轨',
                              created_at=created, audio_format=suffix.lstrip('.'), source_video=name,
                              source_codec=audio['codec'], copied=copy, duration_seconds=audio['duration_seconds'],
                              sample_rate=audio['sample_rate'], channels=audio['channels']))
        return self._audio_result(self.audio_archive.item(published['path']), audio, reused=False)

    @staticmethod
    def _audio_result(item: dict, audio: dict, *, reused: bool) -> dict:
        keys = ('path', 'name', 'title', 'url', 'mime_type', 'format', 'file_size', 'duration_seconds',
                'sample_rate', 'channels', 'peaks')
        return {**{key: item.get(key) for key in keys}, 'source_codec': audio['codec'], 'reused': reused}
