"""Portable exit timing/material contracts; notification dwell is not animation."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ExitMotionContractTests(unittest.TestCase):
    def test_exit_is_shorter_and_displacement_is_quiet(self):
        tokens = (ROOT/'frontend/styles/desktop-tokens.css').read_text()
        duration = lambda key: int(re.search(re.escape(key)+r':\s*(\d+)ms;', tokens)[1])
        self.assertLess(duration('--desk-motion-duration-exit'), duration('--desk-motion-duration-normal'))
        self.assertLess(duration('--desk-motion-duration-exit'), duration('--desk-motion-duration-slow'))
        self.assertTrue('--desk-motion-distance-exit: 2px;' in tokens)
        self.assertTrue('--desk-motion-scale-exit: 0.995;' in tokens)
        transition = re.search(r'--desk-motion-surface-exit-transition:\s*([^;]+);', tokens)[1]
        self.assertEqual(transition.count('var(--desk-motion-duration-exit)'), 3)
        css = (ROOT/'frontend/styles/desktop-motion.css').read_text()
        self.assertTrue('var(--desk-motion-distance-exit)' in css)
        self.assertNotIn('translateY(var(--desk-motion-distance-md))', css)

    def test_dwell_and_special_component_lifecycles_are_not_retimed(self):
        result = (ROOT/'frontend/scripts/desktop-results.js').read_text()
        self.assertRegex(result, r'\},\s*3600\)')
        css = (ROOT/'frontend/styles/desktop-motion.css').read_text()
        self.assertNotRegex(css, r'filter:\s*blur\([^\n]+(?=\n)[\s\S]*?\.desk-canvas-world')
        self.assertNotIn('.desk-image-group__liquid {', css)

    def test_reduced_motion_also_resets_exit_and_icon_tokens(self):
        tokens = (ROOT/'frontend/styles/desktop-tokens.css').read_text()
        reduced = tokens[tokens.rindex('@media (prefers-reduced-motion: reduce)'):]
        for rule in ['--desk-motion-duration-exit: 1ms;', '--desk-motion-distance-exit: 0px;', '--desk-motion-scale-exit: 1;', '--desk-motion-icon-blur: 0px;']:
            self.assertTrue(rule in reduced, rule)
        html = (ROOT/'frontend/desktop.html').read_text()
        self.assertRegex(html, re.escape('styles/desktop-motion.css') + r'\?v=[0-9A-Za-z._-]+')

if __name__ == '__main__':
    unittest.main()
