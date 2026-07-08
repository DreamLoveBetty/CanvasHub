#!/usr/bin/env python3
"""
任务数据库模块 - 使用 SQLite 存储任务状态
"""

import sqlite3
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .app_config import get_database_path

DB_PATH = str(get_database_path())

EXTRA_COLUMNS = {
    'stage': 'TEXT',
    'progress_text': 'TEXT',
    'progress': 'REAL DEFAULT 0',
    'heartbeat_at': 'INTEGER',
    'first_byte_at': 'INTEGER',
    'bytes_received': 'INTEGER DEFAULT 0',
    'transport_error_type': 'TEXT',
    'ttfb_ms': 'INTEGER',
    'started_at': 'INTEGER',
    'finished_at': 'INTEGER',
    'result_files': 'TEXT',
    'error_code': 'TEXT DEFAULT ""',
    'display_error': 'TEXT DEFAULT ""',
    'error_category': 'TEXT DEFAULT ""',
    'raw_error': 'TEXT DEFAULT ""',
    'last_run_id': 'TEXT DEFAULT ""',
    'run_count': 'INTEGER DEFAULT 0',
}

GENERATION_RUN_COLUMNS = {
    'run_id': 'TEXT PRIMARY KEY',
    'task_id': 'TEXT NOT NULL',
    'task_type': 'TEXT',
    'provider': 'TEXT',
    'route': 'TEXT',
    'status': 'TEXT',
    'stage': 'TEXT',
    'progress_text': 'TEXT',
    'progress': 'REAL DEFAULT 0',
    'heartbeat_at': 'INTEGER',
    'first_byte_at': 'INTEGER',
    'bytes_received': 'INTEGER DEFAULT 0',
    'transport_error_type': 'TEXT',
    'ttfb_ms': 'INTEGER',
    'started_at': 'INTEGER',
    'finished_at': 'INTEGER',
    'prompt': 'TEXT',
    'params': 'TEXT',
    'parent_run_id': 'TEXT',
    'error': 'TEXT',
    'error_code': 'TEXT',
    'display_error': 'TEXT',
    'error_category': 'TEXT',
    'raw_error': 'TEXT',
    'error_type': 'TEXT',
    'result_file': 'TEXT',
    'result_files': 'TEXT',
    'image_count': 'INTEGER DEFAULT 0',
    'meta': 'TEXT',
    'created_at': 'INTEGER',
    'updated_at': 'INTEGER',
}

GENERATION_EVENT_COLUMNS = {
    'event_id': 'INTEGER PRIMARY KEY AUTOINCREMENT',
    'run_id': 'TEXT NOT NULL',
    'task_id': 'TEXT NOT NULL',
    'event_type': 'TEXT',
    'stage': 'TEXT',
    'severity': 'TEXT',
    'message': 'TEXT',
    'payload': 'TEXT',
    'created_at': 'INTEGER',
}


@contextmanager
def get_db():
    """数据库连接上下文管理器"""
    Path(DB_PATH).expanduser().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA foreign_keys = ON')
    except Exception:
        pass
    try:
        yield conn
    finally:
        conn.close()


def _ensure_column(conn, name, ddl):
    try:
        conn.execute(f'ALTER TABLE tasks ADD COLUMN {name} {ddl}')
        print(f"✅ 为现有任务添加 {name} 字段")
    except sqlite3.OperationalError as e:
        if 'duplicate column' in str(e).lower():
            pass
        else:
            raise


def _ensure_generation_run_column(conn, name, ddl):
    try:
        conn.execute(f'ALTER TABLE generation_runs ADD COLUMN {name} {ddl}')
    except sqlite3.OperationalError as e:
        if 'duplicate column' in str(e).lower():
            pass
        else:
            raise


def _ensure_generation_event_column(conn, name, ddl):
    try:
        conn.execute(f'ALTER TABLE generation_events ADD COLUMN {name} {ddl}')
    except sqlite3.OperationalError as e:
        if 'duplicate column' in str(e).lower():
            pass
        else:
            raise


