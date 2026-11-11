"""Public request contracts for the video-edit domain (frames, scenes, audio separation).

Requests never carry file paths: a source is one of the same-origin media URLs the canvas
already plays (see sources.py), and everything else is a bounded number or a short list.
"""
from __future__ import annotations

import math
import re

from ..asr.contracts import SCRIPTS as ASR_SCRIPTS

MAX_SOURCE_SECONDS = 600
MAX_FRAMES_PER_JOB = 20
MAX_QUEUED_JOBS = 8
MAX_KEPT_JOBS = 64
JOB_TTL_SECONDS = 3600
MAX_SCENES = 40
SCENE_THRESHOLD = 6.0
SCENE_MIN_GAP_SECONDS = 0.5
PREVIEW_WIDTHS = (160, 240, 320)
FILMSTRIP_TILES = (8, 16, 24, 40)
FILMSTRIP_HEIGHT = 96
KINDS = ('frames', 'scenes', 'extract_audio')
ACTIVE = frozenset({'queued', 'running'})
FINISHED = frozenset({'succeeded', 'failed', 'cancelled'})


def source_url(value) -> str:
    text = str(value or '').strip()
    if not text or len(text) > 2048:
        raise ValueError('缺少视频来源')
    return text


def frame_index(value, frame_count: int) -> int:
    if isinstance(value, bool):
        raise ValueError('帧序号无效')
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError('帧序号无效') from None
    if not math.isfinite(number) or number != int(number):
        raise ValueError('帧序号无效')
    index = int(number)
    if not 0 <= index < frame_count:
        raise ValueError(f'帧序号超出范围（共 {frame_count} 帧）')
    return index


def frame_list(values, frame_count: int) -> list[int]:
    """Unique, ordered frame indices; `-1` is accepted as "the last frame"."""
    if not isinstance(values, list) or not values:
        raise ValueError('请至少选择一帧')
    resolved = []
    for value in values:
        index = frame_count - 1 if value == -1 else frame_index(value, frame_count)
        if index not in resolved:
            resolved.append(index)
    if len(resolved) > MAX_FRAMES_PER_JOB:
        raise ValueError(f'单次最多抽取 {MAX_FRAMES_PER_JOB} 帧')
    return sorted(resolved)


def preview_width(value) -> int:
    try:
        width = int(value or PREVIEW_WIDTHS[-1])
    except (TypeError, ValueError):
        width = PREVIEW_WIDTHS[-1]
    return min(PREVIEW_WIDTHS, key=lambda allowed: abs(allowed - width))


def filmstrip_tiles(value) -> int:
    try:
        tiles = int(value or FILMSTRIP_TILES[-1])
    except (TypeError, ValueError):
        tiles = FILMSTRIP_TILES[-1]
    return min(FILMSTRIP_TILES, key=lambda allowed: abs(allowed - tiles))


def submit_request(body) -> dict:
    if not isinstance(body, dict):
        raise ValueError('请求必须为对象')
    kind = str(body.get('kind') or '').strip()
    if kind not in KINDS:
        raise ValueError('未知视频剪辑任务')
    request = {'kind': kind, 'source_url': source_url(body.get('source_url'))}
    if kind == 'frames':
        frames = body.get('frames')
        if not isinstance(frames, list):
            raise ValueError('请至少选择一帧')
        request['frames'] = frames
    name = str(body.get('source_name') or '').strip()[:160]
    if name:
        request['source_name'] = name
    return request


# ----- compose (phase 2) -------------------------------------------------------------------------
MAX_CLIPS = 20
MAX_OUTPUT_SECONDS = 180
MIN_CLIP_SECONDS = 0.5
MAX_QUEUED_COMPOSE = 4
ASPECTS = ('source', '16:9', '9:16', '1:1', '4:5')
RESOLUTIONS = (720, 1080)
FRAME_RATES = (24, 30)
FITS = ('crop', 'pad', 'blur')
ENCODERS = ('quality', 'fast')
OUTPUT_DEFAULTS = {'aspect': 'source', 'resolution': 1080, 'fps': 30, 'fit': 'crop', 'encoder': 'quality'}
# Phase 3: per-clip speed and the transition into the next clip (xfade names).
SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
TRANSITIONS = ('none', 'fade', 'fadeblack', 'wipeleft')
TRANSITION_SECONDS = (0.5, 1.0)
NO_TRANSITION = {'type': 'none', 'duration': 0.5}
# Phase 3b: burned-in subtitles on the output timeline (seconds), drawn by subtitles.py.
MAX_CUES = 100
MAX_CUE_CHARS = 80
MIN_CUE_SECONDS = 0.3
SUBTITLE_SIZES = ('small', 'medium', 'large')
SUBTITLE_POSITIONS = ('bottom', 'top')
SUBTITLE_LOOKS = ('outline', 'box')
SUBTITLE_DEFAULTS = {'size': 'medium', 'position': 'bottom', 'look': 'outline', 'font': ''}
FONT_NAME = re.compile(r'[^/\\\x00:]{1,160}\.(ttf|otf|ttc)', re.IGNORECASE)
AUDIO_ASSET_PATTERN = r'[a-f0-9]{64}\.(wav|flac|mp3|m4a|ogg|aac|webm|opus)'
COMPOSE_FINISHED = FINISHED | {'interrupted'}


