from pathlib import Path
import ntpath
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


class ProjectLayoutTest(unittest.TestCase):
    def test_frontend_sources_live_under_frontend_directory(self):
        self.assertTrue((ROOT / "frontend" / "desktop.html").exists())
        self.assertTrue((ROOT / "frontend" / "index.html").exists())
        self.assertTrue((ROOT / "frontend" / "scripts" / "desktop-settings.js").exists())
        self.assertTrue((ROOT / "frontend" / "styles" / "desktop-liquid.css").exists())
        self.assertFalse((ROOT / "desktop.html").exists())
        self.assertFalse((ROOT / "index.html").exists())

    def test_backend_sources_live_under_backend_with_compat_entrypoint(self):
        self.assertTrue((ROOT / "backend" / "server.py").exists())
        self.assertTrue((ROOT / "backend" / "app_config.py").exists())
        self.assertTrue((ROOT / "backend" / "codex_image_runtime" / "scripts" / "codex_api.py").exists())
        self.assertTrue((ROOT / "server.py").exists())

    def test_frontend_static_paths_are_url_normalized_on_windows(self):
        from backend import server

        # Simulate Windows path behavior.  The HTTP URL still uses "/" and must
        # not be normalized with ntpath, otherwise "/desktop.html" becomes
        # "\\desktop.html" and misses the frontend entrypoint mapping.
        with mock.patch.object(server.os, "path", ntpath):
            self.assertEqual(
                Path(server.RequestHandler.translate_path(object(), "/desktop.html")),
                ROOT / "frontend" / "desktop.html",
            )
            self.assertEqual(
                Path(server.RequestHandler.translate_path(object(), "/styles/desktop-liquid.css?v=1")),
                ROOT / "frontend" / "styles" / "desktop-liquid.css",
            )


if __name__ == "__main__":
    unittest.main()
