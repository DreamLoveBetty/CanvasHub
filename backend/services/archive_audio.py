"""Generated audio in the configured archive: publish, list, resolve and delete with undo.

Final audio files live in `<archive>/audio/YYYY-MM-DD/` beside a `.txt` prompt, an Obsidian
`.md` note, a `.json` metadata sidecar and, when the engine wrote one, its `.abc` score. The
image and video scanners skip this subtree. The audio worker never imports this module:
server.py hands `AudioArchive.publish` to `AudioService` as an explicit port, and the job's
own directory stays the immutable receipt that `/api/audio/artifact` serves.
"""
from __future__ import annotations

from array import array
import hashlib
import json
import math
import mimetypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlencode

AUDIO_ASSET_PREFIX = 'audio_'
AUDIO_EXTENSIONS = frozenset({'.flac', '.wav', '.mp3', '.m4a', '.ogg', '.opus', '.aac'})
# Written next to each archived audio file; all of them move to the trash with it.
SIDECAR_SUFFIXES = ('.txt', '.md', '.json', '.abc')
MAX_AUDIO_DELETE = 60
FILE_ROUTE = '/api/assets/audio/file'
PEAK_COUNT = 64
# launchd/Finder do not read shell profiles, so look where Homebrew installs FFmpeg as well.
_FFMPEG_DIRS = ('/opt/homebrew/bin', '/usr/local/bin')
_MIME = {'.flac': 'audio/flac', '.wav': 'audio/wav', '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4',
         '.ogg': 'audio/ogg', '.opus': 'audio/ogg', '.aac': 'audio/aac'}


def mime_type(path):
    suffix = Path(path).suffix.lower()
    return _MIME.get(suffix) or mimetypes.guess_type(Path(path).name)[0] or 'application/octet-stream'


def audio_asset_id(rel_path):
    return AUDIO_ASSET_PREFIX + hashlib.sha256(str(rel_path).encode('utf-8')).hexdigest()[:24]


def read_stream_info(path):
    """Duration, sample rate and channels from a FLAC or WAV header; None for other formats.

    Standard library only: the server process never imports the audio engine's dependencies.
    """
    try:
        with open(path, 'rb') as stream:
            head = stream.read(12)
            if head[:4] == b'fLaC':
                block = head[4:12] + stream.read(30)
                if len(block) < 38 or block[0] & 0x7f != 0:
                    return None
                packed = int.from_bytes(block[14:22], 'big')
                rate, channels, total = packed >> 44, ((packed >> 41) & 7) + 1, packed & ((1 << 36) - 1)
                return dict(duration_seconds=round(total / rate, 3) if rate and total else 0,
                            sample_rate=rate, channels=channels)
            if head[:4] == b'RIFF' and head[8:12] == b'WAVE':
                rate = channels = byte_rate = 0
                for _ in range(64):
                    chunk = stream.read(8)
                    if len(chunk) < 8:
                        return None
                    kind, size = chunk[:4], int.from_bytes(chunk[4:], 'little')
                    if kind == b'fmt ':
                        fmt = stream.read(size)
                        channels = int.from_bytes(fmt[2:4], 'little')
                        rate = int.from_bytes(fmt[4:8], 'little')
                        byte_rate = int.from_bytes(fmt[8:12], 'little')
                        if size % 2: stream.seek(1, os.SEEK_CUR)
                        continue
                    if kind == b'data':
                        if not byte_rate:
                            return None
                        return dict(duration_seconds=round(size / byte_rate, 3), sample_rate=rate, channels=channels)
                    stream.seek(size + size % 2, os.SEEK_CUR)
    except OSError:
        return None
    return None


