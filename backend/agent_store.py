#!/usr/bin/env python3
"""SQLite persistence for supervised Agent runs.

Agent state is deliberately kept in its own tables so the existing generation
task schema and history semantics remain untouched.  The tables live in the
configured tasks database, which keeps desktop data portable and covered by
the existing database permission handling.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .app_config import get_database_path


_WRITE_LOCK = threading.RLock()
_JSON_COLUMNS = {"request_json", "context_json", "plan_json", "result_json", "control_json", "payload"}
_SECRET_KEY_RE = re.compile(r"(?:token|secret|password|api[_-]?key|auth[_-]?key|authorization|cookie)", re.I)
_MAX_TEXT = 30_000
_MAX_DEPTH = 6


def agent_db_path() -> Path:
    """Return the current database path, allowing tests/config overrides."""
    override = str(os.environ.get("CANVASHUB_AGENT_DB") or "").strip()
    return Path(override).expanduser().resolve() if override else Path(get_database_path()).expanduser().resolve()


def _safe_value(value: Any, depth: int = 0, key: str = "") -> Any:
    """Bound persisted payloads and remove credential-like fields."""
    if _SECRET_KEY_RE.search(str(key or "")):
        return "[redacted]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        text = value
        if text.startswith("data:"):
            return "[image-data omitted]"
        if len(text) > _MAX_TEXT:
            return f"{text[:_MAX_TEXT]}\n...[truncated]"
        return text
    if depth >= _MAX_DEPTH:
        return "[nested value omitted]"
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(item, depth + 1) for item in list(value)[:160]]
    if isinstance(value, dict):
        return {
            str(item_key): _safe_value(item_value, depth + 1, str(item_key))
            for item_key, item_value in list(value.items())[:200]
        }
    return str(value)[:_MAX_TEXT]


def _dump(value: Any) -> str:
    return json.dumps(_safe_value(value), ensure_ascii=False, separators=(",", ":"), default=str)


def _load(raw: Any, fallback: Any) -> Any:
    if raw in (None, ""):
        return fallback
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return fallback


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = agent_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout = 15000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
    except sqlite3.DatabaseError:
        pass
    try:
        yield conn
    finally:
        conn.close()


def init_agent_store() -> None:
    """Create/migrate Agent tables."""
    with _WRITE_LOCK, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_runs (
                run_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'agent',
                goal TEXT NOT NULL,
                request_json TEXT NOT NULL DEFAULT '{}',
                context_json TEXT NOT NULL DEFAULT '{}',
                plan_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                control_json TEXT NOT NULL DEFAULT '{}',
                current_step INTEGER NOT NULL DEFAULT 0,
                waiting_action_id TEXT NOT NULL DEFAULT '',
                task_id TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                started_at INTEGER,
                finished_at INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
                seq INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT '',
                step_index INTEGER,
                message TEXT NOT NULL DEFAULT '',
                payload TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL,
                UNIQUE(run_id, seq)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_status ON agent_runs(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_updated ON agent_runs(updated_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_events_run_seq ON agent_events(run_id, seq)")
        conn.commit()


def _decode_run(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    for column, fallback in (
        ("request_json", {}),
        ("context_json", {}),
        ("plan_json", {}),
        ("result_json", {}),
        ("control_json", {}),
    ):
        value = _load(item.pop(column, ""), fallback)
        item[column[:-5]] = value
    item["request"] = item.pop("request", {})
    item["context"] = item.pop("context", {})
    item["plan"] = item.pop("plan", {})
    item["result"] = item.pop("result", {})
    item["control"] = item.pop("control", {})
    # Keep the public response snake_case and expose a compact alias only at
    # the boundary if a consumer needs to inspect the latest event.
    return item


def _decode_event(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    item = dict(row)
    item["payload"] = _load(item.get("payload"), {})
    return item


def create_run(
    run_id: str,
    *,
    goal: str,
    request: dict[str, Any],
    context: dict[str, Any],
    plan: dict[str, Any],
    status: str = "awaiting_approval",
    mode: str = "agent",
) -> dict[str, Any]:
    now = int(time.time())
    init_agent_store()
    with _WRITE_LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_runs (
                run_id, status, mode, goal, request_json, context_json, plan_json,
                result_json, control_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(run_id),
                str(status),
                str(mode),
                str(goal),
                _dump(request),
                _dump(context),
                _dump(plan),
                _dump({}),
                _dump({"pause_requested": False, "cancel_requested": False}),
                now,
                now,
            ),
        )
        conn.commit()
    return get_run(run_id) or {}


def get_run(run_id: str) -> dict[str, Any] | None:
    if not run_id:
        return None
    init_agent_store()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM agent_runs WHERE run_id=?", (str(run_id),)).fetchone()
    return _decode_run(row)


def list_runs(limit: int = 20, offset: int = 0, status: str = "") -> list[dict[str, Any]]:
    init_agent_store()
    limit = max(1, min(int(limit or 20), 100))
    offset = max(0, int(offset or 0))
    with _connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM agent_runs WHERE status=? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (str(status), limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM agent_runs ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
    return [_decode_run(row) for row in rows if row is not None]


def update_run(run_id: str, **fields: Any) -> dict[str, Any] | None:
    if not run_id or not fields:
        return get_run(run_id)
    init_agent_store()
    column_map = {
        "request": "request_json",
        "context": "context_json",
        "plan": "plan_json",
        "result": "result_json",
        "control": "control_json",
        "run_id": "run_id",
        "status": "status",
        "mode": "mode",
        "goal": "goal",
        "current_step": "current_step",
        "waiting_action_id": "waiting_action_id",
        "task_id": "task_id",
        "error": "error",
        "started_at": "started_at",
        "finished_at": "finished_at",
    }
    assignments: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        column = column_map.get(key)
        if not column or key == "run_id":
            continue
        assignments.append(f"{column}=?")
        values.append(_dump(value) if column.endswith("_json") else value)
    if not assignments:
        return get_run(run_id)
    assignments.append("updated_at=?")
    values.extend([int(time.time()), str(run_id)])
    with _WRITE_LOCK, _connect() as conn:
        conn.execute(f"UPDATE agent_runs SET {', '.join(assignments)} WHERE run_id=?", values)
        conn.commit()
    return get_run(run_id)


def append_event(
    run_id: str,
    event_type: str,
    *,
    status: str = "",
    step_index: int | None = None,
    message: str = "",
    payload: Any = None,
) -> dict[str, Any]:
    init_agent_store()
    now = int(time.time())
    with _WRITE_LOCK, _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT COALESCE(MAX(seq), 0) AS seq FROM agent_events WHERE run_id=?", (str(run_id),)).fetchone()
        seq = int(row["seq"] if row else 0) + 1
        cursor = conn.execute(
            """
            INSERT INTO agent_events (
                run_id, seq, event_type, status, step_index, message, payload, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(run_id),
                seq,
                str(event_type),
                str(status or ""),
                step_index,
                str(message or ""),
                _dump(payload if payload is not None else {}),
                now,
            ),
        )
        conn.execute("UPDATE agent_runs SET updated_at=? WHERE run_id=?", (now, str(run_id)))
        conn.commit()
        event_id = cursor.lastrowid
    return _decode_event({
        "event_id": event_id,
        "run_id": str(run_id),
        "seq": seq,
        "event_type": str(event_type),
        "status": str(status or ""),
        "step_index": step_index,
        "message": str(message or ""),
        "payload": _dump(payload if payload is not None else {}),
        "created_at": now,
    }) or {}


