"""Independent SQLite persistence. Stable ids do not change with access tokens."""

from __future__ import annotations
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .errors import GoogleError


class GoogleStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        with self.db() as db:
            db.execute(
                'CREATE TABLE IF NOT EXISTS google_accounts (id TEXT PRIMARY KEY, identity TEXT UNIQUE, data TEXT NOT NULL)'
            )
            db.execute(
                'CREATE TABLE IF NOT EXISTS google_options (key TEXT PRIMARY KEY, value TEXT NOT NULL)'
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @contextmanager
    def db(self):
        with self.lock:
            conn = sqlite3.connect(self.path, timeout=10)
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def enabled(self):
        with self.db() as db:
            row = db.execute(
                "SELECT value FROM google_options WHERE key='enabled'"
            ).fetchone()
        return bool(row and row[0] == 'true')

    def set_enabled(self, enabled):
        if not isinstance(enabled, bool):
            raise GoogleError('enabled 必须为布尔值', 400, 'invalid_config')
        with self.db() as db:
            db.execute(
                "INSERT OR REPLACE INTO google_options VALUES ('enabled', ?)",
                (json.dumps(enabled),),
            )

    def private_accounts(self):
        with self.db() as db:
            return [
                json.loads(row[0])
                for row in db.execute('SELECT data FROM google_accounts ORDER BY rowid')
            ]

    def get(self, account_id):
        with self.db() as db:
            row = db.execute(
                'SELECT data FROM google_accounts WHERE id=?', (str(account_id),)
            ).fetchone()
        if not row:
            raise GoogleError('Google 账号不存在', 404, 'account_not_found')
        return json.loads(row[0])

    @staticmethod
    def public(a):
        return {
            k: a.get(k)
            for k in (
                'id',
                'email',
                'enabled',
                'expires_at',
                'models',
                'models_checked_at',
                'last_error',
                'last_used_at',
                'success_count',
                'failure_count',
                'requires_relogin',
            )
        } | {
            'refreshable': bool(a.get('refresh_token')),
            'project_configured': bool(a.get('project_id')),
        }

    def list_public(self):
        return [self.public(a) for a in self.private_accounts()]

    @staticmethod
    def validate_import(item):
        if not isinstance(item, dict):
            raise GoogleError('账号必须为 JSON 对象', 400, 'invalid_account')
        token = item.get('token') if isinstance(item.get('token'), dict) else item
        values = {}
        for key in ('refresh_token', 'access_token'):
            value = token.get(key) or ''
            if not isinstance(value, str) or len(value) > 32768:
                raise GoogleError('Token 格式无效', 400, 'invalid_account')
            values[key] = value.strip()
        if not values['refresh_token'] and not values['access_token']:
            raise GoogleError(
                '需要 refresh_token 或 access_token', 400, 'invalid_account'
            )
        try:
            values['expires_at'] = int(
                token.get('expires_at')
                or token.get('expiry_timestamp')
                or (
                    int(time.time()) + int(token['expires_in'])
                    if token.get('expires_in')
                    else 0
                )
            )
        except (ValueError, TypeError, OverflowError):
            raise GoogleError('Token 到期时间无效', 400, 'invalid_account') from None
        for key, maximum in (('email', 254), ('project_id', 256)):
            value = item.get(key) or token.get(key) or ''
            if not isinstance(value, str) or len(value) > maximum:
                raise GoogleError('账号元数据格式无效', 400, 'invalid_account')
            values[key] = value.strip()
        return values

    def import_account(self, item):
        return self.import_accounts([item])[0]

    def import_accounts(self, items):
        values = [self.validate_import(item) for item in items]
        results = []
        with self.db() as db:
            for value in values:
                identity = hashlib.sha256(
                    (value['refresh_token'] or value['access_token']).encode()
                ).hexdigest()
                existing = db.execute(
                    'SELECT data FROM google_accounts WHERE identity=?', (identity,)
                ).fetchone()
                old = json.loads(existing[0]) if existing else {}
                a = dict(old, **value)
                a.update(
                    id=old.get('id') or uuid.uuid4().hex,
                    email=value['email'] or old.get('email', ''),
                    project_id=value['project_id'] or old.get('project_id', ''),
                    enabled=old.get('enabled', True),
                    requires_relogin=False,
                    last_error='',
                    models=old.get('models', []),
                    models_checked_at=old.get('models_checked_at', 0),
                    success_count=old.get('success_count', 0),
                    failure_count=old.get('failure_count', 0),
                )
                db.execute(
                    'INSERT OR REPLACE INTO google_accounts VALUES (?,?,?)',
                    (a['id'], identity, json.dumps(a)),
                )
                results.append(self.public(a))
        return results

    def patch(self, account_id, values):
        # Caller supplies internal, validated fields; account identity cannot be reassigned.
        with self.db() as db:
            row = db.execute(
                'SELECT data FROM google_accounts WHERE id=?', (str(account_id),)
            ).fetchone()
            if not row:
                raise GoogleError('Google 账号不存在', 404, 'account_not_found')
            a = json.loads(row[0])
            a.update({k: v for k, v in values.items() if k != 'id'})
            identity = hashlib.sha256(
                (a.get('refresh_token') or a.get('access_token')).encode()
            ).hexdigest()
            db.execute(
                'UPDATE google_accounts SET data=?, identity=? WHERE id=?',
                (json.dumps(a), identity, account_id),
            )
        return a

    def delete(self, account_id):
        with self.db() as db:
            if not db.execute(
                'DELETE FROM google_accounts WHERE id=?', (str(account_id),)
            ).rowcount:
                raise GoogleError('Google 账号不存在', 404, 'account_not_found')
