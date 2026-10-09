"""Google authorization-code sessions. State-checked, bounded and single-use."""

from __future__ import annotations
import base64
import hashlib
import secrets
import threading
import time
import uuid
from urllib.parse import urlencode, urlsplit, parse_qs
from .errors import GoogleError

SCOPES = 'openid https://www.googleapis.com/auth/cloud-platform https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile https://www.googleapis.com/auth/cclog https://www.googleapis.com/auth/experimentsandconfigs'


class GoogleOAuth:
    def __init__(self, settings, store, upstream):
        self.settings, self.store, self.upstream = settings, store, upstream
        self.lock = threading.RLock()
        self.sessions = {}

    def start(self):
        if not self.settings.client_id or not self.settings.client_secret:
            raise GoogleError(
                'Google OAuth Client 尚未配置', 503, 'oauth_not_configured'
            )
        sid = uuid.uuid4().hex
        state = sid + '.' + secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b'=')
            .decode()
        )
        with self.lock:
            self.sessions = {
                k: v for k, v in self.sessions.items() if v['expires_at'] > time.time()
            }
            if len(self.sessions) >= 16:
                raise GoogleError('待完成授权过多', 429, 'oauth_busy')
            self.sessions[sid] = {
                'state': state,
                'verifier': verifier,
                'expires_at': time.time() + 600,
                'used': False,
                'result': None,
            }
        query = urlencode(
            {
                'client_id': self.settings.client_id,
                'redirect_uri': self.settings.redirect_uri,
                'response_type': 'code',
                'scope': SCOPES,
                'access_type': 'offline',
                'prompt': 'consent',
                'state': state,
                'code_challenge': challenge,
                'code_challenge_method': 'S256',
            }
        )
        return {
            'session_id': sid,
            'authorize_url': 'https://accounts.google.com/o/oauth2/v2/auth?' + query,
            'redirect_uri': self.settings.redirect_uri,
            'expires_in': 600,
        }

    def finish(self, callback, session_id=''):
        parsed = urlsplit(str(callback))
        expected = urlsplit(self.settings.redirect_uri)
        if (parsed.scheme, parsed.netloc, parsed.path) != (
            expected.scheme,
            expected.netloc,
            expected.path,
        ):
            raise GoogleError(
                '请粘贴完整且匹配本次授权的 callback URL', 400, 'invalid_callback'
            )
        q = parse_qs(parsed.query)
        if len(q.get('state', [])) != 1 or len(q.get('code', [])) != 1:
            raise GoogleError('回调缺少或重复 state/code', 400, 'invalid_callback')
        state = q['state'][0]
        sid = state.split('.')[0]
        if session_id and sid != session_id:
            raise GoogleError('授权会话不匹配', 400, 'invalid_state')
        with self.lock:
            session = self.sessions.get(sid)
            if (
                not session
                or session['expires_at'] <= time.time()
                or not secrets.compare_digest(session['state'], state)
            ):
                raise GoogleError('授权已过期或 state 不匹配', 400, 'invalid_state')
            if session['result'] is not None:
                return session['result']
            if session['used']:
                raise GoogleError(
                    '此授权码已提交，请等待或重新授权', 409, 'oauth_consumed'
                )
            session['used'] = True
        token = self.upstream.token(
            {
                'grant_type': 'authorization_code',
                'code': q['code'][0],
                'redirect_uri': self.settings.redirect_uri,
                'code_verifier': session['verifier'],
            }
        )
        # Save refreshable credentials even if a subsequent profile lookup fails.
        item = self.store.import_account(token)
        try:
            profile = self.upstream.profile(token['access_token'])
            self.store.patch(
                item['id'], {'email': str(profile.get('email') or '')[:254]}
            )
            item = self.store.public(self.store.get(item['id']))
        except GoogleError:
            pass
        result = {'ok': True, 'item': item, 'session_id': sid}
        with self.lock:
            session['result'] = result
            session['verifier'] = ''
        return result
