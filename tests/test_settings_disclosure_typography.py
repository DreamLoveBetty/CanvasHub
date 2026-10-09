"""Portable contracts for Settings category navigation and model-tool guidance."""

from html.parser import HTMLParser
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SettingsDisclosureTypographyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.geometry = (ROOT / "frontend/styles/desktop-geometry.css").read_text()
        cls.controls = (ROOT / "frontend/styles/desktop-controls.css").read_text()
        cls.paint = (ROOT / "frontend/styles/desktop-settings-auth.css").read_text()
        cls.html = (ROOT / "frontend/desktop.html").read_text()

    def rule(self, source, selector):
        match = re.search(re.escape(selector) + r"\s*\{([^}]+)\}", source)
        self.assertIsNotNone(match, selector)
        return match[1]

    def test_direct_inspection_text_has_its_own_caption_scale(self):
        blocks = re.findall(r"body\.desk-app\[data-theme\] \.desk-settings :is\(([^)]+)\)\s*\{([^}]+)\}", self.geometry)
        expected = {".desk-qwen21-tools__inspection", ".desk-krea2-tools__inspection",
                    ".desk-qwen21-tools__progress", ".desk-krea2-tools__progress"}
        matching = [body for selectors, body in blocks if expected <= {selector.strip() for selector in selectors.split(",")}]
        self.assertEqual(len(matching), 1)
        for declaration in ("font-size: var(--desk-font-size-caption);", "line-height: var(--desk-line-height-normal);",
                            "font-weight: var(--desk-font-weight-regular);"):
            self.assertIn(declaration, matching[0])

    def test_help_is_regular_weight_and_long_technical_names_can_wrap(self):
        match = re.search(r"body\.desk-app\[data-theme\] \.desk-settings :is\(([^)]+)\) \.desk-settings-form__hint\s*\{([^}]+)\}", self.geometry)
        self.assertIsNotNone(match)
        for selector in (".desk-krea2-tools__card", ".desk-qwen21-tools__card"):
            self.assertIn(selector, match[1])
        self.assertIn("font-weight: var(--desk-font-weight-regular);", match[2])
        self.assertIn("overflow-wrap: anywhere;", match[2])
        self.assertRegex(self.geometry, re.compile(r"\.desk-settings :is\([^)]*\.desk-qwen21-tools__inspection[^)]*\) strong\s*\{\s*font-weight: var\(--desk-font-weight-medium\);", re.S))

    def test_static_guidance_uses_muted_settings_paint_without_hiding_error_states(self):
        match = re.search(r"body\.desk-app\[data-theme\] \.desk-settings :is\([^)]*\.desk-qwen21-tools__card[^)]*\) \.desk-settings-form__hint,[^{]+\{([^}]+)\}", self.paint)
        self.assertIsNotNone(match)
        self.assertIn("color: var(--desk-settings-muted-ink);", match[1])
        for name in ("krea2", "qwen21"):
            css = (ROOT / f"frontend/styles/desktop-{name}.css").read_text()
            self.assertIn(f".desk-{name}-tools__inspection.is-warn", css)
            self.assertIn(f".desk-{name}-tools__progress.is-error", css)
            self.assertIn("border-color: var(--desk-color-danger-border);", css)


    def test_every_category_is_a_visible_grouped_tab_without_a_disclosure(self):
        class Nav(HTMLParser):
            def __init__(self):
                super().__init__()
                self.nav, self.tabs, self.groups, self.ids = None, [], [], set()

            def handle_starttag(self, tag, attributes):
                values = dict(attributes)
                if values.get("id"):
                    self.ids.add(values["id"])
                if tag == "nav" and values.get("id") == "deskSettingsTabs":
                    self.nav = values
                if values.get("data-settings-group"):
                    self.groups.append(values["data-settings-group"])
                if tag == "button" and "data-settings-tab" in values:
                    self.tabs.append(values)

        parser = Nav()
        parser.feed(self.html)
        self.assertEqual(parser.nav["role"], "tablist")
        self.assertEqual(parser.nav["aria-orientation"], "vertical")
        self.assertEqual(parser.groups, ["常用", "生成线路", "本地模型", "其它"])
        self.assertEqual(len(parser.tabs), 11)
        for tab in parser.tabs:
            self.assertEqual(tab["role"], "tab")
            self.assertEqual(tab["aria-controls"], "deskSettingsBody")
        self.assertTrue({"deskSettingsSearchInput", "deskSettingsSearchResults", "deskSettingsResize"} <= parser.ids)
        self.assertFalse({"deskSettingsTabsToggle", "deskSettingsExtraTabs"} & parser.ids)
        self.assertNotIn("desk-settings-tabs__toggle {", self.controls + self.geometry)


if __name__ == "__main__":
    unittest.main()
