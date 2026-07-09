import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    path = ROOT / relative_path
    if not path.exists() and relative_path.startswith(("desktop.html", "index.html", "scripts/", "styles/", "assets/", "vendor/")):
        path = ROOT / "frontend" / relative_path
    return path.read_text(encoding="utf-8")


class MobileBootstrapContractTest(unittest.TestCase):
    def test_index_loads_preferences_before_bootstrap(self) -> None:
        html = read_text("index.html")

        prefs_idx = html.index("scripts/preferences.js")
        bootstrap_idx = html.index("scripts/bootstrap.js")

        self.assertLess(prefs_idx, bootstrap_idx)

    def test_preferences_exports_load_ui_settings_without_duplicate_google_constant(self) -> None:
        prefs_js = read_text("scripts/preferences.js")

        self.assertIn("function loadUiSettings()", prefs_js)
        self.assertIn("function saveUiSettings()", prefs_js)
        self.assertNotIn("const DEFAULT_GOOGLE_MODEL", prefs_js)


if __name__ == "__main__":
    unittest.main()
