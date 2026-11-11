"""Durable compose jobs: one SQLite table of JSON documents under `data/video-edit/`.

Renders take minutes, so their receipts and recipes survive a restart. A job that was queued
or running when the process stopped is marked `interrupted` on start and keeps its recipe;
nothing re-runs by itself. Finished outputs live in the archive, not here.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid

ACTIVE = ('queued', 'running')
KEEP_FINISHED = 200


def identifier(value) -> str:
    text = str(value or '')
    if not re.fullmatch(r'[a-f0-9]{32}', text):
        raise FileNotFoundError('合成任务不存在或已过期')
    return text


class ComposeStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, created REAL NOT NULL, data TEXT NOT NULL)')

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.root / 'jobs.sqlite3', timeout=20)) as db:
            with db:
                yield db

    def recover(self) -> list[str]:
        """Mark jobs cut off by a stop as interrupted; return their ids."""
        interrupted = []
        with self.db() as db:
            for ident, raw in db.execute('SELECT id, data FROM jobs').fetchall():
                job = json.loads(raw)
                if job['status'] in ACTIVE:
                    job.update(status='interrupted', stage='服务重启，合成已中断', updated_at=time.time())
                    db.execute('UPDATE jobs SET data=? WHERE id=?', (json.dumps(job, ensure_ascii=False), ident))
                    interrupted.append(ident)
        return interrupted

    def create(self, spec: dict, summary: dict) -> dict:
        now = time.time()
        job = {'id': uuid.uuid4().hex, 'kind': 'compose', 'status': 'queued', 'stage': '排队中', 'progress_percent': 0,
               'error': '', 'result': None, 'created_at': now, 'updated_at': now, 'spec': spec, 'summary': summary}
        job['task_id'] = job['id']
        with self.db() as db:
            db.execute('INSERT INTO jobs VALUES (?,?,?)', (job['id'], now, json.dumps(job, ensure_ascii=False)))
            stale = db.execute('SELECT id FROM jobs ORDER BY created DESC LIMIT -1 OFFSET ?', (KEEP_FINISHED,)).fetchall()
            for (old,) in stale:
                row = db.execute('SELECT data FROM jobs WHERE id=?', (old,)).fetchone()
                if row and json.loads(row[0])['status'] not in ACTIVE:
                    db.execute('DELETE FROM jobs WHERE id=?', (old,))
        return job

    def has(self, ident) -> bool:
        try:
            ident = identifier(ident)
        except FileNotFoundError:
            return False
        with self.db() as db:
            return db.execute('SELECT 1 FROM jobs WHERE id=?', (ident,)).fetchone() is not None

    def get(self, ident) -> dict:
        ident = identifier(ident)
        with self.db() as db:
            row = db.execute('SELECT data FROM jobs WHERE id=?', (ident,)).fetchone()
        if not row:
            raise FileNotFoundError('合成任务不存在或已过期')
        return json.loads(row[0])

    def update(self, ident, **changes) -> dict:
        ident = identifier(ident)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM jobs WHERE id=?', (ident,)).fetchone()
            if not row:
                raise FileNotFoundError('合成任务不存在或已过期')
            job = json.loads(row[0])
            job.update(changes, updated_at=time.time())
            db.execute('UPDATE jobs SET data=? WHERE id=?', (json.dumps(job, ensure_ascii=False), ident))
        return job

    def active(self) -> list[dict]:
        with self.db() as db:
            rows = db.execute('SELECT data FROM jobs ORDER BY created').fetchall()
        return [job for job in (json.loads(row[0]) for row in rows) if job['status'] in ACTIVE]
