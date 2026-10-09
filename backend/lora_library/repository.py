"""Durable descriptive metadata, never model weights or the derived file index."""
from __future__ import annotations

from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
import threading


class ConflictError(ValueError):
    pass


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Repository:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "library.db"
        self.lock = threading.RLock()
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS records (
                    asset_id TEXT PRIMARY KEY, local_json TEXT NOT NULL DEFAULT '{}',
                    remote_json TEXT NOT NULL DEFAULT '{}', manual_json TEXT NOT NULL DEFAULT '{}',
                    binding_json TEXT NOT NULL DEFAULT '{}', sync_json TEXT NOT NULL DEFAULT '{}',
                    revision INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS members (
                    asset_id TEXT NOT NULL, engine TEXT NOT NULL, info_json TEXT NOT NULL,
                    present INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(asset_id, engine));
                CREATE TABLE IF NOT EXISTS previews (
                    id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, kind TEXT NOT NULL,
                    source_url TEXT NOT NULL DEFAULT '', caption TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS preview_asset ON previews(asset_id);
                CREATE TABLE IF NOT EXISTS preferences (id INTEGER PRIMARY KEY CHECK(id=1),
                    payload TEXT NOT NULL);
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connection(self):
        # `with sqlite3.connect(...)` alone does not close the connection.
        with self.lock, closing(sqlite3.connect(self.path, timeout=15)) as db, db:
            db.row_factory = sqlite3.Row
            yield db

    def reconcile(self, engine, items):
        with self.connection() as db:
            db.execute("UPDATE members SET present=0 WHERE engine=?", (engine,))
            for item in items:
                identity = item["asset_id"]
                db.execute("INSERT OR IGNORE INTO records(asset_id) VALUES(?)", (identity,))
                db.execute("INSERT INTO members VALUES(?,?,?,1) ON CONFLICT(asset_id,engine) "
                           "DO UPDATE SET info_json=excluded.info_json,present=1",
                           (identity, engine, encode(item)))

    def records(self):
        with self.connection() as db:
            rows = db.execute("SELECT * FROM records").fetchall()
            members = db.execute("SELECT * FROM members").fetchall()
            previews = db.execute("SELECT * FROM previews ORDER BY created_at,id").fetchall()
        result = {row["asset_id"]: {"asset_id": row["asset_id"], "revision": row["revision"],
                  **{key: json.loads(row[key + "_json"]) for key in
                     ("local", "remote", "manual", "binding", "sync")}, "members": [], "previews": []}
                  for row in rows}
        for row in members:
            if row["asset_id"] in result:
                result[row["asset_id"]]["members"].append({"engine": row["engine"],
                    "present": bool(row["present"]), **json.loads(row["info_json"])})
        for row in previews:
            if row["asset_id"] in result:
                result[row["asset_id"]]["previews"].append(dict(row))
        return result

    def get(self, identity):
        record = self.records().get(identity)
        if record is None:
            raise ValueError("LoRA 资料不存在，请先扫描本地目录")
        return record

    def write_source(self, identity, source, value):
        if source not in {"local", "remote", "binding", "sync"}:
            raise ValueError("未知资料来源")
        with self.connection() as db:
            if not db.execute(f"UPDATE records SET {source}_json=? WHERE asset_id=?",
                              (encode(value), identity)).rowcount:
                raise ValueError("LoRA 资料不存在")

    def edit(self, identity, changes, reset, revision):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT manual_json,revision FROM records WHERE asset_id=?", (identity,)).fetchone()
            if not row:
                raise ValueError("LoRA 资料不存在")
            if revision is None or row["revision"] != revision:
                raise ConflictError("资料已在其他窗口修改，请重新打开详情后编辑")
            value = json.loads(row["manual_json"])
            for key in reset:
                value.pop(key, None)
            value.update(changes)
            db.execute("UPDATE records SET manual_json=?,revision=revision+1 WHERE asset_id=?",
                       (encode(value), identity))

    def add_preview(self, item):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM previews WHERE asset_id=?", (item["asset_id"],)).fetchone()[0] >= 24:
                raise ValueError("每个 LoRA 最多保留 24 张示例图")
            db.execute("INSERT INTO previews VALUES(:id,:asset_id,:kind,:source_url,:caption,:created_at)", item)

    def drop_preview(self, identity):
        with self.connection() as db:
            db.execute("DELETE FROM previews WHERE id=?", (identity,))

    def preferences(self, updates=None):
        with self.connection() as db:
            row = db.execute("SELECT payload FROM preferences WHERE id=1").fetchone()
            value = json.loads(row[0]) if row else {"auto_sync": False}
            if updates is not None:
                value.update(updates)
                db.execute("INSERT INTO preferences VALUES(1,?) ON CONFLICT(id) "
                           "DO UPDATE SET payload=excluded.payload", (encode(value),))
        return value
