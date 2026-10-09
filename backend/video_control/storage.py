"""Recoverable video-control jobs and immutable assets, separate from audio/image DBs."""
from contextlib import contextmanager, closing
from pathlib import Path
import hashlib
import json
import sqlite3
import time
import uuid

from .contracts import identifier, MAX_UPLOAD


class Store:
    def __init__(self, root):
        self.root = Path(root)
        (self.root / 'assets').mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, data TEXT NOT NULL)')

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.root / 'jobs.sqlite3', timeout=20)) as db:
            with db: yield db

    def recover(self):
        with self.db() as db:
            for ident, raw in db.execute('SELECT id,data FROM jobs').fetchall():
                job = json.loads(raw)
                if job['status'] in {'queued', 'running', 'cancelling'}:
                    job.update(status='interrupted', stage='服务重启，任务已中断', finished_at=time.time())
                    db.execute('UPDATE jobs SET data=? WHERE id=?', (json.dumps(job), ident))

    def upload(self, data, name):
        if not 0 < len(data) <= MAX_UPLOAD: raise ValueError('视频须小于 200 MB')
        ident = uuid.uuid4().hex
        path = self.root / 'assets' / ident
        path.write_bytes(data)
        info = {'asset_id': ident, 'name': Path(str(name)).name[:150], 'file_size': len(data),
                'sha256': hashlib.sha256(data).hexdigest()}
        path.with_suffix('.json').write_text(json.dumps(info))
        return info

    def asset(self, ident):
        path = self.root / 'assets' / identifier(ident)
        if not path.is_file() or path.is_symlink(): raise FileNotFoundError('视频素材不存在，请重新导入')
        return path

    def path(self, ident):
        return self.root / 'jobs' / identifier(ident)

    def create(self, spec):
        job = dict(id=uuid.uuid4().hex, status='queued', stage='等待本地处理', created_at=time.time(), spec=spec,
                   artifacts=[], error='')
        self.path(job['id']).mkdir(parents=True)
        with self.db() as db:
            db.execute('INSERT INTO jobs VALUES (?,?)', (job['id'], json.dumps(job)))
        return job

    def get(self, ident):
        identifier(ident)
        with self.db() as db: row = db.execute('SELECT data FROM jobs WHERE id=?', (ident,)).fetchone()
        if not row: raise FileNotFoundError('视频控制任务不存在')
        return json.loads(row[0])

    def update(self, ident, **changes):
        identifier(ident)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM jobs WHERE id=?', (ident,)).fetchone()
            if not row: raise FileNotFoundError('视频控制任务不存在')
            job = json.loads(row[0]); job.update(changes)
            db.execute('UPDATE jobs SET data=? WHERE id=?', (json.dumps(job), ident))
        return job

    def artifact(self, ident, name):
        job = self.get(ident)
        if name not in {item['name'] for item in job['artifacts']}: raise FileNotFoundError('产物不存在')
        path = self.path(ident) / name
        if path.is_symlink() or not path.resolve().is_relative_to(self.path(ident).resolve()) or not path.is_file():
            raise FileNotFoundError('产物不存在')
        return path
