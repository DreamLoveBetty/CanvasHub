"""Portable CSS contracts for Settings-only pale success labels."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SettingsStatusMaterialTests(unittest.TestCase):
    def test_success_roles_share_footer_material_in_both_themes(self):
        tokens = (ROOT / "frontend/styles/desktop-tokens.css").read_text()
        for role in ("summary-ok", "badge-ok", "done", "pool-chip-ok"):
            for suffix in ("ink", "background", "border"):
                if role == "badge-ok" and suffix == "border":
                    continue  # These compact badges have no geometric border.
                with self.subTest(role=role, suffix=suffix):
                    values = re.findall(
                        rf"--desk-settings-{role}-{suffix}:\s*([^;]+);", tokens
                    )
                    self.assertEqual(values, [f"var(--desk-status-success-soft-{suffix})"] * 2)

    def test_warning_roles_keep_their_distinct_material(self):
        tokens = (ROOT / "frontend/styles/desktop-tokens.css").read_text()
        for role in ("summary-warn", "badge-warn", "pool-chip-warn"):
            with self.subTest(role=role):
                values = re.findall(rf"--desk-settings-{role}-background:\s*([^;]+);", tokens)
                self.assertEqual(values, ["var(--desk-status-warning-silk-background)"] * 2)

    def test_silk_placement_is_settings_scoped_and_paint_only(self):
        css = (ROOT / "frontend/styles/desktop-settings-auth.css").read_text()
        block = re.search(
            r"body\.desk-app\[data-theme\] \.desk-settings :is\((\s*\.desk-settings__summary[\s\S]+?)\)\s*\{([^}]+)\}",
            css,
        )
        self.assertIsNotNone(block)
        selectors, body = block.groups()
        self.assertIn(".desk-settings-path:not(.is-warn) em", selectors)
        self.assertIn(".desk-settings-account:not(.is-warn)", selectors)
        self.assertIn(".desk-settings-pool-summary span.is-ok", selectors)
        self.assertIn(".desk-settings-form__actions button.is-done", selectors)
        declarations = dict(re.findall(r"([\w-]+):\s*([^;]+);", body))
        self.assertEqual(declarations, {
            "background-position": "var(--desk-status-material-position)",
            "background-repeat": "no-repeat",
            "background-size": "var(--desk-status-material-background-size)",
            "box-shadow": "var(--desk-status-success-soft-shadow)",
        })

    def test_completed_actions_override_primary_paint_but_not_loading(self):
        css = (ROOT / "frontend/styles/desktop-settings-auth.css").read_text()
        self.assertRegex(css, re.compile(
            r"body\.desk-app\[data-theme\] \.desk-settings :is\(\s*"
            r"\.desk-settings-form__actions,\s*\.desk-settings-account__actions\s*"
            r"\) button\.is-done:not\(\.is-loading\)\s*\{\s*"
            r"color: var\(--desk-settings-done-ink\);", re.S
        ))

    def test_changed_assets_have_versioned_html_references(self):
        html = (ROOT / "frontend/desktop.html").read_text()
        old_versions = {
            "desktop-tokens.css": "20260901-agent-task-shelve1",
            "desktop-settings-auth.css": "20260827-style-cleanup1",
        }
        for asset, old_version in old_versions.items():
            with self.subTest(asset=asset):
                versions = re.findall(rf'styles/{re.escape(asset)}\?v=([^"\s]+)', html)
                self.assertEqual(len(versions), 1)
                self.assertNotEqual(versions[0], old_version)


if __name__ == "__main__":
    unittest.main()
