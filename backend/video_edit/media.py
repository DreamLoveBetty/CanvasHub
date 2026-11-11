"""FFmpeg / ffprobe work for the video-edit domain: probe, exact frames, scene cuts, audio track.

Frame accuracy: ffprobe lists every video packet's presentation time; sorted, those are the
frames in display order (VFR included). Frame N is decoded with an accurate input seek to the
midpoint between frame N-1 and frame N, so the decoder drops N-1 and the first frame kept is N.
The canvas player seeks to the same midpoints, which keeps what the user sees and what gets
written identical. Every subprocess goes through `Runner`, which owns timeouts and cancel.
"""
from __future__ import annotations

from bisect import bisect_left
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

from .contracts import MAX_SCENES, MAX_SOURCE_SECONDS, SCENE_MIN_GAP_SECONDS, SCENE_THRESHOLD

# launchd/Finder do not read shell profiles, so look where Homebrew installs FFmpeg as well.
_TOOL_DIRS = ('/opt/homebrew/bin', '/usr/local/bin', '/usr/bin')
# Audio codecs that can be copied bit-exact into a common container, by output extension.
_COPY_CONTAINERS = {
    'aac': '.m4a', 'alac': '.m4a', 'mp3': '.mp3', 'flac': '.flac', 'opus': '.ogg', 'vorbis': '.ogg',
    'pcm_s16le': '.wav', 'pcm_s24le': '.wav', 'pcm_s32le': '.wav', 'pcm_f32le': '.wav',
}


class Cancelled(Exception):
    pass


def locate(name: str, env_key: str | None = None) -> str | None:
    candidates = [os.environ.get(env_key) if env_key else None, shutil.which(name)]
    candidates += [str(Path(directory) / name) for directory in _TOOL_DIRS]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


class Tools:
    """Executable paths, looked up lazily so installing FFmpeg needs no restart."""

    def __init__(self, ffmpeg=None, ffprobe=None):
        self._ffmpeg, self._ffprobe = ffmpeg, ffprobe

    @property
    def ffmpeg(self):
        return self._ffmpeg or locate('ffmpeg', 'FFMPEG_PATH')

    @property
    def ffprobe(self):
        return self._ffprobe or locate('ffprobe', 'FFPROBE_PATH')

    def require(self):
        ffmpeg, ffprobe = self.ffmpeg, self.ffprobe
        if not (ffmpeg and ffprobe):
            raise RuntimeError('未找到 FFmpeg / ffprobe，请先安装 FFmpeg')
        return ffmpeg, ffprobe


class Runner:
    """Run one command; a set `cancel` event terminates it. Lines go to `on_line` when given."""

    def run(self, command, *, timeout=120, cancel: threading.Event | None = None, on_line=None) -> bytes:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        chunks, errors = [], []

        def pump_stdout():
            for raw in iter(process.stdout.readline, b''):
                if on_line:
                    on_line(raw.decode('utf-8', 'replace').rstrip('\n'))
                else:
                    chunks.append(raw)

        def pump_stderr():
            errors.append(process.stderr.read())

        readers = [threading.Thread(target=pump_stdout, daemon=True), threading.Thread(target=pump_stderr, daemon=True)]
        for reader in readers:
            reader.start()
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                if time.monotonic() > deadline:
                    raise RuntimeError('FFmpeg 处理超时')
                time.sleep(0.05)
        except BaseException:
            process.kill()
            process.wait()
            raise
        finally:
            for reader in readers:
                reader.join(timeout=2)
            process.stdout.close()
            process.stderr.close()
        if process.returncode != 0:
            message = b''.join(errors).decode('utf-8', 'replace').strip().splitlines()
            raise RuntimeError('FFmpeg 处理失败：' + (message[-1][:200] if message else f'退出码 {process.returncode}'))
        return b''.join(chunks)


