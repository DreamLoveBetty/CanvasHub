"""Portable markup contracts for gallery output/model tab separation."""

from html.parser import HTMLParser
from pathlib import Path
import unittest


class GalleryTabsParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.divs = []
        self.tabs = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            self.divs.append(attrs)
        if "data-gallery-view" in attrs:
            self.tabs.append((attrs, list(self.divs)))

    def handle_endtag(self, tag):
        if tag == "div":
            self.divs.pop()


class GalleryTabGroupsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        html = Path(__file__).resolve().parents[1] / "frontend/desktop.html"
        cls.tabs = GalleryTabsParser(html.read_text(encoding="utf-8")).tabs

    def test_model_tab_follows_output_tabs(self):
        self.assertEqual(
            [tab["data-gallery-view"] for tab, _ in self.tabs],
            ["images", "videos", "files", "pinterest", "sources", "sets", "loras"],
        )
        ids = [tab["id"] for tab, _ in self.tabs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[-1], "deskGalleryTabLoras")

    def test_separate_named_groups_share_one_keyboard_tablist(self):
        tablists = []
        for tab, ancestors in self.tabs:
            with self.subTest(view=tab["data-gallery-view"]):
                group = ancestors[-1]
                self.assertEqual(group["role"], "group")
                self.assertIn("desk-gallery-tabs", group["class"].split())
                self.assertEqual(
                    group["aria-label"],
                    "模型资产" if tab["data-gallery-view"] == "loras" else "产出资产",
                )
                lists = [node for node in ancestors if node.get("role") == "tablist"]
                self.assertEqual(len(lists), 1)
                tablists.append(lists[0])
        self.assertTrue(all(node is tablists[0] for node in tablists))

    def test_initial_selection_and_panel_contract_preserved(self):
        for tab, _ in self.tabs:
            with self.subTest(view=tab["data-gallery-view"]):
                selected = tab["data-gallery-view"] == "images"
                self.assertEqual(tab["role"], "tab")
                self.assertEqual(tab["aria-controls"], "deskGalleryGrid")
                self.assertEqual(tab["aria-selected"], str(selected).lower())
                self.assertEqual(tab.get("tabindex", "0"), "0" if selected else "-1")


if __name__ == "__main__":
    unittest.main()
