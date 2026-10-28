"""Bounded private image locators and credential-free download events, Web only."""
import json
import logging
import os
from pathlib import Path
import re
import secrets
import tempfile
import time

logger = logging.getLogger(__name__)
_NAME = re.compile(r'wd_[0-9a-f]{32}\.json\Z')
_STAGES = {'rpc', 'original', 'preview', 'result'}
_REASONS = {'rpc_missing_context', 'rpc_error', 'rpc_rejected', 'rpc_no_url', 'response', 'http_error',
    'transport_error', 'url_rejected', 'loop', 'invalid_image', 'invalid_pointer',
    'too_many_hops', 'unexpected_error', 'verified', 'preview', 'failed', 'interrupted'}


def _text(value, limit):
    return value if isinstance(value, str) and len(value) <= limit else ''


class DownloadDiagnostics:
    """No network, browser access, credentials or public recovery endpoint."""
    def __init__(self, directory, *, max_records=64, max_age=86400):
        self.directory = Path(directory)
        self.max_records, self.max_age = max(1, max_records), max(1, max_age)

    def _directory(self):
        if self.directory.is_symlink():
            raise OSError('symlink diagnostic directory')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)

    def _prune(self):
        records = []
        for path in self.directory.iterdir():
            if not _NAME.fullmatch(path.name) or path.is_symlink() or not path.is_file():
                continue
            modified = path.stat().st_mtime
            if time.time() - modified > self.max_age:
                path.unlink()
            else:
                records.append((modified, path))
        # Reserve a slot for the checkpoint about to be written.
        for _, path in sorted(records)[:max(0, len(records) - self.max_records + 1)]:
            path.unlink()

    def begin(self, account_id, image, *, ratio, size, reference_count, image_count):
        trace = DownloadTrace(self, {
            'schema_version': 1, 'trace_id': 'wd_' + secrets.token_hex(16),
            'created_at': time.time(), 'outcome': 'pending',
            'account_id': account_id if re.fullmatch(r'[A-Za-z0-9_-]{1,128}', account_id) else '',
            'authuser': getattr(image.client_ref, 'authuser', None),
            'image': {**{key: _text(getattr(image, key, ''), 16384 if key == 'url' else 512)
                for key in ('url', 'cid', 'rid', 'rcid', 'image_id')},
                'temporary': getattr(image, 'temporary', False) is True},
            'request': {'ratio': ratio if re.fullmatch(r'\d{1,2}:\d{1,2}', ratio) else '',
                'size': size if size in ('1K', '2K', '4K') else '',
                'reference_count': reference_count, 'image_count': image_count},
            'events': [],
        })
        if type(trace.record['authuser']) is not int or not 0 <= trace.record['authuser'] < 20:
            trace.record['authuser'] = None
        try:
            self._directory()
            self._prune()
        except OSError:
            trace.unavailable()
        trace.write()
        return trace


class DownloadTrace:
    def __init__(self, owner, record):
        self.owner, self.record = owner, record
        self.id = record['trace_id']
        self.path = owner.directory / (self.id + '.json')
        self.persisting, self.finished = True, False

    def unavailable(self):
        if self.persisting:
            logger.warning('Gemini Web download checkpoint unavailable; trace_id=%s', self.id)
        self.persisting = False

    def write(self):
        if not self.persisting:
            return
        temporary = None
        try:
            self.owner._directory()
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                    prefix='.wd_', dir=self.owner.directory, delete=False) as stream:
                temporary = Path(stream.name)
                os.fchmod(stream.fileno(), 0o600)
                json.dump(self.record, stream, ensure_ascii=False)
            os.replace(temporary, self.path)
        except OSError:
            self.unavailable()
        finally:
            if temporary:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    self.unavailable()

    def original_url(self, url):
        if not self.finished:
            self.record['original_url'] = _text(url, 16384)
            self.write()

    def event(self, stage, reason, **fields):
        if self.finished or len(self.record['events']) >= 24:
            return
        event = {'stage': stage if stage in _STAGES else 'unknown',
                 'reason': reason if reason in _REASONS else 'unknown'}
        for key, low, high in (('http_status', 100, 599), ('hop', 0, 5),
                              ('transport_code', 0, 999), ('rpc_error_code', 0, 9999)):
            if type(fields.get(key)) is int and low <= fields[key] <= high:
                event[key] = fields[key]
        if fields.get('host_kind') in ('cdn', 'image_gateway', 'untrusted'):
            event['host_kind'] = fields['host_kind']
        self.record['events'].append(event)
        # Only enum/numeric fields plus local IDs: never serialize upstream values.
        logger.info('Gemini Web image download %s', json.dumps({
            'trace_id': self.id, 'account_id': self.record['account_id'],
            'authuser': self.record['authuser'], **event}, ensure_ascii=False))
        self.write()

    def finish(self, outcome):
        if self.finished:
            return
        if outcome not in ('verified', 'preview', 'failed', 'interrupted'):
            outcome = 'interrupted'
        self.record['outcome'] = outcome
        self.event('result', outcome)
        self.write()  # Also persist the outcome if the event limit was reached.
        self.finished = True
        if outcome != 'verified':
            logger.warning('Gemini Web image download %s', json.dumps({
                'trace_id': self.id, 'account_id': self.record['account_id'],
                'authuser': self.record['authuser'], 'outcome': outcome,
                'events': self.record['events']}, ensure_ascii=False))
        if outcome == 'verified':
            try:
                # Never follow a substituted directory to clean up a checkpoint.
                if not self.owner.directory.is_symlink():
                    self.path.unlink(missing_ok=True)
            except OSError:
                self.unavailable()