def _decode_json_list(raw):
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _mirror_generation_run_fields(conn, task_id, fields):
    if not isinstance(fields, dict) or not fields:
        return
    run_id = str(fields.get('last_run_id') or '').strip()
    if not run_id:
        try:
            current = conn.execute('SELECT last_run_id FROM tasks WHERE task_id=?', (task_id,)).fetchone()
        except sqlite3.OperationalError:
            return
        run_id = str(current['last_run_id'] or '').strip() if current else ''
    if not run_id:
        return

    mapping = {
        'status': 'status',
        'stage': 'stage',
        'progress_text': 'progress_text',
        'progress': 'progress',
        'heartbeat_at': 'heartbeat_at',
        'first_byte_at': 'first_byte_at',
        'bytes_received': 'bytes_received',
        'transport_error_type': 'transport_error_type',
        'ttfb_ms': 'ttfb_ms',
        'started_at': 'started_at',
        'finished_at': 'finished_at',
        'result_file': 'result_file',
        'result_files': 'result_files',
        'error': 'error',
        'error_code': 'error_code',
        'display_error': 'display_error',
        'error_category': 'error_category',
        'raw_error': 'raw_error',
        'params': 'params',
        'type': 'task_type',
    }
    run_fields = {}
    for task_key, run_key in mapping.items():
        if task_key in fields and fields[task_key] is not None:
            run_fields[run_key] = fields[task_key]
    if not run_fields:
        return
    assignments = ', '.join(f'{key}=?' for key in run_fields.keys())
    conn.execute(
        f'UPDATE generation_runs SET {assignments}, updated_at=? WHERE run_id=?',
        list(run_fields.values()) + [int(time.time()), run_id],
    )


def init_db():
    """初始化数据库表"""
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                prompt TEXT,
                params TEXT,
                result_file TEXT,
                error TEXT,
                created_at INTEGER,
                updated_at INTEGER,
                type TEXT DEFAULT 'google-gen'
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS generation_runs (
                run_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                task_type TEXT,
                provider TEXT,
                route TEXT,
                status TEXT,
                stage TEXT,
                progress_text TEXT,
                heartbeat_at INTEGER,
                first_byte_at INTEGER,
                bytes_received INTEGER DEFAULT 0,
                transport_error_type TEXT,
                ttfb_ms INTEGER,
                started_at INTEGER,
                finished_at INTEGER,
                prompt TEXT,
                params TEXT,
                parent_run_id TEXT,
                error TEXT,
                error_code TEXT,
                display_error TEXT,
                error_category TEXT,
                raw_error TEXT,
                error_type TEXT,
                result_file TEXT,
                result_files TEXT,
                image_count INTEGER DEFAULT 0,
                meta TEXT,
                created_at INTEGER,
                updated_at INTEGER
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS generation_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES generation_runs(run_id) ON DELETE CASCADE,
                task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
                event_type TEXT,
                stage TEXT,
                severity TEXT,
                message TEXT,
                payload TEXT,
                created_at INTEGER
            )
        ''')

        _ensure_column(conn, 'type', 'TEXT DEFAULT "google-gen"')
        for col, ddl in EXTRA_COLUMNS.items():
            _ensure_column(conn, col, ddl)
        for col, ddl in GENERATION_RUN_COLUMNS.items():
            if col != 'run_id':
                _ensure_generation_run_column(conn, col, ddl)
        for col, ddl in GENERATION_EVENT_COLUMNS.items():
            if col != 'event_id':
                _ensure_generation_event_column(conn, col, ddl)

        conn.execute('CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_created ON tasks(created_at)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_type ON tasks(type)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_heartbeat ON tasks(heartbeat_at)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_generation_runs_task_id ON generation_runs(task_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_generation_runs_status ON generation_runs(status)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_generation_runs_created_at ON generation_runs(created_at)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_generation_events_run_id ON generation_events(run_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_generation_events_task_id ON generation_events(task_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_generation_events_created_at ON generation_events(created_at)')
        conn.commit()


def create_task(task_id, prompt, params, status='pending', task_type='google-gen'):
    """创建新任务"""
    now = int(time.time())
    with get_db() as conn:
        conn.execute(
            '''
            INSERT INTO tasks (
                task_id, status, prompt, params, created_at, updated_at, type,
                stage, progress_text, progress, heartbeat_at, bytes_received, started_at,
                error_code, display_error, error_category, raw_error, last_run_id, run_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                task_id,
                status,
                prompt,
                json.dumps(params),
                now,
                now,
                task_type,
                status,
                '',
                0,
                now,
                0,
                now,
                '',
                '',
                '',
                '',
                '',
                0,
            ),
        )
        conn.commit()


