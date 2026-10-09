"""Private audio task database and immutable artifact root, separate from image data."""
from contextlib import closing, contextmanager
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, status TEXT, created REAL, data TEXT)')
            # Never silently regenerate a task after process failure/restart.
            for row in db.execute("SELECT id,data FROM jobs WHERE status IN ('queued','running','cancelling')").fetchall():
                data = json.loads(row['data'])
                data.update(status='interrupted', stage='服务已重启，请重新提交', finished_at=time.time())
                db.execute('UPDATE jobs SET status=?,data=? WHERE id=?', ('interrupted', json.dumps(data), row['id']))

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.root / 'jobs.sqlite3', timeout=20)) as db:
            db.row_factory = sqlite3.Row
            with db:
                yield db

    def create(self, spec):
        job = dict(id=uuid.uuid4().hex, status='queued', stage='等待音频引擎', created_at=time.time(),
                   spec=spec, artifacts=[], error='')
        self.path(job['id']).mkdir(parents=True)
        with self.db() as db:
            db.execute('INSERT INTO jobs VALUES (?,?,?,?)', (job['id'], job['status'], job['created_at'], json.dumps(job)))
        return job

    def get(self, job_id):
        self.path(job_id)  # validate before SQL/filesystem usage
        with self.db() as db:
            row = db.execute('SELECT data FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise FileNotFoundError('音频任务不存在')
        return json.loads(row['data'])

    def update(self, job_id, **changes):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM jobs WHERE id=?', (job_id,)).fetchone()
            data = json.loads(row['data'])
            data.update(changes)
            db.execute('UPDATE jobs SET status=?,data=? WHERE id=?', (data['status'], json.dumps(data), job_id))
        return data

    def list(self):
        with self.db() as db:
            return [json.loads(r['data']) for r in db.execute('SELECT data FROM jobs ORDER BY created DESC LIMIT 50')]

    def path(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch('[a-f0-9]{32}', job_id):
            raise ValueError('无效音频任务 ID')
        return self.root / 'jobs' / job_id

    def artifact(self, job_id, name):
        job = self.get(job_id)
        if name not in {f['name'] for f in job['artifacts']}:
            raise FileNotFoundError('产物不存在')
        root = self.path(job_id).resolve()
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
            raise FileNotFoundError('产物不存在')
        return path
