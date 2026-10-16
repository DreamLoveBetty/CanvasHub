"""Boundary regressions for the prompt-sources tab split out of desktop-history.js."""

import re
import unittest
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def _read(relative):
    return (FRONTEND / relative).read_text(encoding="utf-8")


class DesktopGalleryPromptSourcesBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.html = _read("desktop.html")
        self.module = _read("scripts/desktop-gallery-prompt-sources.js")
        self.history = _read("scripts/desktop-history.js")

    def test_module_loads_before_the_history_host_with_a_cache_key(self):
        self.assertRegex(self.html, r'scripts/desktop-gallery-prompt-sources\.js\?v=[0-9A-Za-z._-]+')
        self.assertLess(
            self.html.index("scripts/desktop-gallery-prompt-sources.js"),
            self.html.index("scripts/desktop-history.js"),
        )

    def test_host_passes_live_state_as_getters_and_reads_through_the_api(self):
        self.assertIn("const galleryPromptSources = window.DesktopGalleryPromptSources.create({", self.history)
        for getter in (
            "getGalleryView: () => galleryView",
            "getGalleryQuery: () => galleryQuery",
            "getGalleryTag: () => galleryTag",
            "getGalleryVirtualDataRevision: () => galleryVirtualDataRevision",
        ):
            self.assertIn(getter, self.history)
        # Only the shared render limit constant stays with the host's virtual grid.
        leaked = sorted(set(re.findall(r"\bpromptSource\w*|\bPROMPT_SOURCE_\w+|\bnormalizeTaxonomy\w*", self.history))
                        - {"PROMPT_SOURCE_INITIAL_RENDER_LIMIT"})
        self.assertEqual(leaked, [], "prompt-source state or functions left in desktop-history.js")

    def test_virtual_cache_reset_goes_through_the_module(self):
        invalidate = self.history.split("function invalidateGalleryVirtualData()", 1)[1].split("\n  }", 1)[0]
        self.assertIn("galleryPromptSources.invalidateVisibleCache();", invalidate)
        self.assertIn("promptSourceVisibleItemsCache = { revision: -1, items: [] };", self.module)
        for name in ("loadPromptSources", "loadPromptSourceItems", "renderPromptSources", "syncPromptSources", "getVisiblePromptSourceItems"):
            self.assertEqual(len(re.findall(r"function " + name + r"\(", self.module)), 1, name)
        self.assertIn("window.DesktopGalleryPromptSources = { create };", self.module)
        self.assertNotIn("DesktopHistory", self.module)


if __name__ == "__main__":
    unittest.main()
