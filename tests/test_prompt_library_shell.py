"""The prompt library opens in the asset library's shell and uses its compact control sizes."""

import re
import unittest
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def _read(relative):
    return (FRONTEND / relative).read_text(encoding="utf-8")


def _rule(css, selector):
    start = css.index(selector + " {")
    return css[start:css.index("\n}", start)]


class PromptLibraryShellTest(unittest.TestCase):
    def setUp(self):
        self.html = _read("desktop.html")
        self.module = _read("styles/desktop-prompt-library.css")
        self.geometry = _read("styles/desktop-geometry.css")
        self.liquid = _read("styles/desktop-liquid.css")

    def test_panel_takes_the_asset_library_position_size_and_paint(self):
        gallery = _rule(self.liquid, "\n.desk-gallery")
        gallery_inset = re.search(r"inset: ([^;]+);", gallery)[1]
        panel = _rule(self.module, "\n.desk-prompt-library")
        self.assertIn(f"inset: {gallery_inset};", panel)
        for declaration in ("gap: 8px;", "padding: 12px;", "background: var(--desk-gallery-panel-background);",
                            "border: 1px solid var(--desk-gallery-panel-border);",
                            "box-shadow: var(--desk-gallery-panel-shadow);", "backdrop-filter: blur(4px) saturate(1.06);"):
            self.assertIn(declaration, panel)
        self.assertIn("body.desk-history-collapsed .desk-prompt-library { right: 68px; }", self.module)
        self.assertIn("body.desk-history-collapsed .desk-gallery {\n  right: 68px;", self.liquid)
        self.assertRegex(self.module, r"@media \(max-width: 980px\) \{\n  \.desk-prompt-library,\n  body\.desk-history-collapsed \.desk-prompt-library \{\n    position: fixed;\n    inset: 48px 8px 44px 72px;")
        # Theme blocks no longer repaint the shell on top of the shared paint.
        for theme in ('body.desk-app:not([data-theme="dark"]) .desk-prompt-library', 'body.desk-app[data-theme="dark"] .desk-prompt-library'):
            self.assertNotRegex(_rule(self.module, "\n" + theme), r"\n  (background|border-color|border-radius|box-shadow|backdrop-filter):")

    def test_header_is_the_asset_library_title_row(self):
        self.assertIn('<div class="desk-prompt-library__identity">\n          <h2>提示词素材库</h2>\n        </div>', self.html)
        self.assertNotIn("desk-prompt-library__mark", self.html + self.module + self.geometry)
        self.assertIn(".desk-prompt-library__identity h2 { margin: 0; font-size: 17px; font-weight: 700; line-height: 1.1; }", self.module)

    def test_tabs_are_a_compact_single_line_row(self):
        nav = self.html[self.html.index('id="deskPromptLibraryTabs"'):self.html.index("</nav>", self.html.index('id="deskPromptLibraryTabs"'))]
        self.assertEqual(nav.count('role="tab"'), 4)
        self.assertNotIn("<small>", nav)
        self.assertEqual(len(re.findall(r'role="tab"[^>]* title="[^"]+"', nav)), 4)
        tabs = _rule(self.module, "\n.desk-prompt-library__tabs button")
        self.assertIn("height: 24px;", tabs)
        self.assertIn("padding: 0 10px;", tabs)
        self.assertNotIn(".desk-prompt-library__tabs button::after", self.module)
        # Under the current material the selected tab shares the asset library's active tab paint.
        controls = _read("styles/desktop-controls.css")
        self.assertIn('body.desk-app[data-theme] .desk-prompt-library__tabs button[aria-selected="true"]:not(:disabled),', controls)

    def test_controls_use_the_compact_sizes(self):
        self.assertIn("grid-template-rows: auto auto minmax(0, 1fr) auto;", self.geometry)
        header = _rule(self.geometry, "body.desk-app[data-theme] .desk-prompt-library__header-actions button")
        self.assertIn("height: var(--desk-control-height-sm);", header)
        self.assertIn("min-height: var(--desk-control-height-sm);", _rule(self.geometry, "body.desk-app[data-theme] .desk-prompt-library__nav button"))
        prompt_rules = [block for block in re.findall(r"[^{}]+\{[^{}]*\}", self.geometry) if "desk-prompt-library" in block.split("{")[0]]
        self.assertTrue(prompt_rules)
        self.assertFalse([block for block in prompt_rules if "--desk-control-height-md" in block])


    def test_workspace_columns_are_light_cards(self):
        cards = _rule(self.module, "\n.desk-prompt-library__nav,\n.desk-prompt-library__collection,\n.desk-prompt-library__editor")
        for declaration in ("background: var(--desk-gallery-inspector-background);",
                            "border: 1px solid var(--desk-gallery-inspector-border);",
                            "border-radius: 14px;", "box-shadow: var(--desk-gallery-inspector-shadow);"):
            self.assertIn(declaration, cards)
        self.assertIn("gap: 10px;", _rule(self.module, "\n.desk-prompt-library__workspace"))
        # No theme block repaints a column back to a see-through wash, and no divider lines remain.
        self.assertNotRegex(self.module, r"\.desk-prompt-library__(nav|collection|editor) \{ background:")
        self.assertNotRegex(self.module, r'data-theme="dark"\]\)? \.desk-prompt-library__(nav|collection|editor) \{\n  background:')
        self.assertNotRegex(self.module, r"\.desk-prompt-library__(nav|collection) \{[^}]*border-right:")

if __name__ == "__main__":
    unittest.main()
