class WebError(RuntimeError):
    """Only application-authored, credential-free messages cross the API boundary."""
    def __init__(self, message, status=502, code='web_error', details=None):
        super().__init__(message)
        self.status, self.code, self.details = status, code, details

    def public(self):
        payload = {'error': str(self), 'error_code': self.code}
        if self.details is not None:
            payload['details'] = self.details
        return payload
