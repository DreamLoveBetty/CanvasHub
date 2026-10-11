const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'frontend/scripts/desktop-i18n.js'), 'utf8');

// A repeated key in an object literal is silent at runtime (the last value wins), so an
// earlier translation can be dead without anyone noticing; esbuild only warns. Scan source.
function duplicateKeys(block) {
  const seen = new Map(), dupes = [];
  for (const line of block.split('\n')) {
    const m = line.match(/^\s*(?:(["'])((?:\\.|(?!\1).)*)\1|([A-Za-z_$][\w$]*))\s*:/);
    if (!m) continue;
    const key = m[2] ?? m[3];
    if (seen.has(key)) dupes.push(key); else seen.set(key, true);
  }
  return dupes;
}
const between = (start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));

test('translation tables have no duplicate keys', () => {
  assert.deepEqual(duplicateKeys(between('  const exactEn = {', '\n  };')), []);
  assert.deepEqual(duplicateKeys(between('    zh: {', '\n    },')), []);
  assert.deepEqual(duplicateKeys(between('    en: {', '\n    },')), []);
});

test('"中" means Medium in selects; the layout align-center buttons use a keyed translation', () => {
  assert.match(source, /'中': 'Medium',/);
  assert.match(source, /layoutAlignCenter: '中',/);
  assert.match(source, /layoutAlignCenter: 'Center',/);
  const html = fs.readFileSync(path.join(root, 'frontend/desktop.html'), 'utf8');
  assert.equal(html.match(/data-layout-align="center" data-i18n="layoutAlignCenter"/g)?.length, 2);
});
