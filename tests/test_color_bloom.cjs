const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const VERSION = '20261010-color-bloom1';

function load() {
  const listeners = {};
  const context = { window: {}, document: { addEventListener: (type, fn) => { (listeners[type] ||= []).push(fn); } } };
  vm.runInNewContext(read('frontend/scripts/desktop-color-bloom.js'), context);
  return { B: context.window.DesktopColorBloom, listeners };
}

test('colour maths: normalise, HSL round trip, petal choice and arched lightness track', () => {
  const { B } = load();
  assert.equal(B.normalize('2563eb'), '#2563EB');
  assert.equal(B.normalize('#2563E'), '');
  assert.equal(B.normalize('#zzzzzz'), '');
  for (const hex of ['#2563EB', '#E03E66', '#5FB95B', '#000000', '#FFFFFF']) {
    const { h, s, l } = B.hexToHsl(hex);
    assert.equal(B.hslToHex(h, s, l), hex);
  }
  assert.equal(B.selectedPetalKey('#808080'), 'center', 'greys select the white centre');
  assert.equal(B.selectedPetalKey('#E84C3F'), 'outer-4');
  assert.equal(B.PETALS.length, 19);
  assert.deepEqual({ ...B.lightnessPoint(100) }, { x: 12, y: 12 });
  assert.equal(B.lightnessPoint(0).y, 136);
});

test('markup: host attributes ride on the HEX field and hidden value input; ids are unique per instance', () => {
  const { B, listeners } = load();
  const first = B.html({ value: '#156ca2', label: '强调色', hexClass: 'desk-input', hexAttrs: 'data-x="hex"', valueAttrs: 'data-x="color"', after: '<button data-reset></button>' });
  const second = B.html({ value: 'nope', disabled: true });
  assert.match(first, /<input type="hidden" data-color-bloom-value value="#156CA2" data-x="color">/);
  assert.match(first, /class="desk-color-bloom__hex desk-input" value="#156CA2"[^>]*data-x="hex">/);
  assert.match(first, /data-x="hex"><button data-reset><\/button><\/div>/, 'extra controls follow the HEX field');
  assert.match(first, /aria-expanded="false"/);
  assert.match(first, /tabindex="-1"/, 'closed popover keeps petals out of the tab order');
  const ids = html => [...html.matchAll(/id="(deskColorBloom\d+)"/g)].map(m => m[1]);
  assert.notEqual(ids(first)[0], ids(second)[0]);
  assert.match(first, new RegExp(`stroke="url\\(#${ids(first)[0]}Lightness\\)"`), 'gradient id is per instance');
  assert.match(second, /value="#000000"/, 'invalid values fall back to black');
  assert.match(second, /data-color-bloom-trigger[^>]*disabled/);
  assert.match(second, /data-color-bloom-value value="#000000" disabled>/);
  // One delegated listener set for every picker; Escape is taken in the capture phase.
  for (const type of ['click', 'pointerdown', 'input', 'keydown']) assert.equal(listeners[type]?.length, 1, type);
});

test('one implementation: prompt library and settings host the shared picker, not their own', () => {
  const library = read('frontend/scripts/desktop-prompt-library.js');
  assert.match(library, /window\.DesktopColorBloom\.html\(\{ value: safeColor\(value\), label: '基色'/);
  assert.match(library, /DesktopColorBloom\?\.close\(els\.deskPromptLibraryEditor, \{ focus: true \}\)/);
  assert.doesNotMatch(library, /BLOOM_PETALS|colorBloomOpen|desk-prompt-bloom|bloomLightnessPoint|toggle-color-bloom/);
  const libraryCss = read('frontend/styles/desktop-prompt-library.css');
  assert.doesNotMatch(libraryCss, /desk-prompt-bloom|desk-color-bloom__/);
  assert.match(libraryCss, /\.desk-prompt-library \.desk-color-bloom \{ --desk-color-bloom-focus: var\(--prompt-accent\); --desk-color-bloom-line: var\(--prompt-line\); \}/);
  const settings = read('frontend/scripts/desktop-settings.js');
  const material = read('frontend/scripts/desktop-control-material.js');
  for (const source of [settings, material]) assert.doesNotMatch(source, /type="color"|desk-settings-progress-color/);
  assert.match(settings, /valueAttrs: 'data-progress-preference="color"'/);
  assert.match(settings, /DesktopColorBloom\?\.close\(els\.deskSettingsPanel, \{ focus: true \}\)/);
  assert.match(material, /window\.DesktopColorBloom\?\.refresh\(card\)/);
  assert.match(read('frontend/scripts/desktop-settings-search.js'), /'\.desk-settings-color-field > span'/);
  // Settings colour-row geometry lives with the other settings geometry; colours only in settings-auth.
  assert.match(read('frontend/styles/desktop-geometry.css'), /\.desk-settings \.desk-settings-color-field \{\n  display: grid;\n  grid-template-columns: var\(--desk-settings-label-width\) minmax\(0, 1fr\);/);
  assert.doesNotMatch(read('frontend/styles/desktop-progress.css'), /desk-settings-progress-color/);
});

test('desktop.html: component CSS after the prompt library, script before every host, cache keys', () => {
  const html = read('frontend/desktop.html');
  const at = s => html.indexOf(s);
  assert.ok(at(`styles/desktop-color-bloom.css?v=${VERSION}`) > at('styles/desktop-prompt-library.css?'));
  assert.ok(at(`styles/desktop-color-bloom.css?v=${VERSION}`) < at('styles/desktop-geometry.css?'), 'settings geometry overrides the swatch size');
  const script = at(`scripts/desktop-color-bloom.js?v=${VERSION}`);
  assert.ok(script > 0);
  for (const host of ['desktop-control-material', 'desktop-settings', 'desktop-prompt-library']) {
    assert.ok(script < at(`scripts/${host}.js?`), host);
    // Hosts may have moved on since; their key must be at least as new as this change.
    assert.ok((html.match(new RegExp(`scripts/${host}\\.js\\?v=(\\d{8})`)) || [])[1] >= VERSION.slice(0, 8), host);
  }
  for (const css of ['desktop-prompt-library', 'desktop-settings-auth', 'desktop-geometry', 'desktop-progress'])
    assert.ok((html.match(new RegExp(`styles/${css}\\.css\\?v=(\\d{8})`)) || [])[1] >= VERSION.slice(0, 8), css);
});
