"""Automatic subtitles for a compose recipe: its own sound -> speech recognition -> draft cues.

One job at a time on its own worker, kept in memory (a restart forgets the receipt; nothing is
written to the archive: the cues go back to the canvas, where the user edits them before rendering).
Steps: ComposeService.resolve(recipe) gives the clips and timeline; plan.voice_command renders only
the clips' sound (no music, muted clips silent) as 16 kHz mono; the ASR port recognizes it with
aligned timestamps, which are therefore already output seconds; cues_from_tokens cuts them.

Ports injected by server.py:
* compose.resolve(spec) -> {clips, seconds, ...}   (ComposeService)
* asr.transcribe(path, seconds=, script=, cancelled=, progress=) -> {language, text, tokens, speech}
"""
from __future__ import annotations

import atexit
import queue
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path
import uuid

from . import contracts, plan
from .media import Cancelled, Runner, Tools

VOICE_TIMEOUT_SECONDS = 600
KEEP_FINISHED = 16
# Cue shaping. Width counts a CJK/full-width character as 1 and anything else as 0.5, so 24 is two
# lines of a vertical 720p frame at the medium size and stays far under MAX_CUE_CHARS.
MAX_CUE_WIDTH = 24
SOFT_BREAK_WIDTH = 10
MAX_CUE_SECONDS = 6.0
GAP_BREAK_SECONDS = 0.6
HOLD_SECONDS = 0.2
HARD_STOPS = '。！？.!?…；;'
SOFT_STOPS = '，,、：:'
TRAILING_DROP = '，,、：:。.；;'
_WIDE = re.compile(r'[ᄀ-ᅟ⺀-〾ぁ-㏿㐀-䶿一-鿿ꀀ-꓏'
                   r'가-힣豈-﫿︰-﹏＀-｠￠-￦]')


def _width(text: str) -> float:
    return sum(1.0 if _WIDE.match(char) else 0.5 for char in text)


def _cue_text(pieces: list[str]) -> str:
    text = re.sub(r'\s+', ' ', ''.join(pieces)).strip()
    text = text.rstrip(TRAILING_DROP + ' ').lstrip(HARD_STOPS + SOFT_STOPS + ' ')
    return text[:contracts.MAX_CUE_CHARS]


def cues_from_tokens(tokens: list[dict], total: float) -> list[dict]:
    """Draft cues [{start, end, text}] on the output timeline from aligned tokens (each carries the
    punctuation after it). A cue ends at sentence punctuation, at a comma once it is long enough,
    at a pause, or before it would grow too wide or too long. Cues are sorted, at least
    MIN_CUE_SECONDS, never overlap, hold briefly after the last word, and stay inside `total`."""
    groups, current, width = [], [], 0.0
    for token in tokens:
        text = str(token.get('text') or '')
        if not text.strip():
            continue
        start, end = float(token['start']), max(float(token['start']), float(token['end']))
        token_width = _width(text.strip())
        if current and (start - current[-1]['end'] > GAP_BREAK_SECONDS or width + token_width > MAX_CUE_WIDTH
                        or end - current[0]['start'] > MAX_CUE_SECONDS):
            groups.append(current)
            current, width = [], 0.0
        current.append({'start': start, 'end': end, 'text': text})
        width += token_width
        tail = text.rstrip()
        if tail and (tail[-1] in HARD_STOPS or (tail[-1] in SOFT_STOPS and width >= SOFT_BREAK_WIDTH)):
            groups.append(current)
            current, width = [], 0.0
    if current:
        groups.append(current)

    cues = []
    for group in groups:
        text = _cue_text([item['text'] for item in group])
        if text:
            cues.append({'start': group[0]['start'], 'end': group[-1]['end'], 'text': text})
    shortest = contracts.MIN_CUE_SECONDS
    shaped = []
    for index, cue in enumerate(cues):
        start = max(cue['start'], shaped[-1]['end'] if shaped else 0.0)
        following = cues[index + 1]['start'] if index + 1 < len(cues) else total
        end = min(max(cue['end'] + HOLD_SECONDS, start + shortest), max(following, start + shortest), total)
        if start >= total - shortest + 1e-6 or end - start < shortest - 1e-6:
            continue
        shaped.append({'start': round(start, 3), 'end': round(end, 3), 'text': cue['text']})
    return shaped[:contracts.MAX_CUES]


