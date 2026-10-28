"""Do not forward untrusted upstream messages to shared application logs."""
class SilentLogger:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


logger = SilentLogger()


def set_log_level(level):
    pass