def update_task_fields(task_id, **fields):
    """按字段更新任务状态，忽略 None。"""
    cleaned = {k: v for k, v in fields.items() if v is not None}
    if not cleaned:
        return

    cleaned['updated_at'] = int(time.time())
    assignments = ', '.join(f'{k}=?' for k in cleaned.keys())
    values = list(cleaned.values()) + [task_id]

    with get_db() as conn:
        if cleaned.get('status') != 'canceled':
            current = conn.execute('SELECT status FROM tasks WHERE task_id=?', (task_id,)).fetchone()
            if current and current['status'] == 'canceled':
                return
        conn.execute(f'UPDATE tasks SET {assignments} WHERE task_id=?', values)
        _mirror_generation_run_fields(conn, task_id, cleaned)
        conn.commit()


def update_task_status(task_id, status, message=None, stage=None, **extra):
    """更新任务状态（兼容旧调用，支持附加字段）"""
    payload = {'status': status}
    if stage is not None:
        payload['stage'] = stage
    else:
        payload['stage'] = status
    if message is not None:
        payload['progress_text'] = message
    if 'heartbeat_at' not in extra:
        payload['heartbeat_at'] = int(time.time())
    payload.update(extra)
    update_task_fields(task_id, **payload)


def update_task(task_id, status, result_file=None, error=None, **extra):
    """更新任务状态"""
    payload = {
        'status': status,
        'result_file': result_file,
        'error': error,
    }
    status_key = str(status or '').strip()
    if status_key in ('succeeded', 'succeeded_no_telegram'):
        payload['error'] = ''
        payload['error_code'] = ''
        payload['display_error'] = ''
        payload['error_category'] = ''
        payload['raw_error'] = ''
    elif status_key in ('failed', 'telegram_failed', 'canceled') and error is not None:
        payload['display_error'] = error
        payload['raw_error'] = error
    if status in ('succeeded', 'succeeded_no_telegram', 'failed', 'telegram_failed', 'canceled'):
        payload.setdefault('finished_at', int(time.time()))
    payload.update(extra)
    update_task_fields(task_id, **payload)


def get_task(task_id):
    """获取单个任务"""
    with get_db() as conn:
        row = conn.execute(
            'SELECT * FROM tasks WHERE task_id=?', (task_id,)
        ).fetchone()
        if row:
            task = dict(row)
            task['params'] = json.loads(task['params']) if task['params'] else {}
            task['result_files'] = _decode_json_list(task.get('result_files'))
            return task
        return None


def get_all_tasks(limit=50, offset=0):
    """获取所有任务（按创建时间倒序，支持分页）"""
    with get_db() as conn:
        rows = conn.execute(
            'SELECT * FROM tasks ORDER BY created_at DESC LIMIT ? OFFSET ?', (limit, offset)
        ).fetchall()
        tasks = []
        for row in rows:
            task = dict(row)
            task['params'] = json.loads(task['params']) if task['params'] else {}
            task['result_files'] = _decode_json_list(task.get('result_files'))
            tasks.append(task)
        return tasks


def delete_task(task_id):
    """按 task_id 删除单条任务"""
    with get_db() as conn:
        conn.execute('DELETE FROM tasks WHERE task_id=?', (task_id,))
        conn.commit()
        return conn.total_changes


