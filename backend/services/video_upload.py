"""Local videos uploaded into canvas video nodes.

An upload is written into today's archive folder (storage_paths.daily_output_dir), so it is served by
the authenticated /video/ route with byte ranges, listed by the asset library as imported material
(no generation sidecar), and accepted by every video consumer (Topaz Video, ReShot, pose recognition)
exactly like a generated clip. The same content uploaded again on the same day reuses its file.

Dependencies are injected by server.py: output_dir() -> today's folder, probe(path) -> ffprobe metadata.
"""
import hashlib
import os
from pathlib import Path
import re
import time

MAX_UPLOAD = 200 * 1024 * 1024
MIME_TYPES = {'.mp4': 'video/mp4', '.mov': 'video/quicktime', '.webm': 'video/webm'}


def video_suffix(data):
    """Container from the file header (never the client's name): MP4 / MOV via ftyp, WebM via EBML."""
    if len(data) >= 12 and data[4:8] == b'ftyp':
        return '.mov' if data[8:12] == b'qt  ' else '.mp4'
    if data[:4] == b'\x1a\x45\xdf\xa3':
        return '.webm'
    raise ValueError('仅支持 MP4、MOV 或 WebM 视频')


def display_name(name, suffix):
    base = re.sub(r'[\x00-\x1f/\\]+', '', Path(str(name or '')).name).strip()[:120]
    return base or f'本地视频{suffix}'


class VideoUploads:
    def __init__(self, output_dir, probe):
        self.output_dir, self.probe = output_dir, probe

    def upload(self, data, name=''):
        if not 0 < len(data) <= MAX_UPLOAD:
            raise ValueError('视频须小于 200 MiB')
        suffix = video_suffix(data)
        digest = hashlib.sha256(data).hexdigest()[:12]
        day = Path(self.output_dir())
        day.mkdir(parents=True, exist_ok=True)
        existing = sorted(day.glob(f'video_upload_*_{digest}{suffix}'))
        target, reused = (existing[0], True) if existing else (day / f'video_upload_{time.strftime("%H%M%S")}_{digest}{suffix}', False)
        if not reused:
            pending = target.with_name(target.name + '.writing')
            pending.write_bytes(data)
            os.replace(pending, target)
        meta = self.probe(target) or {}
        if not (meta.get('width') and meta.get('height')):
            if not reused:
                target.unlink(missing_ok=True)
            raise ValueError('无法读取视频画面，请确认文件完整且为常见编码')
        return {'url': '/video/' + target.name, 'name': display_name(name, suffix), 'filename': target.name,
                'mime_type': MIME_TYPES[suffix], 'width': int(meta['width']), 'height': int(meta['height']),
                'fps': meta.get('fps') or 0, 'duration_seconds': meta.get('duration_seconds') or 0,
                'file_size': len(data), 'reused': reused}
