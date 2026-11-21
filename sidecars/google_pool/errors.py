"""Bounded public errors. Never expose upstream payloads or credentials."""

from __future__ import annotations

import re

_SAFE_REASON = re.compile(r'^[A-Z][A-Z0-9._-]{0,63}$')
_ANONYMOUS_ACCOUNT_ID = re.compile(r'^[0-9a-fA-F-]{6,64}$')


class GoogleError(RuntimeError):
    def __init__(
        self,
        message,
        status=502,
        code='google_upstream_error',
        reasons=None,
        account_id=None,
        attempt=None,
        http_status_rejection=False,
    ):
        super().__init__(message)
        self.status = status
        self.code = code
        # True only when a complete HTTP status was read from the request
        # response itself, before any SSE/body stream was consumed as output.
        self.http_status_rejection = bool(http_status_rejection)
        self.reasons = tuple(
            value
            for value in (reasons or ())
            if isinstance(value, str) and _SAFE_REASON.fullmatch(value)
        )
        ident = str(account_id) if account_id else ''
        self.account_id = ident if _ANONYMOUS_ACCOUNT_ID.fullmatch(ident) else None
        try:
            self.attempt = int(attempt) if attempt is not None else None
        except (TypeError, ValueError):
            self.attempt = None

    def public(self):
        payload = {'error': str(self), 'error_code': self.code}
        info = {}
        if self.account_id:
            info['account_id'] = self.account_id
        if self.attempt is not None:
            info['attempt'] = self.attempt
        if info:
            payload['google_pool'] = info
        return payload