def _number(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and number not in (float('inf'), float('-inf')) else default


def _rate(value):
    text = str(value or '')
    if '/' in text:
        top, bottom = text.split('/', 1)
        return _number(top) / _number(bottom, 1) if _number(bottom) else 0.0
    return _number(text)


def _rotation(stream):
    for item in stream.get('side_data_list') or []:
        if 'rotation' in item:
            return int(_number(item.get('rotation'))) % 360
    return int(_number((stream.get('tags') or {}).get('rotate'))) % 360


def probe(path, tools: Tools, runner: Runner) -> dict:
    """Stream facts plus every frame's presentation time, relative to the first frame."""
    _, ffprobe = tools.require()
    raw = runner.run([ffprobe, '-v', 'error', '-show_entries',
                      'format=duration,start_time:stream=index,codec_type,codec_name,width,height,'
                      'avg_frame_rate,r_frame_rate,sample_rate,channels,duration:stream_side_data=rotation:stream_tags=rotate',
                      '-of', 'json', str(path)], timeout=30)
    data = json.loads(raw or b'{}')
    streams = data.get('streams') or []
    video = next((s for s in streams if s.get('codec_type') == 'video'), None)
    if not video:
        raise ValueError('无法读取视频画面')
    audio = next((s for s in streams if s.get('codec_type') == 'audio'), None)
    duration = _number((data.get('format') or {}).get('duration')) or _number(video.get('duration'))
    if duration > MAX_SOURCE_SECONDS:
        raise ValueError(f'视频超过 {MAX_SOURCE_SECONDS // 60} 分钟，暂不支持剪辑')
    start = _number((data.get('format') or {}).get('start_time'))
    lines = runner.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'packet=pts_time,flags',
                        '-of', 'csv=p=0', str(path)], timeout=60).decode('utf-8', 'replace').splitlines()
    times = []
    for line in lines:
        pts, _, flags = line.partition(',')
        if 'D' in flags or pts in ('', 'N/A'):
            continue
        value = _number(pts, None)
        if value is not None and value >= start - 1e-6:
            times.append(value)
    times.sort()
    if not times:
        raise ValueError('无法读取视频帧')
    first = times[0]
    width, height = int(_number(video.get('width'))), int(_number(video.get('height')))
    rotation = _rotation(video)
    if rotation in (90, 270):
        width, height = height, width
    return {
        'width': width, 'height': height, 'duration_seconds': round(duration or (times[-1] - first), 3),
        'fps': round(_rate(video.get('avg_frame_rate')) or _rate(video.get('r_frame_rate')), 3),
        'frame_count': len(times), 'codec': str(video.get('codec_name') or ''),
        'first_pts': first, 'pts': times,
        'frame_times': [round(value - first, 6) for value in times],
        'audio': ({'codec': str(audio.get('codec_name') or ''), 'channels': int(_number(audio.get('channels'))),
                   'sample_rate': int(_number(audio.get('sample_rate'))),
                   'duration_seconds': round(_number(audio.get('duration')) or duration, 3)} if audio else None),
    }


def _seek_args(info: dict, index: int) -> list[str]:
    if index <= 0:
        return []
    pts = info['pts']
    return ['-seek_timestamp', '1', '-ss', f'{(pts[index - 1] + pts[index]) / 2:.6f}']


def extract_frame(path, info: dict, index: int, target: Path, tools: Tools, runner: Runner, cancel=None) -> None:
    """Write frame `index` at full resolution as PNG (atomic: temp name, then rename)."""
    ffmpeg, _ = tools.require()
    pending = target.with_name('.' + target.name + '.writing')
    try:
        runner.run([ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', *_seek_args(info, index), '-i', str(path),
                    '-map', '0:v:0', '-frames:v', '1', '-f', 'image2', '-c:v', 'png', '-y', str(pending)],
                   timeout=60, cancel=cancel)
        if not pending.is_file() or pending.stat().st_size == 0:
            raise RuntimeError('没有解码出该帧')
        os.replace(pending, target)
    finally:
        pending.unlink(missing_ok=True)


def preview_frame(path, info: dict, index: int, width: int, tools: Tools, runner: Runner) -> bytes:
    ffmpeg, _ = tools.require()
    data = runner.run([ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', *_seek_args(info, index), '-i', str(path),
                       '-map', '0:v:0', '-frames:v', '1', '-vf', f'scale={int(width)}:-2', '-f', 'image2pipe',
                       '-c:v', 'mjpeg', '-q:v', '4', '-'], timeout=30)
    if not data:
        raise RuntimeError('没有解码出该帧')
    return data


def png_size(path: Path) -> tuple[int, int]:
    with open(path, 'rb') as stream:
        head = stream.read(24)
    if head[:8] != b'\x89PNG\r\n\x1a\n':
        return 0, 0
    return int.from_bytes(head[16:20], 'big'), int.from_bytes(head[20:24], 'big')


def nearest_frame(frame_times: list[float], seconds: float) -> int:
    index = bisect_left(frame_times, seconds)
    if index <= 0:
        return 0
    if index >= len(frame_times):
        return len(frame_times) - 1
    return index if frame_times[index] - seconds < seconds - frame_times[index - 1] else index - 1


