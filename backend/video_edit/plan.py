"""Pure compose planning: clip windows, output size and the FFmpeg command for one render.

No files, no subprocesses: the service resolves sources and probes them, this module turns
that into numbers and argv, so every filter graph is unit-testable.

Frame accuracy follows media.py: a clip that starts at frame N seeks (`-seek_timestamp 1`) to
the midpoint between N-1 and N, so the first decoded frame is N; `trim=end_frame=K` keeps
exactly the K frames N..N+K-1. Audio is cut to the same duration, padded with silence when a
source is shorter, and replaced by silence when a clip has no (or a muted) track, so `concat`
always sees one video and one audio stream per segment.

Phase 3: a clip's speed divides its timestamps (`setpts`) and tempo (`atempo`, pitch kept), so it
lasts `seconds / speed` in the output. A transition into the next clip overlaps the two by its
duration (`xfade` + `acrossfade`), shortening the total; it is capped at half of either clip so
neighbouring transitions never overlap. Without transitions the graph is one `concat`, as before.

Phase 3b: subtitle cues arrive as PNG inputs (subtitles.py) overlaid on the joined picture, each
enabled from its start (inclusive) to its end (exclusive) on the output timeline.

Automatic subtitles: voice_graph renders only the clips' own sound (no music) on the same timeline
as 16 kHz mono, so recognized timestamps are already output seconds.
"""
from __future__ import annotations

from .contracts import MIN_CLIP_SECONDS

SAMPLE_RATE = 48000
FAST_BITRATES = {720: '6M', 1080: '12M'}
ASPECT_RATIOS = {'16:9': (16, 9), '9:16': (9, 16), '1:1': (1, 1), '4:5': (4, 5)}
MAX_LONG_SIDE = 3840


def _even(value: float) -> int:
    return max(2, int(round(value / 2)) * 2)


def output_size(aspect: str, resolution: int, source_width: int, source_height: int) -> tuple[int, int]:
    """Short side = `resolution`; `source` keeps the first clip's shape."""
    if aspect in ASPECT_RATIOS:
        across, down = ASPECT_RATIOS[aspect]
    else:
        across, down = max(1, int(source_width)), max(1, int(source_height))
    if across >= down:
        width, height = resolution * across / down, resolution
    else:
        width, height = resolution, resolution * down / across
    scale = min(1.0, MAX_LONG_SIDE / max(width, height))
    return _even(width * scale), _even(height * scale)


def clip_window(info: dict, start_frame: int, end_frame: int) -> dict:
    """Frames [start, end] (end inclusive, -1 = last) of one probed source as seek args and a duration."""
    times, pts = info['frame_times'], info['pts']
    count = len(times)
    end = count - 1 if end_frame == -1 else end_frame
    if not 0 <= start_frame < count or not 0 <= end < count:
        raise ValueError(f'裁切范围超出视频长度（共 {count} 帧）')
    if end < start_frame:
        raise ValueError('出点必须在入点之后')
    if end + 1 < count:
        stop = times[end + 1]
    else:  # the last frame lasts as long as the one before it
        stop = times[end] + (times[end] - times[end - 1] if end > 0 else 1 / max(info.get('fps') or 30, 1))
    seconds = round(stop - times[start_frame], 6)
    if seconds < MIN_CLIP_SECONDS - 1e-6:
        raise ValueError(f'每段至少 {MIN_CLIP_SECONDS:g} 秒')
    seek = [] if start_frame <= 0 else ['-seek_timestamp', '1', '-ss', f'{(pts[start_frame - 1] + pts[start_frame]) / 2:.6f}']
    return {'start_frame': start_frame, 'end_frame': end, 'frames': end - start_frame + 1, 'seconds': seconds,
            'start_time': times[start_frame], 'seek': seek}


def output_seconds(seconds: float, speed: float) -> float:
    return round(seconds / speed, 6)


def transition_cuts(clips: list[dict]) -> list[float]:
    """Overlap in seconds between clip i and i+1 (len = clips - 1); 0 where there is no transition."""
    lengths = [output_seconds(clip['seconds'], clip.get('speed', 1.0)) for clip in clips]
    cuts = []
    for index in range(len(clips) - 1):
        transition = clips[index].get('transition') or {}
        if transition.get('type', 'none') == 'none':
            cuts.append(0.0)
        else:
            cuts.append(round(min(transition['duration'], lengths[index] / 2, lengths[index + 1] / 2), 6))
    return cuts


def total_seconds(clips: list[dict]) -> float:
    lengths = [output_seconds(clip['seconds'], clip.get('speed', 1.0)) for clip in clips]
    return round(sum(lengths) - sum(transition_cuts(clips)), 6)


