from __future__ import annotations

import re
import unittest
from pathlib import Path
from tests.legacy_css import read_legacy_css


ROOT = Path(__file__).resolve().parents[1]


class DesktopNodeGroupsTest(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_group_control_and_cache_busting_are_present(self):
        html = self.read("frontend/desktop.html")
        css = read_legacy_css()

        self.assertIn('id="deskSelectionGroupBtn"', html)
        self.assertIn(".desk-selection-group", css)
        self.assertIn('.desk-selection-group[data-mode="ungroup"]', css)
        self.assertRegex(
            html,
            re.escape("scripts/desktop-canvas.js") + r"\?v=[0-9A-Za-z._-]+",
        )

    def test_group_selection_drag_and_shortcut_paths_are_wired(self):
        source = self.read("frontend/scripts/desktop-canvas.js")

        for needle in (
            "function normalizeNodeGroupId",
            "function expandNodeIdsToGroups",
            "function getSelectionGroupState",
            "function toggleSelectionGroup",
            "function getSelectionUnits",
            "const groupIds = selectedIds.includes(nodeId)",
            "String(event.key || '').toLowerCase() === 'g'",
            "groupModifier = IS_MAC_PLATFORM ? event.metaKey : event.ctrlKey",
            "pointerInsideSelection",
        ):
            self.assertIn(needle, source)

    def test_workflow_normalization_preserves_valid_group_ids(self):
        source = self.read("frontend/scripts/desktop-canvas-workflow.js")

        self.assertIn("clean.groupId = normalizeNodeGroupId(clean.groupId);", source)
        self.assertIn("normalizeNodeGroups(nodes);", source)
        self.assertIn("const selectedNodeIds = expandNodeIdsToGroups(", source)

    def test_selection_bounds_meta_anchors_outside_top_left_corner(self):
        shell_geometry = self.read("frontend/styles/desktop-shell-geometry.css")
        liquid = self.read("frontend/styles/desktop-liquid.css")
        selection_js = self.read("frontend/scripts/desktop-canvas-selection.js")

        match = re.search(
            r":where\(body\.desk-app\[data-theme\]\)\s*\.desk-selection-bounds__meta\s*\{([^}]*)\}",
            shell_geometry,
            re.S,
        )
        self.assertIsNotNone(match)
        block = match.group(1)
        self.assertIn("top: var(--desk-selection-meta-top, -43px);", block)
        self.assertIn("right: calc(100% + 10px);", block)
        self.assertIn("display: inline-flex;", block)
        self.assertIn("align-items: center;", block)
        self.assertIn("height: 36px;", block)
        self.assertNotIn("left: -10px", block)
        self.assertNotIn("top: 50%", block)

        group_match = re.search(
            r":where\(body\.desk-app\[data-theme\]\)\s*\.desk-selection-group\s*\{([^}]*)\}",
            shell_geometry,
            re.S,
        )
        self.assertIsNotNone(group_match)
        self.assertIn("width: auto;", group_match.group(1))
        self.assertIn("height: 26px;", group_match.group(1))

        count_match = re.search(r"#deskSelectionCount\s*\{([^}]*)\}", liquid, re.S)
        self.assertIsNotNone(count_match)
        self.assertIn("height: 26px;", count_match.group(1))
        self.assertIn("display: inline-flex;", count_match.group(1))

        self.assertIn("--desk-selection-meta-top", selection_js)

    def test_node_drag_and_resize_suppress_trailing_click(self):
        canvas_js = self.read("frontend/scripts/desktop-canvas.js")
        connections_js = self.read("frontend/scripts/desktop-canvas-connections.js")
        self.assertRegex(
            canvas_js,
            r"type:\s*'node-drag'[\s\S]*?moved:\s*false",
        )
        self.assertRegex(
            canvas_js,
            r"type:\s*'node-resize'[\s\S]*?moved:\s*false",
        )
        self.assertRegex(
            connections_js,
            r"type:\s*'connect'[\s\S]*?moved:\s*false",
        )
        self.assertIn(
            "interaction.type === 'pan' || interaction.type === 'node-drag' || interaction.type === 'node-resize'",
            canvas_js,
        )
        self.assertIn(
            "canvasViewport.suppressClickAfterPan(event, moved)",
            canvas_js,
        )
        self.assertIn(
            "canvasViewport.suppressClickAfterPan(event, true)",
            canvas_js,
        )
        self.assertRegex(
            canvas_js,
            r"closest\('\.desk-text-node__alias'\)[\s\S]*?!getSelectedNodeIds\(\)\.includes\(node\.dataset\.nodeId\)",
        )
        self.assertIn(
            "#deskSelectionToolbar, #deskSelectionBounds",
            canvas_js,
        )


if __name__ == "__main__":
    unittest.main()
