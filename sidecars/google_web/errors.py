class WebError(RuntimeError):
    """Only application-authored, credential-free messages cross the API boundary."""
    def __init__(self, message, status=502, code='web_error'):
        super().__init__(message)
        self.status, self.code = status, code

    def public(self):
        return {'error': str(self), 'error_code': self.code}
