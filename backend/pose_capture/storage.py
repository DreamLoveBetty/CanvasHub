"""Uploaded photos and videos and durable recognition jobs, separate from other domains' stores."""
from contextlib import closing, contextmanager
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .contracts import ACTIVE, MAX_PIXELS, MAX_UPLOAD, MAX_VIDEO_UPLOAD, VIDEO_SIGNATURES, identifier, video_suffix

FORMATS = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'}
SUFFIXES = tuple(FORMATS.values()) + tuple(suffix for suffix, _ in VIDEO_SIGNATURES)


class Store:
    def __init__(self, root):
        self.root = Path(root)
        (self.root / 'assets').mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, data TEXT NOT NULL)')

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.root / 'jobs.sqlite3', timeout=20)) as db:
            with db:
                yield db

    def recover(self):
        with self.db() as db:
            for ident, raw in db.execute('SELECT id,data FROM jobs').fetchall():
                job = json.loads(raw)
                if job['status'] in ACTIVE:
                    job.update(status='interrupted', stage='服务重启，任务已中断', finished_at=time.time())
                    db.execute('UPDATE jobs SET data=? WHERE id=?', (json.dumps(job), ident))

    def upload(self, data, name):
        suffix = video_suffix(data)
        if suffix:
            return self._store(data, name, suffix, kind='video')
        if not 0 < len(data) <= MAX_UPLOAD:
            raise ValueError('图片须小于 20 MB')
        from PIL import Image, UnidentifiedImageError
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
                width, height, fmt = image.width, image.height, image.format
        except (OSError, ValueError, UnidentifiedImageError):
            raise ValueError('无法识别图片') from None
        if fmt not in FORMATS:
            raise ValueError('仅支持 PNG、JPEG 或 WebP 图片')
        if not 16 <= min(width, height) or width * height > MAX_PIXELS:
            raise ValueError('图片尺寸过小或像素过多')
        return self._store(data, name, FORMATS[fmt], kind='photo', width=width, height=height)

    def _store(self, data, name, suffix, kind, **extra):
        if kind == 'video' and len(data) > MAX_VIDEO_UPLOAD:
            raise ValueError('视频须小于 200 MB')
        digest = hashlib.sha256(data).hexdigest()
        ident = digest[:32]  # identical uploads share one asset
        path = self.root / 'assets' / (ident + suffix)
        if not path.exists():
            pending = path.with_name(path.name + '.uploading')
            pending.write_bytes(data)
            pending.replace(path)
        # Video duration, frame rate and size are read by the worker (no media libraries in the HTTP process).
        info = {'asset_id': ident, 'kind': kind, 'name': Path(str(name or kind)).name[:150], 'file_size': len(data),
                'sha256': digest, **extra}
        path.with_suffix('.json').write_text(json.dumps(info, ensure_ascii=False))
        return info

    def asset(self, ident):
        identifier(ident)
        for suffix in SUFFIXES:
            path = self.root / 'assets' / (ident + suffix)
            if path.is_file() and not path.is_symlink():
                return path
        raise FileNotFoundError('识别素材不存在，请重新提交')

    def asset_kind(self, ident):
        """photo | video, from the stored container (sidecars written before videos existed are photos)."""
        return 'video' if self.asset(ident).suffix in dict(VIDEO_SIGNATURES) else 'photo'

    def path(self, ident):
        return self.root / 'jobs' / identifier(ident)

    def create(self, spec):
        job = {'id': uuid.uuid4().hex, 'status': 'queued', 'stage': '等待识别', 'created_at': time.time(), 'spec': spec, 'error': ''}
        self.path(job['id']).mkdir(parents=True)
        with self.db() as db:
            db.execute('INSERT INTO jobs VALUES (?,?)', (job['id'], json.dumps(job)))
        return job

    def get(self, ident):
        identifier(ident)
        with self.db() as db:
            row = db.execute('SELECT data FROM jobs WHERE id=?', (ident,)).fetchone()
        if not row:
            raise FileNotFoundError('识别任务不存在')
        return json.loads(row[0])

    def update(self, ident, **changes):
        identifier(ident)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM jobs WHERE id=?', (ident,)).fetchone()
            if not row:
                raise FileNotFoundError('识别任务不存在')
            job = json.loads(row[0])
            job.update(changes)
            db.execute('UPDATE jobs SET data=? WHERE id=?', (json.dumps(job), ident))
        return job

    def result(self, ident):
        path = self.path(ident) / 'result.json'
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError('识别结果不存在')
        return json.loads(path.read_text())
