"""Recoverable jobs and immutable source assets for Topaz Video only."""
from __future__ import annotations

from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .contracts import ACTIVE, MAX_UPLOAD, identifier


VERIFIED_EXPORT_PROVENANCE = frozenset({
    "licensed_topaz_checkout",
    "precise_engine_no_watermark_baseline",
})


class Store:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        (self.root / "assets").mkdir(parents=True, exist_ok=True)
        (self.root / "jobs").mkdir(exist_ok=True)
        with self.db() as database:
            database.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL)")

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.root / "jobs.sqlite3", timeout=20)) as database:
            with database:
                yield database

    def recover(self) -> None:
        with self.db() as database:
            for ident, raw in database.execute("SELECT id,data FROM jobs").fetchall():
                job = json.loads(raw)
                if job.get("status") in ACTIVE:
                    job.update(status="interrupted", stage="服务重启，任务已中断",
                               progress_message="服务重启，任务已中断", finished_at=time.time())
                    database.execute("UPDATE jobs SET data=? WHERE id=?", (json.dumps(job), ident))

    def upload(self, data: bytes, name: str) -> dict:
        if not 0 < len(data) <= MAX_UPLOAD:
            raise ValueError("视频须小于 200 MiB")
        ident = uuid.uuid4().hex
        path = self.root / "assets" / ident
        safe_name = Path(str(name or "source.mp4")).name[:150] or "source.mp4"
        info = {"asset_id": ident, "name": safe_name, "file_size": len(data),
                "sha256": hashlib.sha256(data).hexdigest()}
        path.write_bytes(data)
        path.with_suffix(".json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
        return info

    def asset(self, ident: str) -> Path:
        path = self.root / "assets" / identifier(ident)
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError("视频素材不存在，请重新导入")
        return path

    def path(self, ident: str) -> Path:
        return self.root / "jobs" / identifier(ident)

    def create(self, spec: dict) -> dict:
        ident = uuid.uuid4().hex
        job = {"id": ident, "task_id": ident, "type": "topaz_video",
               "status": "queued", "stage": "等待本地推理", "progress_percent": 0,
               "progress": 0, "progress_message": "等待本地推理", "created_at": time.time(),
               "spec": spec, "artifacts": [], "events": [], "error": ""}
        self.path(ident).mkdir(parents=True, exist_ok=False)
        with self.db() as database:
            database.execute("INSERT INTO jobs VALUES (?,?)", (ident, json.dumps(job, ensure_ascii=False)))
        return job

    def get(self, ident: str) -> dict:
        identifier(ident)
        with self.db() as database:
            row = database.execute("SELECT data FROM jobs WHERE id=?", (ident,)).fetchone()
        if not row:
            raise FileNotFoundError("Topaz Video 任务不存在")
        return json.loads(row[0])

    def update(self, ident: str, **changes) -> dict:
        identifier(ident)
        with self.db() as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute("SELECT data FROM jobs WHERE id=?", (ident,)).fetchone()
            if not row:
                raise FileNotFoundError("Topaz Video 任务不存在")
            job = json.loads(row[0])
            job.update(changes)
            database.execute("UPDATE jobs SET data=? WHERE id=?", (json.dumps(job, ensure_ascii=False), ident))
        return job

    def verified_model_scales(self) -> dict[str, list[int]]:
        """Return model/scale pairs proven by completed no-watermark jobs.

        The task database is the durable source of truth for runs completed
        through this service.  Failed, cancelled, legacy, and unverified
        results must never promote a catalogue entry.
        """
        with self.db() as database:
            rows = database.execute("SELECT data FROM jobs").fetchall()
        verified: dict[str, set[int]] = {}
        for (raw,) in rows:
            try:
                job = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if (job.get("status") != "succeeded"
                    or job.get("watermark_verified") is not True
                    or job.get("export_provenance") not in VERIFIED_EXPORT_PROVENANCE):
                continue
            spec = job.get("spec")
            if not isinstance(spec, dict):
                continue
            if spec.get("enhancement") is False:
                continue
            model = spec.get("model")
            scale = spec.get("scale")
            if not isinstance(model, str) or not model or isinstance(scale, bool):
                continue
            try:
                scale = int(scale)
            except (TypeError, ValueError):
                continue
            if scale < 1:
                continue
            verified.setdefault(model, set()).add(scale)
        return {model: sorted(scales) for model, scales in verified.items()}

    def artifact(self, ident: str, name: str) -> Path:
        job = self.get(ident)
        if job.get("watermark_verified") is not True:
            raise FileNotFoundError("视频结果未通过无水印验收")
        if name not in {item["name"] for item in job.get("artifacts", [])}:
            raise FileNotFoundError("视频结果不存在")
        root = self.path(ident).resolve()
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            raise FileNotFoundError("视频结果不存在")
        return path
