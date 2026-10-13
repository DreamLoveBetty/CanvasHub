"""Source-only contracts for shared node geometry, material and state paint."""
from pathlib import Path
import re
import unittest
from tests.legacy_css import read_legacy_css

ROOT = Path(__file__).resolve().parents[1]

def read(name):
    return (ROOT / 'frontend' / name).read_text()

class NodeSurfaceContractTests(unittest.TestCase):
    def test_node_stroke_is_defined_and_geometry_reserves_one_pixel(self):
        tokens = read('styles/desktop-tokens.css')
        self.assertIn('--desk-node-stroke: var(--desk-node-glass-border);', tokens)
        self.assertIn('--desk-node-border-width: 1px;', tokens)
        css = read('styles/desktop-geometry.css')
        block = re.search(r'body\.desk-app\[data-theme\] \.desk-canvas \.desk-node:not\(\.desk-node--image-group\)\s*\{([^}]+)\}', css)
        self.assertIsNotNone(block)
        self.assertIn('border-width: var(--desk-node-border-width);', block[1])
        self.assertIn('border-style: solid;', block[1])
        self.assertIn('border-radius: var(--desk-node-radius);', block[1])
        self.assertRegex(read('styles/desktop-audio.css'), r'border:\s*1px solid var\(--desk-color-border-faint\)')

    def test_state_paint_covers_every_ordinary_shell_after_stable_paint(self):
        css = read('styles/desktop-canvas-nodes.css')
        start = css.index('/* Shared node frame states:')
        states = css[start:css.index('/* Node success labels', start)]
        self.assertIn('.desk-node:not(.desk-node--image-group):is(', states)
        for name in ['.is-selected', '.is-connection-drop-target', '.is-connecting', '.is-pending']:
            self.assertIn(name, states)
        self.assertNotIn('.has-settled-port-', states)
        self.assertIn('border-color: var(--desk-node-edge-stroke);', states)
        self.assertGreater(start, css.index('/* Stable glass surfaces'))

    def test_group_keeps_local_frame_geometry_but_uses_shared_state_color(self):
        tokens = read('styles/desktop-tokens.css')
        self.assertEqual(re.findall(r'--desk-image-group-selection-border:\s*([^;]+);', tokens), ['var(--desk-canvas-selection-stroke)'] * 2)
        css = read('styles/desktop-image-group.css')
        for state in ['.is-selected', '.is-connection-drop-target', '.is-connecting', '.is-pending']:
            self.assertIn(state, css)
        self.assertNotIn('.has-settled-port-', css)
        self.assertNotIn('border-width:', css)
        self.assertNotIn('border-radius:', css)

    def test_committed_connections_do_not_paint_whole_node_frames(self):
        # A saved edge is not selection. Check the legacy port stylesheet too:
        # removing only the final theme override would still highlight media.
        for asset in ['styles/desktop-liquid.css', 'styles/desktop-canvas-nodes.css', 'styles/desktop-image-group.css']:
            for selectors, declarations in re.findall(r'([^{}]+)\{([^{}]*)\}', read(asset)):
                if '.has-settled-port-' in selectors:
                    with self.subTest(asset=asset, selectors=selectors.strip()):
                        self.assertNotIn('border-color:', declarations)
                        self.assertNotIn('box-shadow:', declarations)
        legacy = read_legacy_css()
        caps = re.search(r'\.desk-node\.has-settled-port-left > \.desk-node-settled-port--left,\s*\.desk-node\.has-settled-port-right > \.desk-node-settled-port--right\s*\{([^}]+)\}', legacy)
        self.assertIsNotNone(caps)
        self.assertIn('opacity: 1;', caps[1])
        self.assertIn('background: var(--desk-node-edge-stroke);', legacy)

    def test_node_depth_is_shallow_and_selected_material_has_no_duplicate_ring(self):
        tokens = read('styles/desktop-tokens.css')
        normals = re.findall(r'--desk-node-glass-shadow:\s*([^;]+);', tokens)
        self.assertEqual(len(normals), 2)
        for shadow in normals:
            self.assertTrue('0 0 0 1px' in shadow, 'missing subtle outline layer')
            self.assertTrue('0 1px 2px -1px' in shadow, 'missing contact shadow')
            self.assertTrue('0 3px 6px -2px' in shadow, 'missing soft depth layer')
            self.assertNotRegex(shadow, r'(18|30|46|70|78)px')
        self.assertEqual(re.findall(r'--desk-node-glass-selected-shadow:\s*([^;]+);', tokens), ['var(--desk-node-selected-shadow)'] * 2)
        self.assertEqual(re.findall(r'--desk-node-text-border:\s*([^;]+);', tokens), ['var(--desk-node-glass-border)'] * 2)
        self.assertEqual(re.findall(r'--desk-node-image-selected-shadow:\s*([^;]+);', tokens), ['none'] * 2)
        css = read('styles/desktop-canvas-nodes.css')
        self.assertTrue('.desk-node:not(:is(.desk-node--image, .desk-node--video, .desk-node--image-group)) {' in css)
        self.assertTrue('.desk-video-result__preview' in css)
        performance = read('styles/desktop-performance.css')
        self.assertTrue('.desk-node:not(.desk-node--image-group)' in performance)
        self.assertTrue('.desk-image-node__placeholder' in performance)

    def test_changed_geometry_paint_and_tokens_are_cache_busted(self):
        html = read('desktop.html')
        # Bumps on change are enforced by frontend/tooling/asset-versions.mjs.
        for asset in ['styles/desktop-tokens.css', 'styles/desktop-audio.css', 'styles/desktop-geometry.css',
                      'styles/desktop-liquid.css', 'styles/desktop-canvas-nodes.css', 'styles/desktop-image-group.css']:
            self.assertRegex(html, re.escape(asset) + r'\?v=[0-9A-Za-z._-]+')

if __name__ == '__main__':
    unittest.main()