def restore_task_snapshot(task):
    """Restore a task row from a snapshot dictionary."""
    if not task or not task.get('task_id'):
        return 0
    payload = dict(task)
    if isinstance(payload.get('params'), dict):
        payload['params'] = json.dumps(payload.get('params'), ensure_ascii=False)
    if isinstance(payload.get('result_files'), list):
        payload['result_files'] = json.dumps(payload.get('result_files'), ensure_ascii=False)

    with get_db() as conn:
        columns = [
            row['name']
            for row in conn.execute('PRAGMA table_info(tasks)').fetchall()
        ]
        clean = {key: payload.get(key) for key in columns if key in payload}
        if 'updated_at' in columns:
            clean['updated_at'] = int(time.time())
        if not clean.get('task_id'):
            return 0
        placeholders = ', '.join('?' for _ in clean)
        assignments = ', '.join(f'{key}=excluded.{key}' for key in clean if key != 'task_id')
        if not assignments:
            return 0
        sql = (
            f"INSERT INTO tasks ({', '.join(clean.keys())}) VALUES ({placeholders}) "
            f"ON CONFLICT(task_id) DO UPDATE SET {assignments}"
        )
        conn.execute(sql, list(clean.values()))
        conn.commit()
        return conn.total_changes


def get_pending_tasks():
    """获取所有待处理任务"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status='pending' ORDER BY created_at"
        ).fetchall()
        tasks = []
        for row in rows:
            task = dict(row)
            task['params'] = json.loads(task['params']) if task['params'] else {}
            tasks.append(task)
        return tasks


def fail_stale_processing_tasks(max_age_seconds=30 * 60):
    """Fail orphaned in-progress tasks after a server restart."""
    now = int(time.time())
    max_age = int(max_age_seconds)
    cutoff = now - max_age
    if max_age <= 0:
        cutoff = now + 1
    message = '生成进程已中断，请重新提交任务'
    with get_db() as conn:
        stale_rows = conn.execute(
            '''
            SELECT task_id, last_run_id
            FROM tasks
            WHERE status IN ('processing', 'preparing', 'fallback_running')
              AND COALESCE(heartbeat_at, updated_at, created_at, 0) < ?
            ''',
            (cutoff,),
        ).fetchall()
        conn.execute(
            '''
            UPDATE tasks
            SET status='failed',
                stage='failed',
                progress_text=?,
                error=?,
                display_error=?,
                raw_error=?,
                error_code='task.orphaned',
                error_category='orphaned',
                updated_at=?,
                heartbeat_at=?,
                finished_at=?,
                transport_error_type='OrphanedTask'
            WHERE status IN ('processing', 'preparing', 'fallback_running')
              AND COALESCE(heartbeat_at, updated_at, created_at, 0) < ?
            ''',
            (message, message, message, message, now, now, now, cutoff),
        )
        run_ids = [str(row['last_run_id'] or '').strip() for row in stale_rows if str(row['last_run_id'] or '').strip()]
        if run_ids:
            placeholders = ', '.join('?' for _ in run_ids)
            conn.execute(
                f'''
                UPDATE generation_runs
                SET status='failed',
                    stage='failed',
                    error=?,
                    display_error=?,
                    raw_error=?,
                    error_code='task.orphaned',
                    error_category='orphaned',
                    finished_at=?,
                    updated_at=?
                WHERE run_id IN ({placeholders})
                ''',
                [message, message, message, now, now, *run_ids],
            )
        changed = conn.total_changes
        conn.commit()
        return changed


def cleanup_old_tasks(days=7):
    """清理旧任务（保留最近 7 天）"""
    cutoff = int(time.time()) - (days * 24 * 60 * 60)
    with get_db() as conn:
        conn.execute('DELETE FROM tasks WHERE created_at < ?', (cutoff,))
        conn.commit()
        return conn.total_changes


def vacuum_tasks_db():
    """Compact tasks.db outside an explicit transaction."""
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    try:
        conn.execute('PRAGMA busy_timeout = 5000')
        conn.execute('VACUUM')
    finally:
        conn.close()


if __name__ == '__main__':
    init_db()
    print("✅ 数据库初始化成功")

    create_task('test_001', 'Test prompt', {'ratio': '1:1'})
    print("✅ 测试任务创建成功")

    task = get_task('test_001')
    print(f"✅ 查询任务：{task['status']}")

    update_task('test_001', 'succeeded', 'test.png', stage='done', progress_text='完成')
    task = get_task('test_001')
    print(f"✅ 更新任务：{task['status']}, {task['result_file']}")
