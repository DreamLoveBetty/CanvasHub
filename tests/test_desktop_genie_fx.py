"""Boundary regressions for the genie engine split out of desktop-history.js."""

import re
import unittest
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def _read(relative):
    return (FRONTEND / relative).read_text(encoding="utf-8")


class DesktopGenieFxBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.html = _read("desktop.html")
        self.engine = _read("scripts/desktop-genie-fx.js")
        self.history = _read("scripts/desktop-history.js")

    def test_engine_loads_before_its_consumers_with_a_cache_key(self):
        self.assertRegex(self.html, r'scripts/desktop-genie-fx\.js\?v=[0-9A-Za-z._-]+')
        engine_at = self.html.index("scripts/desktop-genie-fx.js")
        self.assertLess(engine_at, self.html.index("scripts/desktop-history.js"))
        self.assertLess(engine_at, self.html.index("scripts/desktop-prompt-drawer.js"))

    def test_engine_owns_the_shared_api_and_reads_no_panel_state(self):
        self.assertIn("window.DeskGenieFX = {", self.engine)
        for key in ("ready:", "snapshotPanel:", "animate:", "clear:", "durationMs:"):
            self.assertIn(key, self.engine)
        for private in ("els.", "DesktopHistory", "historyGenieRunId", "historyGenieHandle", "historyGenieTimer"):
            self.assertNotIn(private, self.engine)

    def test_history_uses_the_engine_without_a_second_implementation(self):
        self.assertIn("const genieFx = window.DeskGenieFX;", self.history)
        self.assertNotIn("window.DeskGenieFX =", self.history)
        for name in (
            "snapshotHistoryPanel", "runGenieAnimationCore", "renderHistoryGenieFrame",
            "setupHistoryGenieCanvas", "genieBakeElementStyles", "genieInlineImages",
        ):
            self.assertEqual(len(re.findall(r"function " + name + r"\(", self.engine)), 1, name)
            self.assertNotIn(name, self.history, name)
        # Panel geometry, open/close state and run ids stay with the history panel.
        for name in ("historyGenieCollapsedRect", "historyGenieExpandedRect", "animateHistoryGenieClose", "animateHistoryGenieOpen"):
            self.assertIn("function " + name + "(", self.history)


if __name__ == "__main__":
    unittest.main()
