"""Compose service: clips + optional music -> one MP4 in today's archive folder.

One render at a time on its own worker (a long render never blocks frame or scene jobs), lowered
CPU priority, durable receipts (storage.ComposeStore). The output is idempotent per recipe: the
name carries a hash of the source contents and every setting, so the same recipe reuses the file.

Beside each output: `<name>.json` (the recipe, enough to reopen and re-render), `<name>.txt`, the
Obsidian `.md` note and, with subtitles, `<name>.srt`. Ports injected by server.py:
* sources: VideoEditService (source(url) -> (path, probe), locate(url) -> path, digest(path) -> sha12)
* audio_resolver.resolve(url=, asset_id=) -> Path    (sources.AudioSourceResolver)
* output_dir() -> Path                                 (today's archive folder; served as /video/<name>)
* write_sidecar(path, prompt, txt_path=)
* font_dir: the flat font catalog subtitles draw with (subtitles.py)
"""
from __future__ import annotations

import atexit
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import tempfile
import threading
import time

from . import contracts, media, plan, subtitles
from .media import Cancelled, Runner, Tools
from .storage import ACTIVE as STORE_ACTIVE, ComposeStore

RENDER_TIMEOUT_SECONDS = 3600
MAX_RECIPE_BYTES = 256 * 1024
TRANSITION_LABELS = {'none': '', 'fade': '叠化', 'fadeblack': '黑场', 'wipeleft': '擦除'}
OUTPUT_NAME = re.compile(r'video_compose_[\w.-]+\.mp4')


def _write_text(path: Path, text: str) -> None:
    pending = path.with_name('.' + path.name + '.writing')
    pending.write_text(text, encoding='utf-8')
    pending.replace(path)


