from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DesktopNodeGroupsTest(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_group_control_and_cache_busting_are_present(self):
        html = self.read("frontend/desktop.html")
        css = self.read("frontend/styles/desktop-liquid.css")

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


if __name__ == "__main__":
    unittest.main()
