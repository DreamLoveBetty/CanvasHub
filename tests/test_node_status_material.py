"""Portable, source-only node success paint and asset-cache contracts."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class NodeStatusMaterialTests(unittest.TestCase):
    def test_all_node_success_families_share_soft_material(self):
        css = (ROOT / 'frontend/styles/desktop-canvas-nodes.css').read_text()
        block = re.search(r'body\.desk-app\[data-theme\] \.desk-node :is\(([^)]+)\)\s*\{([^}]+)\}', css)
        self.assertIsNotNone(block)
        selectors, body = block.groups()
        self.assertEqual({s.strip() for s in selectors.split(',')}, {
            '.desk-status-pill.is-success', '.desk-pill-row span.is-success',
            '.desk-video-runtime-pill.is-online',
        })
        self.assertEqual(dict(re.findall(r'([\w-]+):\s*([^;]+);', body)), {
            'color': 'var(--desk-status-success-soft-ink)',
            'background': 'var(--desk-status-success-soft-background)',
            'background-position': 'var(--desk-status-material-position)',
            'background-repeat': 'no-repeat',
            'background-size': 'var(--desk-status-material-background-size)',
            'border-color': 'var(--desk-status-success-soft-border)',
            'box-shadow': 'var(--desk-status-success-soft-shadow)',
        })

    def test_shell_service_badges_keep_their_saturated_role(self):
        tokens = (ROOT / 'frontend/styles/desktop-tokens.css').read_text()
        self.assertEqual(re.findall(r'--desk-status-service-background:\s*([^;]+);', tokens),
                         ['var(--desk-status-success-silk-background)'] * 2)

    def test_connection_and_paint_assets_are_cache_busted(self):
        html = (ROOT / 'frontend/desktop.html').read_text()
        for asset in ['scripts/desktop-canvas-connections.js', 'scripts/desktop-canvas.js', 'styles/desktop-canvas-nodes.css']:
            with self.subTest(asset=asset):
                version = re.findall(re.escape(asset) + r'\?v=([^"\s]+)', html)
                self.assertEqual(len(version), 1)
                self.assertNotIn(version[0], ['20260831-status-silk2', '20260913-agent-result-connections1'])


if __name__ == '__main__':
    unittest.main()
