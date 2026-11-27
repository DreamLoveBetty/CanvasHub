"""Tests for generic local-extension discovery, routing, asset injection, and security."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.local_extensions import DISABLE_ENV, LocalExtensionRegistry  # noqa: E402
from backend.services.server_lifecycle import run_server  # noqa: E402
from backend.video_edit.sources import SourceResolver, UnsupportedSource  # noqa: E402


class FakeRouter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def dispatch(self, handler, method: str, path: str) -> bool:
        self.calls.append((method, path))
        return path == "/api/sample_ext/ping"


class FakeStore:
    def __init__(self, asset_path: Path, artifact_path: Path) -> None:
        self._asset = asset_path
        self._artifact = artifact_path

    def asset(self, ident: str) -> Path:
        if ident != "abc":
            raise FileNotFoundError("not found")
        return self._asset

    def artifact(self, ident: str, name: str) -> Path:
        if ident != "abc" or name != "out.mp4":
            raise FileNotFoundError("not found")
        return self._artifact


def _write_sample_extension(base: Path, *, symlink_asset: bool = False) -> Path:
    ext = base / "local_extensions" / "sample_ext"
    (ext / "frontend" / "scripts").mkdir(parents=True, exist_ok=True)
    (ext / "frontend" / "styles").mkdir(parents=True, exist_ok=True)
    css = ext / "frontend" / "styles" / "sample.css"
    js = ext / "frontend" / "scripts" / "sample.js"
    unlisted = ext / "frontend" / "scripts" / "unlisted.js"
    css.write_text("/* sample */\n", encoding="utf-8")
    js.write_text("console.log('sample');\n", encoding="utf-8")
    unlisted.write_text("console.log('secret');\n", encoding="utf-8")
    if symlink_asset:
        secret = base / "secret.txt"
        secret.write_text("do not expose", encoding="utf-8")
        os.symlink(secret, ext / "frontend" / "scripts" / "link.js")

    (ext / "plugin.py").write_text(
        '''from pathlib import Path

class _Router:
    def dispatch(self, handler, method, path):
        if (method, path) == ("GET", "/api/sample_ext/status"):
            handler["handled"] = True
            return True
        return False

class _Store:
    def __init__(self, root):
        self._clip = root / "clip.mp4"
    def asset(self, ident):
        return self._clip
    def artifact(self, ident, name):
        return self._clip

def register(host):
    ext_dir = Path(__file__).resolve().parent
    host.register_router(_Router())
    host.register_video_store("sample_video", _Store(ext_dir))
    host.register_asset_provider("sample_img", "Sample Ext", filename_prefixes=("sample_ext_",))
    host.register_frontend_assets(
        ext_dir / "frontend",
        styles=("styles/sample.css",),
        scripts=("scripts/sample.js",),
    )
''',
        encoding="utf-8",
    )
    return ext


class LocalExtensionsTest(unittest.TestCase):
    def test_discovery_disable_flag_and_injection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_sample_extension(root)
            reg = LocalExtensionRegistry()

            loaded = reg.load_all(root, app_data_dir=root / "app_data", environ={})
            self.assertEqual(loaded, ["sample_ext"])
            self.assertTrue(reg.has_frontend_assets())

            handler: dict = {}
            self.assertTrue(reg.dispatch_route(handler, "GET", "/api/sample_ext/status"))
            self.assertTrue(handler.get("handled"))
            self.assertFalse(reg.dispatch_route(handler, "GET", "/api/other/status"))

            self.assertEqual(reg.match_asset_provider_group("sample_img"), "sample_img")
            self.assertEqual(reg.asset_provider_label("sample_img"), "Sample Ext")
            self.assertEqual(reg.infer_archive_provider("sample_ext_001.png"), "sample_img")
            self.assertIsNone(reg.infer_archive_provider("other_001.png"))

            desktop_html = (ROOT / "frontend" / "desktop.html").read_text(encoding="utf-8")
            injected = reg.inject_desktop_html(desktop_html)
            self.assertIn('/local-ext/sample_ext/styles/sample.css?v=', injected)
            self.assertIn('/local-ext/sample_ext/scripts/sample.js?v=', injected)
            self.assertNotIn("<!-- local-extensions:styles -->", injected)
            self.assertNotIn("<!-- local-extensions:scripts -->", injected)

            disabled = reg.load_all(
                root,
                app_data_dir=root / "app_data",
                environ={DISABLE_ENV: "1"},
            )
            self.assertEqual(disabled, [])
            self.assertFalse(reg.has_frontend_assets())
            self.assertEqual(reg.inject_desktop_html(desktop_html), desktop_html)
            self.assertEqual(reg.video_stores(), {})

    def test_source_resolver_uses_registered_video_stores(self) -> None:
        clip = Path("/tmp/ext_clip.mp4")
        art = Path("/tmp/ext_out.mp4")
        resolver = SourceResolver(
            archive_video=lambda rel: None,
            stores={"sample_video": FakeStore(clip, art)},
        )
        self.assertEqual(resolver.resolve("/api/sample_video/source?id=abc"), clip)
        self.assertEqual(resolver.resolve("/api/sample_video/artifact?id=abc&name=out.mp4"), art)
        with self.assertRaises(UnsupportedSource):
            resolver.resolve("/api/unregistered_video/source?id=abc")

    def test_allowlist_and_traversal_protection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ext = _write_sample_extension(root, symlink_asset=True)
            reg = LocalExtensionRegistry()
            reg.load_all(root, app_data_dir=root / "app_data", environ={})

            resolved_css = reg.resolve_frontend_asset("/local-ext/sample_ext/styles/sample.css")
            self.assertEqual(resolved_css, (ext / "frontend" / "styles" / "sample.css").resolve())
            self.assertIsNone(reg.resolve_frontend_asset("/local-ext/sample_ext/scripts/unlisted.js"))
            self.assertIsNone(reg.resolve_frontend_asset("/local-ext/sample_ext/../plugin.py"))
            self.assertIsNone(reg.resolve_frontend_asset("/local-ext/sample_ext/scripts/..\\plugin.py"))
            self.assertIsNone(reg.resolve_frontend_asset("/scripts/desktop-canvas.js"))

            # Broken/malicious plugin registering traversal or symlinks is skipped cleanly.
            bad_ext = root / "local_extensions" / "bad_ext"
            bad_ext.mkdir(parents=True)
            (root / "secret_root.js").write_text("x", encoding="utf-8")
            (bad_ext / "plugin.py").write_text(
                f'''from pathlib import Path
def register(host):
    host.register_frontend_assets(Path({str(ext / "frontend")!r}), scripts=("../plugin.py",))
''',
                encoding="utf-8",
            )
            loaded = reg.load_all(root, app_data_dir=root / "app_data", environ={})
            self.assertEqual(loaded, ["sample_ext"])

    def test_tracked_extensions_precedence_disable_isolation_and_ext_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            built = root / "extensions" / "built-in"
            (built / "frontend" / "styles").mkdir(parents=True)
            (built / "frontend" / "styles" / "built.css").write_text("/* built */\n", encoding="utf-8")
            (built / "frontend" / "styles" / "unlisted.css").write_text("/* hidden */\n", encoding="utf-8")
            (built / "plugin.py").write_text(
                '''from pathlib import Path
def register(host):
    ext_dir = Path(__file__).resolve().parent
    host.register_frontend_assets(ext_dir / "frontend", styles=("styles/built.css",))
''',
                encoding="utf-8",
            )
            local = root / "local_extensions" / "built-in"
            (local / "frontend" / "scripts").mkdir(parents=True)
            (local / "frontend" / "scripts" / "shadow.js").write_text("console.log('shadow');\n", encoding="utf-8")
            (local / "plugin.py").write_text(
                '''from pathlib import Path
def register(host):
    ext_dir = Path(__file__).resolve().parent
    host.register_frontend_assets(ext_dir / "frontend", scripts=("scripts/shadow.js",))
''',
                encoding="utf-8",
            )
            _write_sample_extension(root)

            reg = LocalExtensionRegistry()
            loaded = reg.load_all(root, app_data_dir=root / "app_data", environ={})
            self.assertEqual(loaded, ["built-in", "sample_ext"])
            self.assertEqual(
                reg.resolve_frontend_asset("/ext/built-in/styles/built.css"),
                (built / "frontend" / "styles" / "built.css").resolve(),
            )
            self.assertIsNone(reg.resolve_frontend_asset("/local-ext/built-in/scripts/shadow.js"))
            self.assertIsNone(reg.resolve_frontend_asset("/ext/built-in/styles/unlisted.css"))
            self.assertIsNone(reg.resolve_frontend_asset("/ext/built-in/../plugin.py"))

            html = (ROOT / "frontend" / "desktop.html").read_text(encoding="utf-8")
            injected = reg.inject_desktop_html(html)
            self.assertIn("/ext/built-in/styles/built.css?v=", injected)
            self.assertIn("/local-ext/sample_ext/scripts/sample.js?v=", injected)

            only_built = reg.load_all(root, app_data_dir=root / "app_data", environ={DISABLE_ENV: "1"})
            self.assertEqual(only_built, ["built-in"])
            self.assertIsNotNone(reg.resolve_frontend_asset("/ext/built-in/styles/built.css"))
            self.assertIsNone(reg.resolve_frontend_asset("/local-ext/sample_ext/scripts/sample.js"))

    def test_startup_hooks_fault_isolation_and_method_dispatch(self) -> None:
        events: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ext = root / "extensions" / "hooked"
            ext.mkdir(parents=True)
            (ext / "plugin.py").write_text(
                '''class _MethodRouter:
    def dispatch(self, handler, method, path):
        if path == "/api/hooked/item" and method in ("DELETE", "PATCH", "PUT"):
            handler["method"] = method
            return True
        return False

def register(host):
    try:
        host.register_startup_hook("not-callable")
    except TypeError:
        host._registry._test_rejected_non_callable = True  # checked via hook side effect
    host.register_startup_hook(lambda: host._registry._test_calls.append("first"))
    def broken():
        raise RuntimeError("boom")
    host.register_startup_hook(broken)
    host.register_startup_hook(lambda: host._registry._test_calls.append("second"))
    host.register_router(_MethodRouter())
''',
                encoding="utf-8",
            )

            reg = LocalExtensionRegistry()
            reg._test_calls = events
            loaded = reg.load_all(root, app_data_dir=root / "app_data", environ={})
            self.assertEqual(loaded, ["hooked"])
            self.assertTrue(getattr(reg, "_test_rejected_non_callable", False))
            self.assertEqual(reg.run_startup_hooks(), 2)
            self.assertEqual(events, ["first", "second"])

            for method in ("DELETE", "PATCH", "PUT"):
                sink: dict = {}
                self.assertTrue(reg.dispatch_route(sink, method, "/api/hooked/item"))
                self.assertEqual(sink["method"], method)
            self.assertFalse(reg.dispatch_route({}, "POST", "/api/hooked/item"))

    def test_server_lifecycle_invokes_extension_startup_hooks(self) -> None:
        calls: list[str] = []

        class FakeServer:
            def __init__(self, _addr, _handler):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *_exc):
                return False
            def serve_forever(self):
                calls.append("serve")

        class FakeMixin:
            pass

        class FakeSocketServer:
            ThreadingMixIn = FakeMixin
            TCPServer = FakeServer

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            run_server(
                APP_DATA_DIR=tmp_dir,
                PORT=0,
                RequestHandler=object,
                SERVER_CONFIG={"public_mode": False},
                SERVER_HOST="127.0.0.1",
                SOURCE_IMAGE_DIR=tmp_dir / "src",
                STYLE_PRESETS_FILE=tmp_dir / "presets.json",
                _ensure_db_file_permissions=lambda: None,
                _init_generation_semaphore=lambda: None,
                _validate_public_mode_password=lambda **_kw: None,
                cancel_orphan_prompt_source_runs=lambda: 0,
                fail_stale_processing_tasks=lambda **_kw: 0,
                fail_orphaned_queued_generation_tasks=lambda: 0,
                get_agent_runtime=lambda: type("R", (), {"recover_after_restart": lambda _s: 0})(),
                init_agent_store=lambda: None,
                init_asset_store=lambda: None,
                init_db=lambda: None,
                init_layout_draft_store=lambda: None,
                init_prompt_library_store=lambda **_kw: None,
                init_prompt_source_store=lambda: None,
                recover_cyimg_tasks=lambda: None,
                recover_krea2_tasks=lambda: None,
                run_extension_startup_hooks=lambda: calls.append("ext_hooks"),
                socketserver=FakeSocketServer,
            )
        self.assertEqual(calls, ["ext_hooks", "serve"])

    def test_extension_test_discovery_scopes(self) -> None:
        from tests import run_regressions

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            ext_tests = tmp_root / "extensions" / "my-ext" / "tests"
            ext_tests.mkdir(parents=True)
            stable_py = ext_tests / "test_ext_ok.py"
            local_py = ext_tests / "test_ext_local.py"
            stable_py.write_text("import unittest\n", encoding="utf-8")
            local_py.write_text("import unittest\n", encoding="utf-8")
            # Ensure local_extensions tests remain excluded.
            (tmp_root / "local_extensions" / "priv" / "tests").mkdir(parents=True)
            (tmp_root / "local_extensions" / "priv" / "tests" / "test_priv.py").write_text("", encoding="utf-8")

            with mock.patch.object(run_regressions, "EXTENSIONS_ROOT", tmp_root / "extensions"):
                self.assertEqual(run_regressions._extension_test_files("stable"), [("my-ext", stable_py)])
                self.assertEqual(run_regressions._extension_test_files("local"), [("my-ext", local_py)])
                self.assertEqual(
                    run_regressions._extension_test_files("all"),
                    [("my-ext", local_py), ("my-ext", stable_py)],
                )


if __name__ == "__main__":
    unittest.main()