def list_events(run_id: str, *, since: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    init_agent_store()
    since = max(0, int(since or 0))
    limit = max(1, min(int(limit or 200), 1000))
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_events WHERE run_id=? AND seq>? ORDER BY seq ASC LIMIT ?",
            (str(run_id), since, limit),
        ).fetchall()
    return [_decode_event(row) for row in rows if row is not None]


def latest_event(run_id: str) -> dict[str, Any] | None:
    init_agent_store()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM agent_events WHERE run_id=? ORDER BY seq DESC LIMIT 1",
            (str(run_id),),
        ).fetchone()
    return _decode_event(row)


def mark_interrupted_runs() -> int:
    """Mark non-terminal runs as paused after a process restart."""
    init_agent_store()
    active = ("running", "waiting_for_action", "rolling_back")
    now = int(time.time())
    with _WRITE_LOCK, _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        placeholders = ",".join("?" for _ in active)
        rows = conn.execute(
            f"SELECT run_id, status, control_json FROM agent_runs WHERE status IN ({placeholders})",
            active,
        ).fetchall()
        for row in rows:
            control = _load(row["control_json"], {})
            if not isinstance(control, dict):
                control = {}
            control.update({
                "pause_requested": True,
                "recovered_after_restart": True,
                "interrupted_status": row["status"],
            })
            if row["status"] == "rolling_back":
                control["operation"] = "rollback"
            else:
                control.setdefault("operation", "execute")
            conn.execute(
                """
                UPDATE agent_runs
                SET status='paused', control_json=?, error=?, updated_at=?
                WHERE run_id=?
                """,
                (
                    _dump(control),
                    "服务重启后已暂停，点击继续可恢复。",
                    now,
                    row["run_id"],
                ),
            )
        conn.commit()
    return len(rows)


__all__ = [
    "agent_db_path",
    "init_agent_store",
    "create_run",
    "get_run",
    "list_runs",
    "update_run",
    "append_event",
    "list_events",
    "latest_event",
    "mark_interrupted_runs",
]
