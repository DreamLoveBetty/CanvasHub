#!/usr/bin/env python3
"""Compatibility entrypoint; real implementation lives in backend.server."""

import sys as _sys
from backend import server as _impl

_sys.modules[__name__] = _impl


if __name__ == "__main__":
    _impl.run_server()
