"""Recoverable SQLite job store and job artifact directory for video_understand."""
from __future__ import annotations

from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List
import uuid

from .contracts import ACTIVE, identifier


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        (self.root / "jobs").mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, data TEXT NOT NULL)")

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.root / "jobs.sqlite3", timeout=20)) as conn:
            with conn:
                yield conn

    def recover(self) -> None:
        with self.db() as db:
            for ident, raw in db.execute("SELECT id, data FROM jobs").fetchall():
                job = json.loads(raw)
                if job.get("status") in ACTIVE:
                    job.update(status="interrupted", stage="服务重启，任务已中断", finished_at=time.time())
                    db.execute("UPDATE jobs SET data=? WHERE id=?", (json.dumps(job, ensure_ascii=False), ident))

    def path(self, ident: str) -> Path:
        return self.root / "jobs" / identifier(ident)

    def create(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        job = {
            "id": uuid.uuid4().hex,
            "status": "queued",
            "stage": "等待本地处理",
            "progress_percent": 0,
            "progress_message": "等待本地处理",
            "created_at": time.time(),
            "spec": spec,
            "result": None,
            "artifacts": [],
            "events": [],
            "error": "",
        }
        self.path(job["id"]).mkdir(parents=True)
        with self.db() as db:
            db.execute("INSERT INTO jobs VALUES (?, ?)", (job["id"], json.dumps(job, ensure_ascii=False)))
        return job

    def get(self, ident: str) -> Dict[str, Any]:
        identifier(ident)
        with self.db() as db:
            row = db.execute("SELECT data FROM jobs WHERE id=?", (ident,)).fetchone()
        if not row:
            raise FileNotFoundError("视频理解任务不存在")
        return json.loads(row[0])

    def update(self, ident: str, **changes: Any) -> Dict[str, Any]:
        identifier(ident)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM jobs WHERE id=?", (ident,)).fetchone()
            if not row:
                raise FileNotFoundError("视频理解任务不存在")
            job = json.loads(row[0])
            job.update(changes)
            db.execute("UPDATE jobs SET data=? WHERE id=?", (json.dumps(job, ensure_ascii=False), ident))
        return job

    def recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.db() as db:
            rows = db.execute("SELECT data FROM jobs ORDER BY rowid DESC LIMIT ?", (int(limit),)).fetchall()
        return [json.loads(raw) for (raw,) in rows]

    def artifact(self, ident: str, name: str) -> Path:
        job = self.get(ident)
        if name not in {item.get("name") for item in job.get("artifacts", [])}:
            raise FileNotFoundError("产物不存在")
        job_dir = self.path(ident).resolve()
        path = self.path(ident) / name
        if path.is_symlink() or not path.resolve().is_relative_to(job_dir) or not path.is_file():
            raise FileNotFoundError("产物不存在")
        return path
