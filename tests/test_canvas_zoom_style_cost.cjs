const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

// Measured on a 22-node canvas (2026-10-09): updating an inherited custom property on the
// canvas world every zoom frame restyled all ~2000 descendants (31 → 59 fps when removed;
// 24 → 51 fps with Glass buttons). Canvas transforms must stay style-cheap.
test('canvas viewport does not write inherited custom properties on the world per frame', () => {
  const viewport = read('frontend/scripts/desktop-canvas-viewport.js');
  assert.doesNotMatch(viewport, /--desk-canvas-scale/);
  assert.doesNotMatch(viewport, /deskCanvasWorld\.style\.setProperty\(\s*'--/);
  // Nothing may start depending on the removed variable without re-registering it.
  for (const dir of ['frontend/styles', 'frontend/scripts']) {
    for (const file of fs.readdirSync(path.join(root, dir))) {
      if (/\.(css|js)$/.test(file)) assert.doesNotMatch(read(`${dir}/${file}`), /var\(--desk-canvas-scale/, file);
    }
  }
  // Grid variables on the viewport stay non-inherited (desktop-performance.css).
  const perf = read('frontend/styles/desktop-performance.css');
  for (const name of ['x', 'y', 'size']) assert.match(perf, new RegExp(`@property --canvas-grid-${name}[^}]*inherits: false`));
});