def _fit(label_in: str, label_out: str, fit: str, width: int, height: int, index: int) -> str:
    if fit == 'pad':
        return (f'{label_in}scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,'
                f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black{label_out}')
    if fit == 'blur':
        small_w, small_h = _even(width / 8), _even(height / 8)
        return (f'{label_in}split=2[bg{index}][fg{index}];'
                f'[bg{index}]scale={small_w}:{small_h}:force_original_aspect_ratio=increase,crop={small_w}:{small_h},'
                f'boxblur=8:2,scale={width}:{height}[bgs{index}];'
                f'[fg{index}]scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2[fgs{index}];'
                f'[bgs{index}][fgs{index}]overlay=(W-w)/2:(H-h)/2{label_out}')
    return (f'{label_in}scale={width}:{height}:force_original_aspect_ratio=increase,'
            f'crop={width}:{height}{label_out}')


def _overlays(video: str, overlays: list[dict]) -> list[str]:
    """Chain each subtitle PNG over `video`, ending in [vout]. overlays: {input, x, y, start, end}."""
    parts = []
    for index, item in enumerate(overlays):
        out = '[vout]' if index == len(overlays) - 1 else f'[vs{index}]'
        parts.append(f"{video}[{item['input']}:v:0]overlay=x={item['x']}:y={item['y']}:"
                     f"enable='gte(t,{item['start']:.3f})*lt(t,{item['end']:.3f})'{out}")
        video = out
    return parts


STEREO = f'aresample={SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo'


def _clip_audio(index: int, clip: dict, seconds: str, clip_volume: float) -> str:
    """Clip `index`'s audio as [a{index}]: trimmed, sped up, padded to `seconds`, or silence when muted."""
    if clip['audio']:
        speed = clip.get('speed', 1.0)
        gain = '' if abs(clip_volume - 1) < 1e-9 else f',volume={clip_volume:g}'
        tempo = '' if speed == 1 else f',atempo={speed:g}'
        return f'[{index}:a:0]{STEREO},asetpts=PTS-STARTPTS{tempo},apad,atrim=duration={seconds}{gain}[a{index}]'
    return f'anullsrc=r={SAMPLE_RATE}:cl=stereo,atrim=duration={seconds},aformat=sample_fmts=fltp[a{index}]'


def filter_graph(clips: list[dict], music: dict | None, *, width: int, height: int, fps: int, fit: str,
                 clip_volume: float, overlays: list[dict] | None = None) -> tuple[str, float]:
    """(filter_complex, total seconds). clips: {frames, seconds, audio, speed?, transition?};
    music: {input, volume, fade_in, fade_out, duration}; overlays: subtitle PNG inputs (see _overlays)."""
    joined = '[vmain]' if overlays else '[vout]'
    parts, labels, lengths = [], [], []
    stereo = STEREO
    for index, clip in enumerate(clips):
        speed = clip.get('speed', 1.0)
        length = output_seconds(clip['seconds'], speed)
        lengths.append(length)
        seconds = f'{length:.6f}'
        timestamps = 'setpts=PTS-STARTPTS' if speed == 1 else f'setpts=(PTS-STARTPTS)/{speed:g}'
        parts.append(_fit(f'[{index}:v:0]trim=end_frame={clip["frames"]},{timestamps},', f'[vf{index}]',
                          fit, width, height, index))
        parts.append(f'[vf{index}]fps={fps},setsar=1,format=yuv420p,trim=duration={seconds}[v{index}]')
        parts.append(_clip_audio(index, clip, seconds, clip_volume))
        labels.append(f'[v{index}][a{index}]')
    cuts = transition_cuts(clips)
    total = round(sum(lengths) - sum(cuts), 6)
    if not any(cuts):
        parts.append(f'{"".join(labels)}concat=n={len(clips)}:v=1:a=1{joined}[acat]')
    else:
        # Pairwise: the running result joins the next clip by a cut (concat) or an overlap (xfade).
        video, audio, length = '[v0]', '[a0]', lengths[0]
        for index in range(1, len(clips)):
            cut, last = cuts[index - 1], index == len(clips) - 1
            out_v, out_a = (joined, '[acat]') if last else (f'[vj{index}]', f'[aj{index}]')
            if cut:
                kind = clips[index - 1]['transition']['type']
                parts.append(f'{video}[v{index}]xfade=transition={kind}:duration={cut:.6f}:offset={length - cut:.6f}{out_v}')
                parts.append(f'{audio}[a{index}]acrossfade=d={cut:.6f}:c1=tri:c2=tri{out_a}')
            else:
                parts.append(f'{video}[v{index}]concat=n=2:v=1:a=0{out_v}')
                parts.append(f'{audio}[a{index}]concat=n=2:v=0:a=1{out_a}')
            video, audio, length = out_v, out_a, length + lengths[index] - cut
    if overlays:
        parts.extend(_overlays(joined, overlays))
    loud = any(clip['audio'] for clip in clips) and clip_volume > 1
    if music:
        chain = [f'[{music["input"]}:a:0]{stereo}', f'atrim=duration={total:.6f}', 'asetpts=PTS-STARTPTS']
        if abs(music['volume'] - 1) > 1e-9:
            chain.append(f'volume={music["volume"]:g}')
        heard = min(total, music.get('duration') or total)
        if music['fade_in'] > 0:
            chain.append(f'afade=t=in:st=0:d={min(music["fade_in"], heard):g}')
        if music['fade_out'] > 0:
            length = min(music['fade_out'], heard)
            chain.append(f'afade=t=out:st={max(0.0, heard - length):.3f}:d={length:g}')
        parts.append(','.join(chain) + '[music]')
        parts.append('[acat][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,'
                     'alimiter=limit=0.97:level=0[aout]')
    elif loud:
        parts.append('[acat]alimiter=limit=0.97:level=0[aout]')
    else:
        parts.append('[acat]anull[aout]')
    return ';'.join(parts), total


def voice_graph(clips: list[dict]) -> tuple[str, float]:
    """(filter_complex, total) for the clips' own sound only, on the render's timeline: the same clip
    audio, speed and transition overlaps as filter_graph, no music and no gain, as 16 kHz mono [aout]
    for speech recognition. Muted clips are silence, exactly as they are in the render."""
    parts, lengths = [], []
    for index, clip in enumerate(clips):
        length = output_seconds(clip['seconds'], clip.get('speed', 1.0))
        lengths.append(length)
        parts.append(_clip_audio(index, clip, f'{length:.6f}', 1.0))
    cuts = transition_cuts(clips)
    total = round(sum(lengths) - sum(cuts), 6)
    if not any(cuts):
        parts.append(f'{"".join(f"[a{index}]" for index in range(len(clips)))}concat=n={len(clips)}:v=0:a=1[voice]')
    else:
        audio = '[a0]'
        for index in range(1, len(clips)):
            out = '[voice]' if index == len(clips) - 1 else f'[aj{index}]'
            cut = cuts[index - 1]
            parts.append(f'{audio}[a{index}]acrossfade=d={cut:.6f}:c1=tri:c2=tri{out}' if cut
                         else f'{audio}[a{index}]concat=n=2:v=0:a=1{out}')
            audio = out
    parts.append('[voice]aresample=16000,aformat=sample_fmts=s16:channel_layouts=mono[aout]')
    return ';'.join(parts), total


def voice_command(ffmpeg: str, clips: list[dict], *, target: str) -> tuple[list[str], float]:
    """argv writing voice_graph to a WAV. clips: {path, seek, seconds, audio, speed?, transition?}."""
    argv = [ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-nostats']
    for clip in clips:
        argv += [*clip['seek'], '-i', str(clip['path'])]
    graph, total = voice_graph(clips)
    argv += ['-filter_complex', graph, '-map', '[aout]', '-c:a', 'pcm_s16le', '-t', f'{total:.6f}',
             '-f', 'wav', '-y', str(target)]
    return argv, total


def encoder_args(encoder: str, resolution: int) -> list[str]:
    if encoder == 'fast':
        return ['-c:v', 'h264_videotoolbox', '-b:v', FAST_BITRATES.get(resolution, '12M'), '-allow_sw', '1',
                '-pix_fmt', 'yuv420p']
    return ['-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-profile:v', 'high', '-pix_fmt', 'yuv420p']


def command(ffmpeg: str, clips: list[dict], music: dict | None, output: dict, *, width: int, height: int,
            clip_volume: float, target: str, overlays: list[dict] | None = None) -> tuple[list[str], float]:
    """Full argv. clips: {path, seek, frames, seconds, audio}; music: {path, volume, fade_in, fade_out, duration};
    overlays: subtitle PNGs {path, x, y, start, end} (subtitles.render)."""
    argv = [ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-nostats', '-progress', 'pipe:1']
    for clip in clips:
        argv += [*clip['seek'], '-i', str(clip['path'])]
    mixed = None
    if music:
        mixed = dict(music, input=len(clips))
        argv += ['-i', str(music['path'])]
    first = len(clips) + (1 if music else 0)
    placed = [dict(item, input=first + index) for index, item in enumerate(overlays or [])]
    for item in placed:
        argv += ['-i', str(item['path'])]
    graph, total = filter_graph(clips, mixed, width=width, height=height, fps=output['fps'], fit=output['fit'],
                                clip_volume=clip_volume, overlays=placed)
    argv += ['-filter_complex', graph, '-map', '[vout]', '-map', '[aout]',
             *encoder_args(output['encoder'], output['resolution']), '-r', str(output['fps']),
             '-c:a', 'aac', '-b:a', '192k', '-ar', str(SAMPLE_RATE), '-movflags', '+faststart',
             '-t', f'{total:.6f}', '-f', 'mp4', '-y', str(target)]
    return argv, total


def progress_share(line: str, total: float) -> float | None:
    """Share done from one `-progress` line (`out_time_us=` / `out_time_ms=` are both microseconds)."""
    key, _, value = line.partition('=')
    if key not in ('out_time_us', 'out_time_ms') or not value.strip().lstrip('-').isdigit():
        return None
    return max(0.0, min(1.0, int(value) / 1e6 / max(total, 1e-3)))