def pick_scenes(scored: list[tuple[float, float]], frame_times: list[float], *, threshold=SCENE_THRESHOLD,
                min_gap=SCENE_MIN_GAP_SECONDS, limit=MAX_SCENES) -> list[dict]:
    """Strongest cuts first, at least `min_gap` apart, returned in time order."""
    accepted = []
    for seconds, score in sorted((item for item in scored if item[1] >= threshold), key=lambda item: -item[1]):
        if seconds <= 0 or any(abs(seconds - other) < min_gap for other, _ in accepted):
            continue
        accepted.append((seconds, score))
        if len(accepted) >= limit:
            break
    scenes = []
    for seconds, score in sorted(accepted):
        frame = nearest_frame(frame_times, seconds)
        scenes.append({'frame': frame, 'time': frame_times[frame], 'score': round(score, 2)})
    return scenes


def detect_scenes(path, info: dict, tools: Tools, runner: Runner, cancel=None, progress=None) -> list[dict]:
    """Score every frame change with `scdet` on a 270p copy; the user confirms the candidates."""
    ffmpeg, _ = tools.require()
    scored, current = [], [None]
    duration = max(info.get('duration_seconds') or 0, 0.001)

    def on_line(line):
        if line.startswith('frame:'):
            for part in line.split():
                if part.startswith('pts_time:'):
                    current[0] = _number(part[len('pts_time:'):], None)
                    if progress and current[0] is not None:
                        progress(min(current[0] / duration, 1.0))
        elif line.startswith('lavfi.scd.score=') and current[0] is not None:
            scored.append((current[0], _number(line.split('=', 1)[1])))

    runner.run([ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-i', str(path), '-map', '0:v:0', '-an',
                '-vf', 'scale=-2:270,scdet=threshold=0,metadata=print:file=-', '-f', 'null', '-'],
               timeout=900, cancel=cancel, on_line=on_line)
    return pick_scenes(scored, info['frame_times'])


def audio_plan(codec: str) -> tuple[str, bool]:
    """(extension, copy) for the first audio stream: copy when a common container holds it."""
    suffix = _COPY_CONTAINERS.get(str(codec or '').lower())
    return (suffix, True) if suffix else ('.flac', False)


def extract_audio(path, target: Path, copy: bool, tools: Tools, runner: Runner, cancel=None) -> None:
    ffmpeg, _ = tools.require()
    codec = ['-c:a', 'copy'] if copy else ['-c:a', 'flac']
    container = ['-movflags', '+faststart'] if target.suffix == '.m4a' else []
    runner.run([ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-i', str(path), '-map', '0:a:0', '-vn', '-sn',
                '-dn', *codec, *container, '-y', str(target)], timeout=600, cancel=cancel)
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError('音轨导出为空')


def probe_audio(path, tools: Tools, runner: Runner) -> dict:
    """First audio stream of a music file: codec and duration (seconds)."""
    _, ffprobe = tools.require()
    raw = runner.run([ffprobe, '-v', 'error', '-show_entries', 'format=duration:stream=codec_type,codec_name,duration',
                      '-of', 'json', str(path)], timeout=30)
    data = json.loads(raw or b'{}')
    audio = next((s for s in data.get('streams') or [] if s.get('codec_type') == 'audio'), None)
    if not audio:
        raise ValueError('配乐文件没有音轨')
    duration = _number(audio.get('duration')) or _number((data.get('format') or {}).get('duration'))
    if duration <= 0:
        raise ValueError('无法读取配乐时长')
    return {'codec': str(audio.get('codec_name') or ''), 'duration_seconds': round(duration, 3)}


def filmstrip_frames(frame_count: int, tiles: int) -> list[int]:
    """Frame index shown by each tile: the middle frame of each equal share of the clip."""
    return [min(frame_count - 1, int((index + 0.5) * frame_count / tiles)) for index in range(tiles)]


def filmstrip(path, info: dict, tiles: int, height: int, tools: Tools, runner: Runner) -> bytes:
    """One JPEG row of `tiles` thumbnails picked by frame index (VFR-safe), each `height` px tall."""
    ffmpeg, _ = tools.require()
    tiles = max(1, min(tiles, info['frame_count']))
    picks = '+'.join(f'eq(n\\,{index})' for index in sorted(set(filmstrip_frames(info['frame_count'], tiles))))
    data = runner.run([ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-i', str(path), '-map', '0:v:0', '-an',
                       '-vf', f"select='{picks}',scale=-2:{int(height)},tile={tiles}x1", '-fps_mode', 'passthrough',
                       '-frames:v', '1', '-f', 'image2pipe', '-c:v', 'mjpeg', '-q:v', '5', '-'], timeout=180)
    if not data:
        raise RuntimeError('没有解码出缩略图')
    return data
