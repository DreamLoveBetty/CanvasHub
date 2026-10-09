"""Bounded public errors. Never expose upstream payloads or credentials."""


class GoogleError(RuntimeError):
    def __init__(self, message, status=502, code='google_upstream_error'):
        super().__init__(message)
        self.status = status
        self.code = code

    def public(self):
        return {'error': str(self), 'error_code': self.code}
