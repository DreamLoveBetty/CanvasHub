"""Small exact-match dispatcher for existing authenticated HTTP endpoints."""

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any


class ProtectedRouter:
    """Keep the existing handler's authentication and response/error behavior."""

    def __init__(self, routes: Mapping[tuple[str, str], Callable[[Any], None]]):
        # Copy once at startup; request threads never mutate the route table.
        self._routes = MappingProxyType(dict(routes))

    def dispatch(self, handler: Any, method: str, path: str) -> bool:
        """Return True when consumed, including an authentication rejection.

        Unknown method/path pairs return False without writing a response, so
        the caller can continue its legacy dispatch. Do not normalize paths,
        introduce 404/405 responses, or reinterpret endpoint exceptions here.
        """
        action = self._routes.get((method, path))
        if action is None:
            return False
        if handler.require_auth():
            action(handler)
        return True
