import io
import json
import unittest

from backend.routes.moss_routes import create_router

ROUTES = {("GET", "/api/moss/status"), ("GET", "/api/moss/catalog"), ("GET", "/api/moss/lora-list"),
          ("POST", "/api/moss/prepare"), ("POST", "/api/moss/model-bind"), ("POST", "/api/moss/layout-compile"), ("GET", "/api/moss/model-tools"), ("POST", "/api/moss/model-inspect"),
          ("POST", "/api/moss/model-convert"), ("POST", "/api/moss/model-convert-cancel"), ("POST", "/api/moss/model-delete"),
          ("POST", "/api/moss/generate"), ("POST", "/api/moss/cancel"), ("POST", "/api/moss/lora-import"),
          ("POST", "/api/moss/lora-delete")}


class Handler:
    def __init__(self, body=b"", *, authenticated=True, path="/api/moss/x", length=None):
        self.headers = {"Content-Length": str(len(body) if length is None else length)}
        self.rfile, self.path, self.authenticated = io.BytesIO(body), path, authenticated
        self.sent = None

    def require_auth(self):
        return self.authenticated

    def send_json(self, value, code=200):
        self.sent = (value, code)


class Service:
    result = {"ok": True}

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name, args))
            if isinstance(self.result, Exception):
                raise self.result
            return self.result
        return call


class Routes(unittest.TestCase):
    def setUp(self):
        self.service = Service()
        self.router = create_router(self.service)

    def post(self, path, value):
        handler = Handler(value if isinstance(value, bytes) else json.dumps(value).encode(), path=path)
        self.assertTrue(self.router.dispatch(handler, "POST", path))
        return handler.sent

    def test_exact_whitelist(self):
        self.assertEqual(set(self.router._routes), ROUTES)

    def test_excluded_actions_are_not_routed(self):
        for action in ("upload", "edit", ):
            self.assertFalse(self.router.dispatch(Handler(), "POST", f"/api/moss/{action}"))
            self.assertFalse(self.router.dispatch(Handler(), "GET", f"/api/moss/{action}"))

    def test_every_route_requires_auth(self):
        for method, path in ROUTES:
            handler = Handler(b"{}", authenticated=False)
            self.assertTrue(self.router.dispatch(handler, method, path))
            self.assertIsNone(handler.sent)
        self.assertEqual(self.service.calls, [])

    def test_long_operations_and_generate_answer_202(self):
        for path in ("prepare", "model-bind", "generate"):
            self.assertEqual(self.post(f"/api/moss/{path}", {})[1], 202)

    def test_compile_and_cancel_answer_200(self):
        self.assertEqual(self.post("/api/moss/layout-compile", {"mode": "text"})[1], 200)
        self.post("/api/moss/cancel", {"task_id": "t"})
        self.assertEqual(self.service.calls[-1], ("cancel", ("t",)))

    def test_body_is_parsed_strictly(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b"[1]", b"not json"):
            self.assertEqual(self.post("/api/moss/generate", raw)[1], 400)
        self.assertEqual(self.service.calls, [])

    def test_body_limit(self):
        handler = Handler(b"{}", path="/api/moss/generate", length=256 * 1024 + 1)
        self.router.dispatch(handler, "POST", "/api/moss/generate")
        self.assertEqual(handler.sent[1], 400)
        self.assertEqual(self.service.calls, [])

    def test_truncated_body_is_rejected(self):
        handler = Handler(b"{}", path="/api/moss/generate", length=10)
        self.router.dispatch(handler, "POST", "/api/moss/generate")
        self.assertEqual(handler.sent[1], 400)

    def test_lora_import_streams_without_reading_the_body(self):
        handler = Handler(b"x" * 16, path="/api/moss/lora-import?name=a.safetensors")
        self.router.dispatch(handler, "POST", "/api/moss/lora-import")
        name, args = self.service.calls[0]
        self.assertEqual((name, args[0], args[1], args[2]), ("import_lora", handler.rfile, 16, "a.safetensors"))
        self.assertEqual(handler.rfile.tell(), 0)

    def test_lora_import_limit(self):
        handler = Handler(b"", path="/api/moss/lora-import", length=2 * 1024**3 + 1)
        self.router.dispatch(handler, "POST", "/api/moss/lora-import")
        self.assertEqual(handler.sent[1], 400)

    def test_error_mapping_hides_internals(self):
        for error, code in ((ValueError("bad"), 400), (RuntimeError("busy"), 503), (OSError("/secret/path"), 500),
                            (Exception("/secret/path"), 502)):
            self.service.result = error
            value, status = self.post("/api/moss/generate", {})
            self.assertEqual(status, code)
            if code in (500, 502):
                self.assertNotIn("secret", value["error"])


if __name__ == "__main__":
    unittest.main()