def _bounded(value, low: float, high: float, default: float, label: str) -> float:
    if value is None or value == '':
        return default
    if isinstance(value, bool):
        raise ValueError(f'{label}无效')
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{label}无效') from None
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f'{label}须在 {low:g}–{high:g} 之间')
    return round(number, 3)


def _choice(value, allowed, default, label):
    if value is None or value == '':
        return default
    if value not in allowed:
        raise ValueError(f'{label}无效')
    return value


def _whole(value, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f'{label}无效')
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{label}无效') from None
    if not math.isfinite(number) or number != int(number) or number < -1:
        raise ValueError(f'{label}无效')
    return int(number)


def _name(value) -> str:
    return str(value or '').strip()[:160]


def _number_choice(value, allowed, default, label):
    if value is None or value == '':
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) not in allowed:
        raise ValueError(f'{label}无效')
    return float(value)


def _transition(value, label: str) -> dict:
    if value in (None, '', {}):
        return dict(NO_TRANSITION)
    if not isinstance(value, dict):
        raise ValueError(f'{label}无效')
    kind = _choice(value.get('type'), TRANSITIONS, 'none', label)
    duration = _number_choice(value.get('duration'), TRANSITION_SECONDS, NO_TRANSITION['duration'], label + '时长')
    return {'type': kind, 'duration': duration}