class ComposeService:
    def __init__(self, *, store: ComposeStore, sources, audio_resolver, output_dir, write_sidecar,
                 font_dir=None, tools=None, runner=None, nice=True):
        self.store = store
        self.sources = sources
        self.audio_resolver = audio_resolver
        self.output_dir = output_dir
        self.write_sidecar = write_sidecar
        self.font_dir = font_dir
        self.tools = tools or Tools()
        self.runner = runner or Runner()
        self._nice = ['nice', '-n', '10'] if nice and shutil.which('nice') else []
        self._lock = threading.Lock()
        self._cancels: dict[str, threading.Event] = {}
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._closed = False
        self.store.recover()
        atexit.register(self.close)

    # ----- reads -----------------------------------------------------------------------------------
    @staticmethod
    def limits() -> dict:
        return {'max_clips': contracts.MAX_CLIPS, 'max_output_seconds': contracts.MAX_OUTPUT_SECONDS,
                'min_clip_seconds': contracts.MIN_CLIP_SECONDS, 'aspects': list(contracts.ASPECTS),
                'resolutions': list(contracts.RESOLUTIONS), 'frame_rates': list(contracts.FRAME_RATES),
                'fits': list(contracts.FITS), 'encoders': list(contracts.ENCODERS), 'defaults': contracts.OUTPUT_DEFAULTS,
                'max_cues': contracts.MAX_CUES, 'max_cue_chars': contracts.MAX_CUE_CHARS,
                'min_cue_seconds': contracts.MIN_CUE_SECONDS}

    def subtitle_fonts(self) -> dict:
        return {'fonts': subtitles.catalog(self.font_dir), 'default': subtitles.DEFAULT_FONTS[0]}

    def owns(self, ident) -> bool:
        return self.store.has(ident)

    def job(self, ident) -> dict:
        return self._public(self.store.get(ident))

    @staticmethod
    def _public(job: dict) -> dict:
        return dict(job)

    # ----- validation ------------------------------------------------------------------------------
    def resolve(self, spec: dict) -> dict:
        """Probe every source and check ranges, durations and limits; returns render inputs.
        Public for automatic subtitles (transcribe.py), which needs the same clips and timeline."""
        clips = []
        for position, clip in enumerate(spec['clips'], 1):
            path, info = self.sources.source(clip['source_url'])
            try:
                window = plan.clip_window(info, clip['start_frame'], clip['end_frame'])
            except ValueError as exc:
                raise ValueError(f'第 {position} 段：{exc}') from None
            speed = clip.get('speed', 1.0)
            if plan.output_seconds(window['seconds'], speed) < contracts.MIN_CLIP_SECONDS - 1e-6:
                raise ValueError(f'第 {position} 段变速后不足 {contracts.MIN_CLIP_SECONDS:g} 秒，请放宽裁切或降低倍速')
            clips.append({'path': path, 'info': info, 'seek': window['seek'], 'frames': window['frames'],
                          'seconds': window['seconds'], 'start_frame': window['start_frame'],
                          'end_frame': window['end_frame'], 'audio': bool(clip['audio'] and info['audio']),
                          'has_audio': bool(info['audio']), 'speed': speed,
                          'transition': clip.get('transition') or dict(contracts.NO_TRANSITION)})
        total = plan.total_seconds(clips)
        if total > contracts.MAX_OUTPUT_SECONDS + 1e-6:
            raise ValueError(f'成片超过 {contracts.MAX_OUTPUT_SECONDS // 60} 分钟（{total:.1f} 秒），请裁短或减少片段')
        music = None
        if spec['music']:
            source = spec['music']
            path = self.audio_resolver.resolve(url=source['source_url'], asset_id=source['asset_id'])
            facts = media.probe_audio(path, self.tools, self.runner)
            music = {**source, 'path': path, 'duration': facts['duration_seconds']}
        first = clips[0]['info']
        width, height = plan.output_size(spec['output']['aspect'], spec['output']['resolution'],
                                         first['width'], first['height'])
        return {'clips': clips, 'music': music, 'width': width, 'height': height, 'seconds': round(total, 3),
                'subtitles': self._subtitles(spec.get('subtitles'), total, width, height)}

    def _subtitles(self, spec: dict | None, total: float, width: int, height: int) -> dict | None:
        """Cues on this render's timeline (ends clipped to the total) laid out once, so a cue that does not
        fit fails before the job is queued."""
        if not spec:
            return None
        cues = []
        for position, cue in enumerate(spec['cues'], 1):
            if cue['start'] >= total - contracts.MIN_CUE_SECONDS + 1e-6:
                raise ValueError(f'第 {position} 条字幕在成片结束之后（成片 {total:.2f} 秒），请调整字幕时间')
            cues.append(dict(cue, end=round(min(cue['end'], total), 3)))
        font = subtitles.font_path(self.font_dir, spec['style']['font'])
        layout = subtitles.Layout(cues, spec['style'], width=width, height=height, font_file=font)
        return {'cues': cues, 'style': spec['style'], 'font': font, 'layout': layout}

    def _recipe_key(self, spec: dict, resolved: dict) -> str:
        material = {
            # Speed and transition join the key only when set, so phase-2 recipes keep their file names.
            'clips': [{'digest': self.sources.digest(clip['path']), 'start': clip['start_frame'], 'end': clip['end_frame'],
                       'audio': clip['audio'],
                       **({'speed': clip['speed']} if clip['speed'] != 1 else {}),
                       **({'transition': clip['transition']} if clip['transition']['type'] != 'none' else {})}
                      for clip in resolved['clips']],
            'music': ({'digest': self.sources.digest(resolved['music']['path'])} | {
                key: resolved['music'][key] for key in ('volume', 'fade_in', 'fade_out')} if resolved['music'] else None),
            'clip_volume': spec['clip_volume'], 'output': spec['output'],
        }
        if resolved['subtitles']:  # only when set, so earlier recipes keep their file names
            sub = resolved['subtitles']
            material['subtitles'] = {'cues': sub['cues'], 'style': sub['style'], 'font': self.sources.digest(sub['font'])}
        return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()[:12]

    def _summary(self, resolved: dict) -> dict:
        return {'clip_count': len(resolved['clips']), 'duration_seconds': resolved['seconds'],
                'width': resolved['width'], 'height': resolved['height'],
                'clips': [{'start_frame': clip['start_frame'], 'end_frame': clip['end_frame'], 'frames': clip['frames'],
                           'seconds': clip['seconds'], 'has_audio': clip['has_audio'], 'audio': clip['audio'],
                           'speed': clip['speed'], 'output_seconds': plan.output_seconds(clip['seconds'], clip['speed'])}
                          for clip in resolved['clips']],
                'transitions': plan.transition_cuts(resolved['clips']),
                'subtitle_count': len(resolved['subtitles']['cues']) if resolved['subtitles'] else 0,
                'music_seconds': resolved['music']['duration'] if resolved['music'] else 0}

    def recipe(self, url: str) -> dict:
        """The `.json` recipe beside a rendered output, re-validated, so the canvas can rebuild the node."""
        path = self.sources.locate(url)
        if not OUTPUT_NAME.fullmatch(path.name):
            raise ValueError('这段视频不是合成成片，没有可重开的配方')
        sidecar = path.with_suffix('.json')
        if not sidecar.is_file():
            raise FileNotFoundError('找不到这段成片的配方文件（.json）')
        if sidecar.stat().st_size > MAX_RECIPE_BYTES:
            raise ValueError('配方文件过大')
        data = json.loads(sidecar.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('kind') != 'video_compose':
            raise ValueError('配方格式无效')
        spec = contracts.compose_request(data.get('spec'))
        summary = data.get('summary') if isinstance(data.get('summary'), dict) else {}
        number = lambda key: summary.get(key) if isinstance(summary.get(key), (int, float)) and not isinstance(summary.get(key), bool) else 0
        return {'spec': spec, 'result': {'url': '/video/' + path.name, 'filename': path.name, 'file_size': path.stat().st_size,
                                         'duration_seconds': number('duration_seconds'), 'width': number('width'),
                                         'height': number('height'), 'fps': spec['output']['fps']}}

    def check(self, body) -> dict:
        """Validate a recipe without rendering (the workbench shows the real total and size)."""
        spec = contracts.compose_request(body)
        self.tools.require()
        return self._summary(self.resolve(spec))

    # ----- jobs --------------------------------------------------------------------------------------
    def submit(self, body) -> dict:
        spec = contracts.compose_request(body)
        self.tools.require()
        resolved = self.resolve(spec)
        with self._lock:
            if self._closed:
                raise RuntimeError('视频合成服务正在停止')
            if len(self.store.active()) >= contracts.MAX_QUEUED_COMPOSE:
                raise RuntimeError('合成任务排队已满，请稍后再试')
            job = self.store.create(spec, self._summary(resolved))
            self._cancels[job['id']] = threading.Event()
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, name='video-compose', daemon=True)
                self._thread.start()
            self._queue.put(job['id'])
        return self._public(job)

    def cancel(self, ident) -> dict:
        job = self.store.get(ident)
        if job['status'] in STORE_ACTIVE:
            event = self._cancels.get(job['id'])
            if event:
                event.set()
            if job['status'] == 'queued':
                job = self.store.update(job['id'], status='cancelled', stage='已取消')
        return self._public(job)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for event in self._cancels.values():
                event.set()
        self._queue.put(None)

    def _loop(self) -> None:
        while True:
            ident = self._queue.get()
            if ident is None:
                return
            try:
                job = self.store.get(ident)
            except FileNotFoundError:
                continue
            cancel = self._cancels.get(ident) or threading.Event()
            if job['status'] != 'queued':
                continue
            if cancel.is_set():
                self.store.update(ident, status='cancelled', stage='已取消')
                continue
            self.store.update(ident, status='running', stage='准备素材', progress_percent=0)
            try:
                result = self._render(ident, job['spec'], cancel)
                self.store.update(ident, status='succeeded', stage='完成', progress_percent=100, result=result)
            except Cancelled:
                self.store.update(ident, status='cancelled', stage='已取消')
            except (ValueError, RuntimeError, FileNotFoundError) as exc:
                self.store.update(ident, status='failed', stage='失败', error=str(exc))
            except OSError:
                self.store.update(ident, status='failed', stage='失败', error='视频合成读写失败')
            finally:
                self._cancels.pop(ident, None)

    # ----- render -----------------------------------------------------------------------------------
    def _render(self, ident: str, spec: dict, cancel: threading.Event) -> dict:
        resolved = self.resolve(spec)
        key = self._recipe_key(spec, resolved)
        folder = Path(self.output_dir())
        folder.mkdir(parents=True, exist_ok=True)
        existing = sorted(folder.glob(f'video_compose_*_{key}.mp4'))
        if existing:
            return self._result(existing[0], spec, resolved, reused=True)
        target = folder / f'video_compose_{time.strftime("%H%M%S")}_{key}.mp4'
        pending = target.with_name('.' + target.stem + '.writing.mp4')
        ffmpeg, _ = self.tools.require()
        scratch = Path(tempfile.mkdtemp(prefix='video-compose-'))
        try:
            overlays = resolved['subtitles']['layout'].render(scratch) if resolved['subtitles'] else []
            argv, total = plan.command(ffmpeg, resolved['clips'], resolved['music'], spec['output'],
                                       width=resolved['width'], height=resolved['height'],
                                       clip_volume=spec['clip_volume'], target=str(pending), overlays=overlays)
            self._run(ident, argv, total, pending, target, cancel)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        self._write_sidecars(target, spec, resolved)
        return self._result(target, spec, resolved, reused=False)

    def _run(self, ident: str, argv: list[str], total: float, pending: Path, target: Path, cancel: threading.Event) -> None:
        last = [0.0]

        def on_line(line):
            share = plan.progress_share(line, total)
            if share is not None and share - last[0] >= 0.01:
                last[0] = share
                self.store.update(ident, stage='合成中', progress_percent=min(98, round(share * 100)))

        self.store.update(ident, stage='合成中', progress_percent=1)
        try:
            self.runner.run([*self._nice, *argv], timeout=RENDER_TIMEOUT_SECONDS, cancel=cancel, on_line=on_line)
            if cancel.is_set():
                raise Cancelled()
            if not pending.is_file() or pending.stat().st_size == 0:
                raise RuntimeError('合成结果为空')
            self.store.update(ident, stage='写入作品库', progress_percent=99)
            os.replace(pending, target)
        finally:
            pending.unlink(missing_ok=True)

    def _write_sidecars(self, target: Path, spec: dict, resolved: dict) -> None:
        recipe = {'version': 1, 'kind': 'video_compose', 'created_at': time.time(), 'spec': spec,
                  'summary': self._summary(resolved)}
        _write_text(target.with_suffix('.json'), json.dumps(recipe, ensure_ascii=False, indent=2))
        output = spec['output']
        lines = [f'视频合成：{spec["title"] or target.stem}',
                 f'{len(resolved["clips"])} 段 · {resolved["seconds"]:.2f}s · {resolved["width"]}×{resolved["height"]}'
                 f' · {output["fps"]}fps · {output["fit"]} · {output["encoder"]}']
        cuts = plan.transition_cuts(resolved['clips'])
        for position, clip in enumerate(spec['clips'], 1):
            window = resolved['clips'][position - 1]
            speed = f' {window["speed"]:g}×' if window['speed'] != 1 else ''
            cut = cuts[position - 1] if position <= len(cuts) else 0
            joined = f' → {TRANSITION_LABELS[window["transition"]["type"]]} {cut:g}s' if cut else ''
            lines.append(f'{position}. {clip["source_name"] or Path(window["path"]).name} 帧 {window["start_frame"] + 1}–'
                         f'{window["end_frame"] + 1}（{window["seconds"]:.2f}s）{speed}{"" if window["audio"] else " 静音"}{joined}')
        if spec['music']:
            lines.append(f'配乐：{spec["music"]["source_name"] or "音频"} · 音量 {spec["music"]["volume"]:g}')
        sub = resolved['subtitles']
        if sub:
            lines.append(f'字幕：{len(sub["cues"])} 条 · {sub["font"].stem}（另存 {target.with_suffix(".srt").name}）')
            _write_text(target.with_suffix('.srt'), subtitles.srt(sub['cues']))
        txt = target.with_suffix('.txt')
        _write_text(txt, '\n'.join(lines))
        self.write_sidecar(target, '\n'.join(lines), txt_path=txt)

    def _result(self, target: Path, spec: dict, resolved: dict, *, reused: bool) -> dict:
        return {'url': '/video/' + target.name, 'filename': target.name, 'file_size': target.stat().st_size,
                'duration_seconds': resolved['seconds'], 'width': resolved['width'], 'height': resolved['height'],
                'fps': spec['output']['fps'], 'has_audio': True, 'reused': reused}
