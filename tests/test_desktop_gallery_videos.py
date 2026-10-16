"""Boundary regressions for the gallery video folder split out of desktop-history.js."""

import re
import unittest
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def _read(relative):
    return (FRONTEND / relative).read_text(encoding="utf-8")


class DesktopGalleryVideosBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.html = _read("desktop.html")
        self.module = _read("scripts/desktop-gallery-videos.js")
        self.history = _read("scripts/desktop-history.js")

    def test_module_loads_before_the_history_host_with_a_cache_key(self):
        self.assertRegex(self.html, r'scripts/desktop-gallery-videos\.js\?v=[0-9A-Za-z._-]+')
        self.assertLess(self.html.index("scripts/desktop-gallery-videos.js"), self.html.index("scripts/desktop-history.js"))

    def test_host_no_longer_owns_video_state(self):
        self.assertIn("const galleryVideoFolder = window.DesktopGalleryVideos.create({", self.history)
        self.assertIn("getGalleryView: () => galleryView", self.history)
        self.assertIn("getGalleryQuery: () => galleryQuery", self.history)
        # The history panel's own isVideoHistoryItem stays; the gallery video folder does not.
        # Allowed: the module global, the instance, and the element id the host's els registry collects.
        allowed = {"DesktopGalleryVideos", "galleryVideoFolder", "deskGalleryVideoSource"}
        leaked = sorted(set(re.findall(r"\b\w*(?:galleryVideo|GalleryVideo)\w*", re.sub(r"\bdataset\.\w+", "", self.history))) - allowed)
        self.assertEqual(leaked, [], "gallery video state or functions left in desktop-history.js")
        self.assertIn("function isVideoHistoryItem(", self.history)
        # Writes that used to reset the expanded card now go through the module.
        self.assertNotIn("expandedGalleryVideoId", self.history)
        self.assertEqual(self.history.count("galleryVideoFolder.collapseExpanded()"), 2)

    def test_single_implementation(self):
        for name in ("loadGalleryVideos", "renderGalleryVideos", "renderGalleryVideoCard", "bindGalleryVideoEvents",
                     "bindGalleryVideoSourceEvents", "renderGalleryVideoStats", "collapseExpandedGalleryVideo"):
            self.assertEqual(len(re.findall(r"function " + name + r"\(", self.module)), 1, name)
        self.assertIn("window.DesktopGalleryVideos = { create };", self.module)
        self.assertNotIn("DesktopHistory", self.module)
        # The clipboard helper is shared with the Pinterest tab and stays in the host.
        self.assertNotIn("function copyPinterestSplitText(", self.module)


if __name__ == "__main__":
    unittest.main()