def _seconds(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{label}无效')
    if not 0 <= value <= MAX_OUTPUT_SECONDS:
        raise ValueError(f'{label}超出成片长度')
    return round(float(value), 3)


def subtitles_request(value) -> dict | None:
    """Ordered, non-overlapping cues on the output timeline plus one style; None when there are no cues."""
    if value in (None, {}):
        return None
    if not isinstance(value, dict):
        raise ValueError('字幕格式无效')
    cues = value.get('cues')
    if cues in (None, []):
        return None
    if not isinstance(cues, list):
        raise ValueError('字幕格式无效')
    if len(cues) > MAX_CUES:
        raise ValueError(f'最多 {MAX_CUES} 条字幕')
    parsed = []
    for position, cue in enumerate(cues, 1):
        if not isinstance(cue, dict):
            raise ValueError(f'第 {position} 条字幕格式无效')
        text = '\n'.join(line.strip() for line in str(cue.get('text') or '').replace('\r', '').split('\n')).strip()
        if not text:
            raise ValueError(f'第 {position} 条字幕没有文字')
        if len(text) > MAX_CUE_CHARS:
            raise ValueError(f'第 {position} 条字幕超过 {MAX_CUE_CHARS} 字')
        start = _seconds(cue.get('start'), f'第 {position} 条字幕开始时间')
        end = _seconds(cue.get('end'), f'第 {position} 条字幕结束时间')
        if end - start < MIN_CUE_SECONDS - 1e-9:
            raise ValueError(f'第 {position} 条字幕至少 {MIN_CUE_SECONDS:g} 秒')
        parsed.append({'start': start, 'end': end, 'text': text})
    parsed.sort(key=lambda cue: cue['start'])
    for before, after in zip(parsed, parsed[1:]):
        if after['start'] < before['end'] - 1e-9:
            raise ValueError(f'字幕在 {after["start"]:g} 秒处重叠，请错开时间')
    style = value.get('style') or {}
    if not isinstance(style, dict):
        raise ValueError('字幕样式格式无效')
    font = str(style.get('font') or '').strip()
    if font and not FONT_NAME.fullmatch(font):
        raise ValueError('字幕字体无效')
    return {'cues': parsed, 'style': {
        'size': _choice(style.get('size'), SUBTITLE_SIZES, SUBTITLE_DEFAULTS['size'], '字幕大小'),
        'position': _choice(style.get('position'), SUBTITLE_POSITIONS, SUBTITLE_DEFAULTS['position'], '字幕位置'),
        'look': _choice(style.get('look'), SUBTITLE_LOOKS, SUBTITLE_DEFAULTS['look'], '字幕样式'),
        'font': font}}


def compose_request(body) -> dict:
    """Structural checks only; frame ranges and durations are checked against each probe by the service."""
    if not isinstance(body, dict):
        raise ValueError('请求必须为对象')
    clips = body.get('clips')
    if not isinstance(clips, list) or not clips:
        raise ValueError('请至少连接一段视频')
    if len(clips) > MAX_CLIPS:
        raise ValueError(f'最多合成 {MAX_CLIPS} 段视频')
    parsed = []
    for position, clip in enumerate(clips, 1):
        if not isinstance(clip, dict):
            raise ValueError(f'第 {position} 段格式无效')
        start = _whole(clip.get('start_frame', 0), f'第 {position} 段入点')
        end = _whole(clip.get('end_frame', -1), f'第 {position} 段出点')
        if start < 0:
            raise ValueError(f'第 {position} 段入点无效')
        parsed.append({'source_url': source_url(clip.get('source_url')), 'source_name': _name(clip.get('source_name')),
                       'start_frame': start, 'end_frame': end, 'audio': clip.get('audio', True) is not False,
                       'speed': _number_choice(clip.get('speed'), SPEEDS, 1.0, f'第 {position} 段变速'),
                       # The transition leads into the next clip; the last clip has none.
                       'transition': (_transition(clip.get('transition'), f'第 {position} 段转场') if position < len(clips)
                                      else dict(NO_TRANSITION))})
    music = body.get('music')
    if music in (None, {}):
        music = None
    elif isinstance(music, dict):
        asset = str(music.get('asset_id') or '').strip()
        url = str(music.get('source_url') or '').strip()
        if bool(asset) == bool(url):
            raise ValueError('配乐须是作品库或已上传的音频')
        if asset and not re.fullmatch(AUDIO_ASSET_PATTERN, asset):
            raise ValueError('配乐音频无效')
        music = {'source_url': source_url(url) if url else '', 'asset_id': asset, 'source_name': _name(music.get('source_name')),
                 'volume': _bounded(music.get('volume'), 0, 2, 0.8, '配乐音量'),
                 'fade_in': _bounded(music.get('fade_in'), 0, 10, 0, '淡入秒数'),
                 'fade_out': _bounded(music.get('fade_out'), 0, 10, 1.5, '淡出秒数')}
    else:
        raise ValueError('配乐格式无效')
    output = body.get('output') or {}
    if not isinstance(output, dict):
        raise ValueError('输出设置格式无效')
    resolution = output.get('resolution')
    fps = output.get('fps')
    return {
        'clips': parsed,
        'clip_volume': _bounded(body.get('clip_volume'), 0, 2, 1, '原声音量'),
        'music': music,
        'output': {
            'aspect': _choice(output.get('aspect'), ASPECTS, OUTPUT_DEFAULTS['aspect'], '输出比例'),
            'resolution': _choice(int(resolution) if isinstance(resolution, (int, float)) and not isinstance(resolution, bool)
                                  else resolution, RESOLUTIONS, OUTPUT_DEFAULTS['resolution'], '输出分辨率'),
            'fps': _choice(int(fps) if isinstance(fps, (int, float)) and not isinstance(fps, bool) else fps,
                           FRAME_RATES, OUTPUT_DEFAULTS['fps'], '输出帧率'),
            'fit': _choice(output.get('fit'), FITS, OUTPUT_DEFAULTS['fit'], '填充方式'),
            'encoder': _choice(output.get('encoder'), ENCODERS, OUTPUT_DEFAULTS['encoder'], '编码方式'),
        },
        'subtitles': subtitles_request(body.get('subtitles')),
        'title': _name(body.get('title'))[:80],
    }


# ----- automatic subtitles ---------------------------------------------------------------------------
MAX_QUEUED_TRANSCRIBE = 2


def transcribe_request(body) -> dict:
    """{recipe, script}: the compose recipe whose own sound is recognized (its subtitles are ignored, a
    stale cue must not block recognition) and the Chinese script (asr.contracts.SCRIPTS)."""
    if not isinstance(body, dict):
        raise ValueError('请求必须为对象')
    recipe = body.get('recipe')
    if not isinstance(recipe, dict):
        raise ValueError('缺少合成配方')
    return {'recipe': compose_request({**recipe, 'subtitles': None}),
            'script': _choice(body.get('script'), tuple(ASR_SCRIPTS), 'original', '文字转换')}
