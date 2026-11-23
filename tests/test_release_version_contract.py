"""Source-release contract: synchronized version labels and bundled bell notes."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = "26.6.3"
NOTES_DATE = "2026-11-23"
PREFERENCES_ASSET = "scripts/desktop-preferences.js"
PREFERENCES_SOURCE = "frontend/scripts/desktop-preferences.js"


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _first_release_block(source: str) -> str:
    match = re.search(
        r"const RELEASES = \[(.*?)\n  \];",
        source,
        flags=re.S,
    )
    if not match:
        raise AssertionError("RELEASES array not found")
    return match.group(1)


class ReleaseVersionContractTest(unittest.TestCase):
    def test_application_version_fields_are_synchronized_to_26_6_3(self):
        package = json.loads(_read("desktop/electron/package.json"))
        lock = json.loads(_read("desktop/electron/package-lock.json"))
        python = _read("backend/version.py")
        electron = _read("desktop/electron/src/main.ts")
        html = _read("frontend/desktop.html")

        self.assertEqual(package["version"], EXPECTED)
        self.assertEqual(lock["version"], EXPECTED)
        self.assertEqual(lock["packages"][""]["version"], EXPECTED)
        self.assertIn(f'APP_VERSION = "{EXPECTED}"', python)
        self.assertIn(f"const APP_VERSION = '{EXPECTED}';", electron)
        labels = re.findall(r"V\d+(?:\.\d+){2,3}", html)
        self.assertGreaterEqual(len(labels), 4)
        self.assertTrue(all(label == f"V{EXPECTED}" for label in labels), labels)
        self.assertNotIn("26.6.2", python)
        self.assertNotIn("V26.6.2", html)

    def test_bundled_release_notes_keep_existing_id_and_empty_version(self):
        block = _first_release_block(_read(PREFERENCES_SOURCE))
        self.assertIn("id: 'bundled-release'", block)
        self.assertIn("version: ''", block)
        self.assertIn(f"date: '{NOTES_DATE}'", block)
        self.assertRegex(block, r"title:\s*\{\s*zh:\s*'[^']+'")
        items = re.search(r"zh:\s*\[(.*?)\],\s*en:", block, flags=re.S)
        self.assertIsNotNone(items)
        bullets = re.findall(r"'([^']*)'", items.group(1))
        self.assertGreaterEqual(len(bullets), 5, bullets)
        joined = "\n".join(bullets)
        for needle in ("Cinematic", "粘液", "面板", "ComfyUI", "端口"):
            self.assertIn(needle, joined, f"missing {needle} in {bullets}")

    def test_preferences_cache_key_is_bumped_and_recorded(self):
        html = _read("frontend/desktop.html")
        lock = json.loads(_read("frontend/asset-versions.lock.json"))
        match = re.search(re.escape(PREFERENCES_ASSET) + r"\?v=([^\"\s]+)", html)
        self.assertIsNotNone(match, "desktop-preferences.js is missing a cache key")
        key = match.group(1)
        self.assertRegex(key, r"^20\d{6}-")
        self.assertIn("release", key)
        self.assertNotIn("runner-slider", key)
        recorded = lock["pages"]["desktop.html"][PREFERENCES_ASSET]["v"]
        self.assertEqual(recorded, key)


if __name__ == "__main__":
    unittest.main()
