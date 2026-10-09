"""Portable contracts for the footer's stationary information label."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class StatusFeedbackStyleTests(unittest.TestCase):
    def test_feedback_label_reuses_the_queue_palette_without_focus_motion(self):
        css = (ROOT / 'frontend/styles/desktop-shell.css').read_text()
        block = re.search(
            r'body\.desk-app\[data-theme\] \.desk-status-group--feedback :is\(span, \.desk-status-feedback-trigger\)\s*\{([^}]+)\}',
            css,
        ).group(1)
        for declaration in (
            'color: var(--desk-status-ok-ink);',
            'background: var(--desk-status-ok-background);',
            'border: 1px solid var(--desk-status-ok-border);',
            'box-shadow: var(--desk-status-feedback-shadow);',
            'transition: none;', 'animation: none;', 'transform: none;', 'filter: none;',
        ):
            self.assertIn(declaration, block)
        # Tone remains task metadata, not a competing button material.
        self.assertNotRegex(css, r'\.desk-status-feedback-trigger\[data-tone=')
        self.assertIn('.desk-status-feedback-trigger:focus-visible', css)
        self.assertIn('outline: 2px solid var(--desk-color-focus-border);', css)

    def test_footer_keeps_indicators_scrollable_and_separates_the_aligned_label(self):
        html = (ROOT / 'frontend/desktop.html').read_text()
        css = (ROOT / 'frontend/styles/desktop-shell.css').read_text()
        self.assertIn('id="deskStatusBarStatus"', html)
        self.assertIn('class="desk-status-indicators"', html)
        self.assertIn('aria-labelledby="deskTodayCount deskQueueCount"', html)
        self.assertIn('tabindex="0"', html)
        self.assertIn('--desk-status-dock-width', css)
        self.assertIn('--desk-status-dock-trailing', css)
        block = re.search(r'body\.desk-app\[data-theme\] \.desk-status-indicators\s*\{([^}]+)\}', css).group(1)
        self.assertIn('min-width: 0;', block)
        self.assertIn('overflow-x: auto;', block)
        for asset in ['styles/desktop-shell.css', 'styles/desktop-tokens.css']:
            version = '20261009-settings-drawer2' if asset == 'styles/desktop-tokens.css' else '20261006-node-palette-frost1'
            self.assertIn(asset + '?v=' + version, html)
        self.assertIn('scripts/desktop-results.js?v=20261007-node-progress4', html)

    def test_log_shadow_is_recessed_in_both_themes_without_changing_other_chips(self):
        tokens = (ROOT / 'frontend/styles/desktop-tokens.css').read_text()
        shadows = re.findall(r'--desk-status-feedback-shadow:\s*([^;]+);', tokens)
        self.assertEqual(len(shadows), 2)
        for shadow in shadows:
            layers = re.sub(r'rgba?\([^)]*\)', 'color', shadow).split(',')
            self.assertEqual(len(layers), 3)
            self.assertTrue(all(layer.strip().startswith('inset ') for layer in layers))
            self.assertIn('inset 0 -1px 0', shadow)
        # The log owns its inset material; today's/queue elevation is unchanged.
        self.assertEqual(tokens.count('--desk-status-ok-shadow: var(--desk-status-success-soft-shadow);'), 2)
        css = (ROOT / 'frontend/styles/desktop-shell.css').read_text()
        chip = re.search(r'body\.desk-app\[data-theme\] \.desk-status-chip--ok\s*\{([^}]+)\}', css).group(1)
        self.assertIn('box-shadow: var(--desk-status-ok-shadow);', chip)

    def test_long_task_identity_does_not_displace_the_close_control(self):
        css = (ROOT / 'frontend/styles/desktop-shell.css').read_text()
        block = re.search(r'#deskStatusTip \.desk-status-tip__head > div\s*\{([^}]+)\}', css).group(1)
        self.assertIn('min-width: 0;', block)
        close = re.search(r'#deskStatusTip \.desk-status-tip__head button\s*\{([^}]+)\}', css).group(1)
        self.assertIn('flex: 0 0 var(--desk-control-height-xs);', close)
        feedback = re.search(r'body\.desk-app\[data-theme\] \.desk-status-group--feedback\s*\{([^}]+)\}', css).group(1)
        self.assertIn('max-width: none;', feedback)


if __name__ == '__main__':
    unittest.main()