def _ffmpeg():
    found = shutil.which('ffmpeg')
    if found:
        return found
    for directory in _FFMPEG_DIRS:
        candidate = Path(directory) / 'ffmpeg'
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def compute_peaks(path, count=PEAK_COUNT):
    """Loudness envelope (0–1, `count` bars) for the gallery waveform, or None without FFmpeg.

    FFmpeg decodes any archived format to 2 kHz mono PCM; the server imports no audio library.
    """
    executable = _ffmpeg()
    if not executable:
        return None
    command = [executable, '-v', 'error', '-nostdin', '-i', str(path), '-ac', '1', '-ar', '2000', '-f', 's16le', '-']
    try:
        result = subprocess.run(command, capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    data = result.stdout[:len(result.stdout) // 2 * 2]
    if result.returncode != 0 or len(data) < count * 2:
        return None
    samples = array('h')
    samples.frombytes(data)
    if sys.byteorder == 'big':
        samples.byteswap()
    step = len(samples) / count
    levels = []
    for index in range(count):
        chunk = samples[int(index * step):max(int((index + 1) * step), int(index * step) + 1)]
        # RMS follows perceived loudness more closely than the sample maximum.
        levels.append(math.sqrt(sum(value * value for value in chunk) / len(chunk)))
    top = max(levels) or 1
    return [round(level / top, 3) for level in levels]


def _valid_peaks(value):
    return (isinstance(value, list) and 8 <= len(value) <= 256
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1 for v in value))


def _prompt_text(request):
    style = str(request.get('style') or '').strip()
    lyrics = str(request.get('lyrics') or '').strip()
    return '\n\n'.join(part for part in (f'风格：\n{style}' if style else '', f'歌词：\n{lyrics}' if lyrics else '') if part)


def _write_text(path, text):
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(text)
    temp.replace(path)


class AudioArchive:
    """One archive subtree. `root` is a callable so the configured archive path is read late."""

    def __init__(self, root, *, write_markdown, move_to_trash=None, record_batch=None, peaks=compute_peaks):
        self._root = root
        self._write_markdown = write_markdown
        self._peaks = peaks
        self._move_to_trash = move_to_trash
        self._record_batch = record_batch
        self._lock = threading.Lock()
        self._info_cache = {}

    @property
    def root(self):
        return Path(self._root()).expanduser()

    def publish(self, source, *, job_id, created_at, spec, score=None):
        """Copy a finished job's audio (and score) into the archive; idempotent per job."""
        request = spec.get('request') or {}
        has_score = bool(score and Path(score).is_file())
        return self.publish_file(
            source, name=f'yue_{str(job_id)[:12]}{Path(source).suffix.lower()}', created_at=created_at,
            prompt=_prompt_text(request), extras={'.abc': score} if has_score else None,
            metadata=dict(
                source='tg-mini-app-img-gen', type='audio', engine='yue', job_id=job_id,
                created_at=created_at, audio_format=Path(source).suffix.lower().lstrip('.'),
                precision=spec.get('precision', ''), style=request.get('style', ''),
                lyrics=request.get('lyrics', ''), seed=request.get('seed'), cot=request.get('cot', ''),
                ode_steps=(request.get('generation_config') or {}).get('ode_steps'),
                has_reference_abc='abc' in request, has_score=has_score))

    def publish_file(self, source, *, name, created_at, prompt, metadata, extras=None):
        """Copy one audio file into `<root>/YYYY-MM-DD/<name>` with `.txt`, `.md` and `.json` sidecars.

        Any producer (generated songs, a video's separated track) goes through here, so every
        archived file has the same sidecars, waveform peaks and atomic write. `extras` maps a
        sidecar suffix to a file copied next to the audio. Re-publishing the same name is a no-op copy.
        """
        source = Path(source)
        suffix = source.suffix.lower()
        if suffix not in AUDIO_EXTENSIONS or not source.is_file() or Path(name).suffix.lower() != suffix:
            raise FileNotFoundError('没有可归档的音频文件')
        if Path(name).name != name or name.startswith('.'):
            raise ValueError('无效音频文件名')
        day = time.strftime('%Y-%m-%d', time.localtime(created_at or time.time()))
        folder = self.root / day
        target = folder / name
        with self._lock:
            folder.mkdir(parents=True, exist_ok=True)
            if not (target.is_file() and target.stat().st_size == source.stat().st_size):
                with tempfile.NamedTemporaryFile(dir=folder, prefix='.audio-', delete=False) as stream:
                    temp = Path(stream.name)
                try:
                    shutil.copyfile(source, temp)
                    temp.replace(target)
                except BaseException:
                    temp.unlink(missing_ok=True)
                    raise
            for extra_suffix, extra in (extras or {}).items():
                if extra and Path(extra).is_file():
                    shutil.copyfile(extra, target.with_suffix(extra_suffix))
            txt = target.with_suffix('.txt')
            _write_text(txt, prompt)
            self._write_markdown(target, prompt, txt_path=txt)
            stored = {**metadata, 'peaks': self._peaks(target), **(read_stream_info(target) or {})}
            _write_text(target.with_suffix('.json'), json.dumps(stored, ensure_ascii=False, indent=2))
        return {'path': target.relative_to(self.root).as_posix()}

    def find(self, pattern):
        """The newest archived audio whose file name matches `pattern` (a glob), as a list item."""
        root = self.root
        if not root.is_dir():
            return None
        resolved = root.resolve()
        matches = sorted((path for path in resolved.glob('*/' + pattern)
                          if path.is_file() and not path.is_symlink() and path.suffix.lower() in AUDIO_EXTENSIONS),
                         key=lambda path: path.stat().st_mtime, reverse=True)
        return self._item(matches[0], resolved) if matches else None

    def item(self, rel_path):
        path = self.resolve(rel_path)
        return self._item(path, self.root.resolve())

    def resolve(self, rel_path):
        """Resolve a public `YYYY-MM-DD/name.flac` path without leaving the audio subtree."""
        clean = str(rel_path or '').strip().replace('\\', '/').lstrip('/')
        parts = clean.split('/')
        if not clean or any(part in ('', '.', '..') or part.startswith('.') for part in parts):
            raise FileNotFoundError('音频不存在')
        root = self.root.resolve()
        path = (root / clean)
        if path.is_symlink() or path.suffix.lower() not in AUDIO_EXTENSIONS:
            raise FileNotFoundError('音频不存在')
        path = path.resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise FileNotFoundError('音频不存在')
        return path

    def _metadata(self, path):
        stat = path.stat()
        sidecar = path.with_suffix('.json')
        try:
            sidecar_stamp = sidecar.stat().st_mtime_ns
        except OSError:
            sidecar_stamp = 0
        key = (str(path), stat.st_mtime_ns, stat.st_size, sidecar_stamp)
        cached = self._info_cache.get(str(path))
        if cached and cached[0] == key:
            return cached[1]
        data = {}
        try:
            loaded = json.loads(sidecar.read_text(encoding='utf-8')) if sidecar.is_file() else {}
            data = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            data = {}
        if not data.get('duration_seconds'):
            data = {**data, **(read_stream_info(path) or {})}
        self._info_cache[str(path)] = (key, data)
        return data

    def _item(self, path, root):
        rel = path.relative_to(root).as_posix()
        stat = path.stat()
        meta = self._metadata(path)
        number = lambda value: value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
        created = number(meta.get('created_at')) or stat.st_mtime
        style = str(meta.get('style') or '')
        lyrics = str(meta.get('lyrics') or '')
        title = str(meta.get('title') or '').strip() or (style.strip().splitlines() or [path.stem])[0]
        return dict(
            id=audio_asset_id(rel), path=rel, name=path.name, title=title[:120],
            url=FILE_ROUTE + '?' + urlencode({'path': rel}),
            mime_type=mime_type(path),
            format=path.suffix.lstrip('.').upper(), file_size=stat.st_size, created_at=created,
            duration_seconds=number(meta.get('duration_seconds')) or 0,
            sample_rate=number(meta.get('sample_rate')) or 0, channels=number(meta.get('channels')) or 0,
            job_id=str(meta.get('job_id') or ''), engine=str(meta.get('engine') or ''),
            style=style, lyrics=lyrics, seed=number(meta.get('seed')),
            precision=str(meta.get('precision') or ''), has_score=path.with_suffix('.abc').is_file(),
            peaks=meta.get('peaks') if _valid_peaks(meta.get('peaks')) else None,
        )

    def peaks(self, rel_path):
        """Waveform for one file, computed once: kept in our `.json` sidecar, else in memory."""
        path = self.resolve(rel_path)
        meta = self._metadata(path)
        if _valid_peaks(meta.get('peaks')):
            return {'peaks': meta['peaks']}
        peaks = self._peaks(path)
        if not _valid_peaks(peaks):
            return {'peaks': None}
        sidecar = path.with_suffix('.json')
        with self._lock:
            try:
                stored = json.loads(sidecar.read_text(encoding='utf-8')) if sidecar.is_file() else None
            except (OSError, ValueError):
                stored = None
            if isinstance(stored, dict):
                _write_text(sidecar, json.dumps({**stored, 'peaks': peaks}, ensure_ascii=False, indent=2))
            else:
                meta['peaks'] = peaks
        return {'peaks': peaks}

    def list(self, query='', limit=200, offset=0):
        root = self.root
        items = []
        if root.is_dir():
            resolved = root.resolve()
            for directory, dirnames, filenames in os.walk(resolved, followlinks=False):
                dirnames[:] = sorted(d for d in dirnames if not d.startswith('.'))
                for filename in filenames:
                    path = Path(directory) / filename
                    if filename.startswith('.') or path.suffix.lower() not in AUDIO_EXTENSIONS or path.is_symlink():
                        continue
                    try:
                        items.append(self._item(path, resolved))
                    except OSError:
                        continue
        needle = str(query or '').strip().casefold()
        if needle:
            items = [item for item in items if needle in ' '.join(
                (item['name'], item['title'], item['style'], item['lyrics'], item['format'])).casefold()]
        items.sort(key=lambda item: (item['created_at'], item['path']), reverse=True)
        total = len(items)
        return {
            'ok': True, 'total': total, 'items': items[offset:offset + limit],
            'stats': {
                'total': total,
                'total_file_size': sum(item['file_size'] for item in items),
                'total_duration_seconds': round(sum(item['duration_seconds'] for item in items), 3),
                'by_format': {fmt: sum(1 for item in items if item['format'] == fmt)
                              for fmt in sorted({item['format'] for item in items})},
            },
        }

    def delete(self, paths):
        """Move archived audio and its sidecars to the trash and record an undoable batch."""
        if self._move_to_trash is None or self._record_batch is None:
            raise RuntimeError('音频删除未配置废纸篓')
        clean = []
        for raw in paths or []:
            value = str(raw or '').strip()
            if value and value not in clean:
                clean.append(value)
        if not clean:
            raise ValueError('缺少音频路径')
        if len(clean) > MAX_AUDIO_DELETE:
            raise ValueError(f'单次最多删除 {MAX_AUDIO_DELETE} 个音频')
        targets = [(rel, self.resolve(rel)) for rel in clean]
        deleted, missing, skipped, moves, asset_ids, assets = [], [], [], [], [], []
        for rel, path in targets:
            asset_id = audio_asset_id(rel)
            asset_ids.append(asset_id)
            assets.append({'id': asset_id, 'asset_id': asset_id, 'file': path.name, 'kind': 'audio', 'path': rel})
            self._move_to_trash(path, deleted, missing, skipped, moves=moves)
            for suffix in SIDECAR_SUFFIXES:
                sidecar = path.with_suffix(suffix)
                if sidecar.exists():
                    self._move_to_trash(sidecar, deleted, missing, skipped, moves=moves)
            self._info_cache.pop(str(path), None)
        journal = self._record_batch({
            'asset_ids': asset_ids, 'assets': assets, 'moves': moves,
            'task_snapshots': [], 'set_snapshots': [],
            'deleted_files': deleted, 'missing_files': missing, 'skipped_files': skipped,
        })
        return {
            'ok': True, 'asset_ids': asset_ids,
            'delete_batch_id': journal.get('batch_id'), 'undo_id': journal.get('batch_id'),
            'deleted_files': deleted, 'missing_files': missing, 'skipped_files': skipped,
            'message': '音频已移入废纸篓' if deleted else '音频已从资产库移除',
        }
