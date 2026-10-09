#!/usr/bin/env python3

from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def assert_asset_has_cache_bust(testcase, html: str, asset_path: str) -> None:
    testcase.assertRegex(html, re.escape(asset_path) + r"\?v=[0-9A-Za-z._-]+")


class DesktopScriptParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src"):
            self.scripts.append(attrs)


def read_canvas_module(testcase, name):
    """Read an actual, synchronously loaded canvas dependency, not an orphan file."""
    parser = DesktopScriptParser()
    parser.feed(testcase.read("desktop.html"))
    paths = [attrs["src"].split("?", 1)[0] for attrs in parser.scripts]
    module_path = f"scripts/desktop-canvas-{name}.js"
    host_path = "scripts/desktop-canvas.js"
    for path in (module_path, host_path):
        testcase.assertEqual(paths.count(path), 1, path)
        attrs = parser.scripts[paths.index(path)]
        for attribute in ("async", "defer", "nomodule"):
            testcase.assertNotIn(attribute, attrs, path)
        testcase.assertIn(attrs.get("type", "").lower(), ("", "text/javascript", "application/javascript"), path)
    testcase.assertLess(paths.index(module_path), paths.index(host_path))
    return testcase.read(module_path)


class DesktopWorkflowFileTest(unittest.TestCase):
    def read(self, rel: str) -> str:
        path = ROOT / rel
        if not path.exists() and rel.startswith(("desktop.html", "scripts/", "styles/")):
            path = ROOT / "frontend" / rel
        return path.read_text(encoding="utf-8")

    def test_desktop_has_workflow_save_load_controls(self):
        html = self.read("desktop.html")

        self.assertIn('id="deskWorkflowDockToggle"', html)
        self.assertIn('id="deskWorkflowDockPanel"', html)
        self.assertIn('id="deskWorkflowSaveBtn"', html)
        self.assertIn('id="deskWorkflowLoadBtn"', html)
        self.assertIn('id="deskWorkflowFileInput"', html)
        self.assertIn(".tcflow.json", html)
        assert_asset_has_cache_bust(self, html, "scripts/desktop-canvas.js")
        assert_asset_has_cache_bust(self, html, "scripts/desktop-api.js")
        assert_asset_has_cache_bust(self, html, "scripts/desktop-state.js")
        assert_asset_has_cache_bust(self, html, "scripts/desktop-i18n.js")
        assert_asset_has_cache_bust(self, html, "scripts/desktop-select.js")
        assert_asset_has_cache_bust(self, html, "styles/desktop-liquid.css")
        self.assertNotIn("desk-workflow-row", html)

    def test_canvas_js_exports_workflow_file_helpers(self):
        source = self.read("scripts/desktop-canvas.js")
        workflow = read_canvas_module(self, "workflow")

        for needle in (
            "tg-mini-app-img-gen.desktop-workflow",
            "exportWorkflowSnapshot",
            "applyWorkflowSnapshot",
            "saveWorkflowFile",
            "loadWorkflowFile",
            "normalizeWorkflowReference",
            "syncVisibleInputNodeStatesToCanvas",
            "dataUrlValue",
        ):
            self.assertIn(needle, source)
        self.assertIn("加载工作流会替换当前画布", source)
        self.assertIn(".tcflow.json", workflow)
        self.assertIn("showSaveFilePicker", workflow)
        self.assertIn("suggestedName", workflow)
        self.assertIn("createWritable", workflow)
        self.assertIn("保存工作流完整路径", workflow)
        self.assertIn("保存工作流文件名", workflow)
        self.assertIn("saveWorkflowToCustomPath", workflow)
        self.assertIn("deskWorkflowDockToggle", source)
        self.assertIn("setWorkflowDockOpen", source)

    def test_desktop_api_exposes_workflow_save_path(self):
        source = self.read("scripts/desktop-api.js")

        self.assertIn("saveWorkflowFileToPath", source)
        self.assertIn("/api/desktop/workflow/save", source)

    def test_server_exposes_workflow_save_endpoint(self):
        source = self.read("backend/server.py")

        self.assertIn("/api/desktop/workflow/save", source)
        self.assertIn("handle_desktop_workflow_save", source)
        self.assertIn(".tcflow.json", source)

    def test_workflow_controls_are_styled(self):
        css = self.read("styles/desktop-liquid.css")

        self.assertIn(".desk-workflow-dock-toggle", css)
        self.assertIn(".desk-workflow-dock-panel", css)
        self.assertIn("width: 240px", css)
        self.assertIn("height: 24px", css)
        self.assertIn("--desk-zoom-panel-height: 188px", css)
        self.assertIn('body.desk-app[data-theme="dark"] .desk-workflow-dock-panel button', css)
        self.assertNotIn(".desk-workflow-row", css)


if __name__ == "__main__":
    unittest.main()
