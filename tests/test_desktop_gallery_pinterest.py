"""Boundary regressions for the Pinterest gallery split out of desktop-history.js."""

import re
import unittest
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
PINTEREST_STATE = re.compile(r"\b(pinterest[A-Z]\w*|PINTEREST_[A-Z_]+)\b")


def _read(relative):
    return (FRONTEND / relative).read_text(encoding="utf-8")


class DesktopGalleryPinterestBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.html = _read("desktop.html")
        self.module = _read("scripts/desktop-gallery-pinterest.js")
        self.history = _read("scripts/desktop-history.js")

    def test_module_loads_before_the_history_host_with_a_cache_key(self):
        self.assertRegex(self.html, r'scripts/desktop-gallery-pinterest\.js\?v=[0-9A-Za-z._-]+')
        self.assertLess(
            self.html.index("scripts/desktop-gallery-pinterest.js"),
            self.html.index("scripts/desktop-history.js"),
        )

    def test_host_reaches_pinterest_state_only_through_the_api(self):
        self.assertIn("const galleryPinterest = window.DesktopGalleryPinterest.create({", self.history)
        # Gallery-owned live state goes in as getters, not copies.
        for getter in ("getGalleryView: () => galleryView", "getGalleryQuery: () => galleryQuery", "getPreviewAsset: () => previewAsset"):
            self.assertIn(getter, self.history)
        leaked = sorted({
            name for name in PINTEREST_STATE.findall(re.sub(r"\bdataset\.\w+", "", self.history))
            if name not in {"pinterestPinId", "pinterestDownloading", "pinterestAnalyzing", "pinterestSplitting",
                            "pinterestAnalyzed", "pinterestSplitHasImage", "pinterestSplitReady",
                            "pinterestAnalyzeLabel", "pinterestSplitLabel", "pinterestAnalyzeTitle",
                            "pinterestSplitTitle", "pinterestSplitButton", "pinterestAnalyzeButton",
                            "pinterestDownloadButton", "pinterestDownloadTitle", "pinterestDownloadLabel"}
        })
        # Card rendering keeps its own local names (and data-pinterest-* dataset keys); nothing
        # else of the Pinterest domain remains.
        self.assertEqual(leaked, [], "Pinterest state or functions left in desktop-history.js")

    def test_single_implementation_and_explicit_dependencies(self):
        for name in ("loadPinterestLibrary", "renderPinterestLibrary", "checkPinterestSyncStatus",
                     "openPinterestAnalysisModal", "openPinterestSplitModal", "bindPinterestModalEvents",
                     "renderPinterestGalleryStats"):
            self.assertEqual(len(re.findall(r"function " + name + r"\(", self.module)), 1, name)
            self.assertNotIn("function " + name + "(", self.history, name)
        self.assertIn("window.DesktopGalleryPinterest = { create };", self.module)
        self.assertNotIn("DesktopHistory", self.module)
        # The video folder shares the clipboard helper, so it stays with the host.
        self.assertIn("async function copyPinterestSplitText(", self.history)
        self.assertNotIn("function copyPinterestSplitText(", self.module)


if __name__ == "__main__":
    unittest.main()