class TranscribeService:
    def __init__(self, *, compose, asr, tools=None, runner=None):
        self.compose = compose
        self.asr = asr
        self.tools = tools or Tools()
        self.runner = runner or Runner()
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._cancels: dict[str, threading.Event] = {}
        self._queue: queue.Queue[tuple[str, dict] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._closed = False
        atexit.register(self.close)

    def owns(self, ident) -> bool:
        with self._lock:
            return isinstance(ident, str) and ident in self._jobs

    def job(self, ident) -> dict:
        with self._lock:
            if ident not in self._jobs:
                raise FileNotFoundError('任务不存在或已过期')
            return dict(self._jobs[ident])

    def submit(self, body) -> dict:
        request = contracts.transcribe_request(body)
        self.tools.require()
        resolved = self.compose.resolve(request['recipe'])
        if not any(clip['audio'] for clip in resolved['clips']):
            raise ValueError('所有片段都已静音或没有音轨，没有可识别的原声')
        with self._lock:
            if self._closed:
                raise RuntimeError('视频剪辑服务正在停止')
            if sum(job['status'] in contracts.ACTIVE for job in self._jobs.values()) >= contracts.MAX_QUEUED_TRANSCRIBE:
                raise RuntimeError('已有自动字幕任务在进行，请稍后再试')
            now = time.time()
            ident = 'transcribe_' + uuid.uuid4().hex
            job = {'id': ident, 'task_id': ident, 'kind': 'transcribe', 'status': 'queued', 'stage': '排队中',
                   'progress_percent': 0, 'error': '', 'result': None, 'created_at': now, 'updated_at': now,
                   'seconds': resolved['seconds']}
            self._jobs[ident] = job
            self._cancels[ident] = threading.Event()
            self._prune()
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, name='video-transcribe', daemon=True)
                self._thread.start()
            self._queue.put((ident, request))
            return dict(job)

    def cancel(self, ident) -> dict:
        with self._lock:
            job = self._jobs.get(ident)
            if job is None:
                raise FileNotFoundError('任务不存在或已过期')
            if job['status'] in contracts.ACTIVE:
                self._cancels[ident].set()
                if job['status'] == 'queued':
                    job.update(status='cancelled', stage='已取消', updated_at=time.time())
            return dict(job)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for event in self._cancels.values():
                event.set()
        self._queue.put(None)

    def _prune(self) -> None:
        finished = sorted((job for job in self._jobs.values() if job['status'] not in contracts.ACTIVE),
                          key=lambda job: job['updated_at'])
        for job in finished[:-KEEP_FINISHED] if len(finished) > KEEP_FINISHED else []:
            self._jobs.pop(job['id'], None)
            self._cancels.pop(job['id'], None)

    def _update(self, ident: str, **changes) -> None:
        with self._lock:
            self._jobs[ident].update(changes, updated_at=time.time())

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            ident, request = item
            cancel = self._cancels.get(ident) or threading.Event()
            with self._lock:
                if self._jobs[ident]['status'] != 'queued':
                    continue
            if cancel.is_set():
                self._update(ident, status='cancelled', stage='已取消')
                continue
            self._update(ident, status='running', stage='提取原声', progress_percent=2)
            try:
                result = self._run(ident, request, cancel)
                self._update(ident, status='succeeded', stage='完成', progress_percent=100, result=result)
            except Cancelled:
                self._update(ident, status='cancelled', stage='已取消')
            except Exception as exc:  # the ASR port raises its own errors; a cancel shows as cancelled
                if cancel.is_set():
                    self._update(ident, status='cancelled', stage='已取消')
                else:
                    self._update(ident, status='failed', stage='失败', error=str(exc)[:400] or '自动字幕失败')

    def _run(self, ident: str, request: dict, cancel: threading.Event) -> dict:
        resolved = self.compose.resolve(request['recipe'])
        ffmpeg, _ = self.tools.require()
        scratch = Path(tempfile.mkdtemp(prefix='video-transcribe-'))
        try:
            voice = scratch / 'voice.wav'
            argv, total = plan.voice_command(ffmpeg, resolved['clips'], target=str(voice))
            self.runner.run(argv, timeout=VOICE_TIMEOUT_SECONDS, cancel=cancel)
            if cancel.is_set():
                raise Cancelled()

            def progress(ratio, stage):
                self._update(ident, stage=stage, progress_percent=max(5, min(97, round(5 + 92 * ratio))))

            self._update(ident, stage='等待语音识别', progress_percent=5)
            heard = self.asr.transcribe(voice, seconds=total, script=request['script'], cancelled=cancel,
                                        progress=progress)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        cues = cues_from_tokens(heard['tokens'], total) if heard.get('speech') else []
        return {'cues': cues, 'speech': bool(heard.get('speech')), 'language': heard.get('language', ''),
                'text': str(heard.get('text', ''))[:4000], 'seconds': total}
