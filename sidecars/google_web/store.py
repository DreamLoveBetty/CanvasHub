"""Private Web Cookie storage. No dependency on either OAuth account store."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager, closing
from .errors import WebError

COOKIE_NAMES = {
    '__Secure-1PSID', '__Secure-1PSIDTS', '__Secure-1PSIDCC', '__Secure-1PSIDRTS',
    '__Secure-1PSIDRCC', '__Secure-3PSID', '__Secure-3PSIDTS', '__Secure-3PSIDCC',
    '__Secure-3PSIDRTS', '__Secure-3PSIDRCC', 'NID', 'SID', 'HSID', 'SSID',
    'APISID', 'SAPISID', 'COMPASS', '__Secure-STRP', 'AEC',
}
APEX_COOKIE_NAMES = COOKIE_NAMES - {'COMPASS', '__Secure-STRP'}
GEMINI_COOKIE_NAMES = {'COMPASS', '__Secure-STRP'}


def cookie_domain_kind(domain):
    host = str(domain or '.google.com').lstrip('.').lower()
    if host == 'google.com':
        return 'google_apex'
    if host == 'gemini.google.com' or host.endswith('.gemini.google.com'):
        return 'gemini_host'
    if host == 'google.com' or host.endswith('.google.com'):
        return 'other_google'
    return 'other'


def cookie_domain_score(name, kind):
    if name in GEMINI_COOKIE_NAMES:
        return {'gemini_host': 3, 'google_apex': 2, 'other_google': 1}.get(kind, 0)
    if name in APEX_COOKIE_NAMES:
        return {'google_apex': 3, 'other_google': 2, 'gemini_host': 1}.get(kind, 0)
    return {'google_apex': 2, 'gemini_host': 2, 'other_google': 1}.get(kind, 0)


def _cookie_items(value):
    if isinstance(value, dict) and 'cookies' in value:
        value = value['cookies']
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [{'name': key, 'value': val, 'domain': '.google.com'} for key, val in value.items()]
    raise WebError('需要有效 Cookie JSON', 400, 'invalid_cookies')


def cookie_source_stats(value):
    counts = {}
    input_rows = 0
    for item in _cookie_items(value):
        if not isinstance(item, dict):
            continue
        domain = str(item.get('domain') or '.google.com')
        host = domain.lstrip('.').lower()
        if host != 'google.com' and not host.endswith('.google.com'):
            continue
        name = item.get('name')
        if name not in COOKIE_NAMES:
            continue
        input_rows += 1
        kind = cookie_domain_kind(domain)
        names = counts.setdefault(name, {})
        names[kind] = names.get(kind, 0) + 1
    duplicates = {name: kinds for name, kinds in counts.items() if sum(kinds.values()) > 1}
    return {
        'input_rows': input_rows,
        'kept_names': len(counts),
        'duplicate_names': duplicates,
    }


def normalize_cookies(value):
    items = _cookie_items(value)
    cookies = {}
    scores = {}
    for item in items:
        if not isinstance(item, dict):
            raise WebError('Cookie JSON 格式无效', 400, 'invalid_cookies')
        domain = str(item.get('domain') or '.google.com')
        host = domain.lstrip('.').lower()
        if host != 'google.com' and not host.endswith('.google.com'):
            continue
        expiry = item.get('expirationDate', item.get('expires'))
        try:
            if expiry and float(expiry) > 0 and float(expiry) < time.time():
                continue
        except (ValueError, TypeError):
            pass
        name = item.get('name')
        kind = cookie_domain_kind(domain)
        score = cookie_domain_score(name, kind)
        if name in cookies and score < scores[name]:
            continue
        if name in cookies and score == scores[name]:
            continue
        cookies[name] = item.get('value')
        scores[name] = score
    result = {}
    for key, value in cookies.items():
        if key not in COOKIE_NAMES:
            continue
        if not isinstance(value, str) or not value or len(value) > 32768 or '\n' in value or '\r' in value:
            raise WebError('Cookie 字段无效', 400, 'invalid_cookies')
        result[key] = value
    if not result.get('__Secure-1PSID'):
        raise WebError('Cookie 缺少有效的 __Secure-1PSID', 400, 'invalid_cookies')
    return result


def sanitize_cookie_records(value):
    records = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        name, val = item.get('name'), item.get('value')
        if (not isinstance(name, str) or not name or len(name) > 256 or ' ' in name
                or not isinstance(val, str) or not val or len(val) > 32768 or '\n' in name or '\r' in name
                or '\n' in val or '\r' in val):
            continue
        domain = str(item.get('domain') or '.google.com')
        host = domain.lstrip('.').lower()
        if host != 'google.com' and not host.endswith('.google.com'):
            continue
        rec = {'name': name, 'value': val, 'domain': domain, 'path': str(item.get('path') or '/') or '/'}
        expiry = item.get('expires', item.get('expirationDate'))
        if expiry is not None:
            rec['expires'] = expiry
        records.append(rec)
    return records


def cookie_records_from_jar(jar):
    records = []
    for cookie in jar or []:
        domain = str(getattr(cookie, 'domain', None) or '.google.com')
        host = domain.lstrip('.').lower()
        if host != 'google.com' and not host.endswith('.google.com'):
            continue
        expired = getattr(cookie, 'is_expired', None)
        if callable(expired) and expired():
            continue
        records.extend(sanitize_cookie_records([{
            'name': getattr(cookie, 'name', None),
            'value': getattr(cookie, 'value', None),
            'domain': domain,
            'path': getattr(cookie, 'path', None) or '/',
            'expires': getattr(cookie, 'expires', None),
        }]))
    return records



class WebStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS web_accounts (id TEXT PRIMARY KEY, identity TEXT UNIQUE, data TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS web_options (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS web_credentials (id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE, data TEXT NOT NULL)')
            # One canonical Cookie record per browser session; preserve old task IDs.
            for account_id, raw in db.execute('SELECT id,data FROM web_accounts').fetchall():
                account = json.loads(raw)
                if 'cookies' not in account:
                    continue
                cookies = account.pop('cookies')
                revision = account.pop('revision', 1)
                fingerprint = self.fingerprint(cookies)
                row = db.execute('SELECT id FROM web_credentials WHERE fingerprint=?', (fingerprint,)).fetchone()
                credential_id = row[0] if row else uuid.uuid4().hex
                if not row:
                    db.execute('INSERT INTO web_credentials VALUES (?,?,?)', (credential_id, fingerprint,
                        json.dumps({'cookies': cookies, 'revision': revision})))
                account.update(credential_id=credential_id, authuser=account.get('authuser', 0),
                               expected_email=account.get('expected_email') or account.get('email') or '')
                db.execute('UPDATE web_accounts SET data=? WHERE id=?', (json.dumps(account), account_id))
        os.chmod(self.path, 0o600)

    @contextmanager
    def db(self):
        with self.lock, closing(sqlite3.connect(self.path, timeout=15)) as db:
            with db:
                yield db

    def enabled(self):
        with self.db() as db:
            row = db.execute("SELECT value FROM web_options WHERE key='enabled'").fetchone()
        return bool(row and row[0] == 'true')

    def set_enabled(self, value):
        if not isinstance(value, bool):
            raise WebError('enabled 必须为布尔值', 400, 'invalid_config')
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO web_options VALUES ('enabled', ?)", (json.dumps(value),))

    def private_accounts(self):
        with self.db() as db:
            return [self.hydrate(db, json.loads(row[0])) for row in db.execute('SELECT data FROM web_accounts ORDER BY rowid').fetchall()]

    @staticmethod
    def fingerprint(cookies):
        return hashlib.sha256(cookies['__Secure-1PSID'].encode()).hexdigest()

    @staticmethod
    def hydrate(db, account):
        row = db.execute('SELECT data FROM web_credentials WHERE id=?', (account['credential_id'],)).fetchone()
        if not row:
            raise WebError('Web 会话不存在，请重新导入', 409, 'web_auth_expired')
        return dict(account, **json.loads(row[0]))

    def get(self, account_id):
        with self.db() as db:
            row = db.execute('SELECT data FROM web_accounts WHERE id=?', (str(account_id),)).fetchone()
            if not row:
                raise WebError('Web 账号不存在', 404, 'account_not_found')
            return self.hydrate(db, json.loads(row[0]))

    @staticmethod
    def public(account):
        return {key: account.get(key) for key in (
            'id', 'label', 'display_name', 'email', 'enabled', 'checked_at', 'last_used_at', 'last_error',
            'success_count', 'failure_count', 'requires_relogin', 'cooldown_until',
            'authuser', 'source_profile',
        )}

    def list_public(self):
        return [self.public(account) for account in self.private_accounts()]


    def preview_import(self, items):
        if not isinstance(items, list) or not 1 <= len(items) <= 50:
            raise WebError('需要 1–50 个 Web 账号', 400, 'invalid_account')
        fingerprints, snapshot_names = set(), set()
        for item in items:
            if not isinstance(item, dict):
                raise WebError('账号必须为 JSON 对象', 400, 'invalid_account')
            cookies = normalize_cookies(item.get('cookies', item))
            fingerprints.add(self.fingerprint(cookies))
            for record in sanitize_cookie_records(item.get('cookie_records')):
                if record.get('name'):
                    snapshot_names.add(record['name'])
            snapshot_names.update(name for name in cookies)
        if len(fingerprints) != 1:
            raise WebError('同一浏览器会话的 Cookie 不一致，请统一后导入', 400, 'invalid_account')
        fingerprint = next(iter(fingerprints))
        with self.db() as db:
            row = db.execute('SELECT id FROM web_credentials WHERE fingerprint=?', (fingerprint,)).fetchone()
            session_count = db.execute('SELECT COUNT(*) FROM web_credentials').fetchone()[0]
            account_count = db.execute('SELECT COUNT(*) FROM web_accounts').fetchone()[0]
        matched = row[0] if row else None
        return {
            'ok': True,
            'discovered': len(items),
            'fingerprint_matches_existing': bool(matched),
            'would_create_new_session': not bool(matched),
            'matched_credential': (matched[:8] + '…') if matched else None,
            'current_sessions': session_count,
            'current_accounts': account_count,
            'snapshot_name_count': len(snapshot_names),
            'snapshot_names': sorted(snapshot_names),
            'names_outside_legacy_allowlist': sorted(snapshot_names - COOKIE_NAMES),
        }

    def import_accounts(self, items, *, source_credential_id=None):
        if not isinstance(items, list) or not 1 <= len(items) <= 50:
            raise WebError('需要 1–50 个 Web 账号', 400, 'invalid_account')
        values, groups, group_records = [], {}, {}
        for item in items:
            if not isinstance(item, dict):
                raise WebError('账号必须为 JSON 对象', 400, 'invalid_account')
            cookies = normalize_cookies(item.get('cookies', item))
            label = item.get('label') or item.get('email') or ''
            if not isinstance(label, str) or len(label) > 120:
                raise WebError('账号名称无效', 400, 'invalid_account')
            slot = item.get('authuser', 0)
            if type(slot) is not int or not 0 <= slot < 100:
                raise WebError('Google 账号序号无效', 400, 'invalid_account')
            email = item.get('email') or ''
            name, profile = item.get('display_name') or '', item.get('source_profile') or ''
            if (not isinstance(email, str) or len(email) > 254 or (email and ('@' not in email or any(c.isspace() for c in email)))
                    or not isinstance(name, str) or len(name) > 120 or not isinstance(profile, str) or len(profile) > 120):
                raise WebError('Google 账号信息无效', 400, 'invalid_account')
            fingerprint = self.fingerprint(cookies)
            if fingerprint in groups and groups[fingerprint] != cookies:
                raise WebError('同一浏览器会话的 Cookie 不一致，请统一后导入', 400, 'invalid_account')
            groups[fingerprint] = cookies
            records = sanitize_cookie_records(item.get('cookie_records'))
            if records and fingerprint not in group_records:
                group_records[fingerprint] = records
            values.append((fingerprint, label.strip(), slot, email.strip(), name.strip(), profile.strip()))
        results = []
        with self.db() as db:
            if source_credential_id and (len(groups) != 1 or not db.execute('SELECT 1 FROM web_credentials WHERE id=?', (source_credential_id,)).fetchone()):
                raise WebError('原 Web 会话不存在，请重新导入', 409, 'account_not_found')
            credentials = {}
            for fingerprint, cookies in groups.items():
                row = db.execute('SELECT id,data FROM web_credentials WHERE fingerprint=?', (fingerprint,)).fetchone()
                if source_credential_id:
                    if row and row[0] != source_credential_id:
                        raise WebError('发现重复 Web 会话，请使用已有账号', 409, 'invalid_account')
                    row = db.execute('SELECT id,data FROM web_credentials WHERE id=?', (source_credential_id,)).fetchone()
                credential_id = row[0] if row else uuid.uuid4().hex
                revision = json.loads(row[1])['revision'] + 1 if row else 1
                payload = {'cookies': cookies, 'revision': revision}
                if group_records.get(fingerprint):
                    payload['cookie_records'] = group_records[fingerprint]
                db.execute('INSERT OR REPLACE INTO web_credentials VALUES (?,?,?)',
                           (credential_id, fingerprint, json.dumps(payload)))
                credentials[fingerprint] = credential_id
            for fingerprint, label, slot, email, name, profile in values:
                credential_id = credentials[fingerprint]
                candidates = [json.loads(row[0]) for row in db.execute('SELECT data FROM web_accounts')
                              if json.loads(row[0]).get('credential_id') == credential_id]
                old = next((a for a in candidates if email and str(a.get('expected_email') or '').casefold() == email.casefold()), None)
                if old is None:
                    old = next((a for a in candidates if a.get('authuser', 0) == slot and
                        (not email or not a.get('expected_email'))), {})
                expected_email = email or old.get('expected_email') or ''
                identity = credential_id + ':' + (expected_email.casefold() or str(slot))
                account = dict(old, id=old.get('id') or uuid.uuid4().hex,
                               label=label or old.get('label') or 'Web 账号',
                               display_name=name, email=email, expected_email=expected_email,
                               credential_id=credential_id, authuser=slot,
                               source_profile=profile or old.get('source_profile') or '',
                               enabled=old.get('enabled', True), checked_at=0,
                               requires_relogin=False, last_error='', cooldown_until=0,
                               success_count=old.get('success_count', 0), failure_count=old.get('failure_count', 0),
                               last_used_at=old.get('last_used_at', 0))
                if old:
                    db.execute('UPDATE web_accounts SET identity=?,data=? WHERE id=?', (identity, json.dumps(account), account['id']))
                else:
                    db.execute('INSERT INTO web_accounts VALUES (?,?,?)', (account['id'], identity, json.dumps(account)))
                results.append(self.public(account))
        return results

    def patch(self, account_id, values):
        if set(values) & {'cookies', 'revision', 'credential_id', 'authuser', 'expected_email'}:
            raise WebError('会话凭据与账号序号只能通过导入更新', 400, 'invalid_account')
        with self.db() as db:
            row = db.execute('SELECT data FROM web_accounts WHERE id=?', (account_id,)).fetchone()
            if not row:
                raise WebError('Web 账号不存在', 404, 'account_not_found')
            account = dict(json.loads(row[0]), **values)
            db.execute('UPDATE web_accounts SET data=? WHERE id=?', (json.dumps(account), account_id))
        return self.get(account_id)

    def record_identity(self, account_id, identity):
        identity = identity or {}
        email, name = str(identity.get('email') or '')[:254], str(identity.get('display_name') or '')[:120]
        with self.db() as db:
            row = db.execute('SELECT data FROM web_accounts WHERE id=?', (account_id,)).fetchone()
            if not row:
                raise WebError('Web 账号不存在', 404, 'account_not_found')
            account = json.loads(row[0])
            expected = account.get('expected_email') or email
            if email and expected.casefold() != email.casefold():
                raise WebError('Google 账号身份已变化，请重新识别同会话账号', 409, 'web_account_changed')
            key = account['credential_id'] + ':' + (expected.casefold() or str(account.get('authuser', 0)))
            duplicate = db.execute('SELECT id FROM web_accounts WHERE identity=? AND id!=?', (key, account_id)).fetchone()
            if duplicate:
                raise WebError('此 Google 账号已在会话列表中，请使用已有账号', 409, 'web_account_changed')
            account.update(display_name=name, email=email, expected_email=expected,
                           checked_at=int(time.time()), requires_relogin=False)
            db.execute('UPDATE web_accounts SET identity=?,data=? WHERE id=?', (key, json.dumps(account), account_id))

    def persist_cookies(self, account_id, cookies, expected_revision=None, records=None):
        try:
            with self.db() as db:
                row = db.execute('SELECT data FROM web_accounts WHERE id=?', (account_id,)).fetchone()
                if not row:
                    return None
                current = self.hydrate(db, json.loads(row[0]))
                if expected_revision is not None and current['revision'] != expected_revision:
                    return None
                merged = normalize_cookies(dict(current['cookies'], **cookies))
                payload = {'cookies': merged, 'revision': current['revision']}
                stored = sanitize_cookie_records(records if records is not None else current.get('cookie_records'))
                if records is None and stored and cookies:
                    stored = [{**item, 'value': cookies[item['name']]} if item['name'] in cookies else item for item in stored]
                    for name, value in cookies.items():
                        if not any(item['name'] == name for item in stored):
                            stored.extend(sanitize_cookie_records([{'name': name, 'value': value, 'domain': '.google.com', 'path': '/'}]))
                if stored:
                    payload['cookie_records'] = stored
                db.execute('UPDATE web_credentials SET fingerprint=?,data=? WHERE id=?',
                    (self.fingerprint(merged), json.dumps(payload), current['credential_id']))
                return merged
        except (WebError, sqlite3.Error, OSError):
            pass  # A deleted account must never be recreated by a late refresh.

    def delete(self, account_id):
        account = self.get(account_id)
        with self.db() as db:
            db.execute('DELETE FROM web_accounts WHERE id=?', (account_id,))
            if not any(json.loads(row[0]).get('credential_id') == account['credential_id'] for row in db.execute('SELECT data FROM web_accounts')):
                db.execute('DELETE FROM web_credentials WHERE id=?', (account['credential_id'],))
