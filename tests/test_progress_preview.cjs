const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

function load() {
  const calls = [];
  const presenter = { update: (el, display) => calls.push(['update', el, display]), refreshPreferences: () => calls.push(['refresh']), destroy: () => calls.push(['destroy']) };
  const context = { window: { DesktopProgress: { create: options => { calls.push(['create', options]); return presenter; } } } };
  vm.runInNewContext(read('frontend/scripts/desktop-progress-preview.js'), context);
  return { P: context.window.DesktopProgressPreview, calls };
}

test('preview: one sample task on its own presenter, following preferences, released with the card', () => {
  const { P, calls } = load();
  const html = P.html();
  assert.match(html, /data-progress-preview-root/);
  assert.match(html, /<span data-progress-bar style="width:62%"><\/span>/, 'classic capsule markup for the classic style');
  const getPreferences = () => ({ style: 'liquid' });
  const preview = P.create({ getPreferences });
  const sampleRoot = {};
  const container = { querySelector: sel => (sel === '[data-progress-preview-root]' ? sampleRoot : null) };
  preview.mount(container);
  preview.mount(container); // same root: no second presenter
  assert.equal(calls.filter(c => c[0] === 'create').length, 1);
  assert.equal(calls[0][1].getPreferences, getPreferences);
  const display = calls.find(c => c[0] === 'update')[2];
  assert.equal(display.visible, true);
  assert.equal(display.percent, 62);
  assert.equal(display.elapsedText, '00:42', 'fixed clock: no per-second timer for the preview');
  preview.refresh();
  assert.ok(calls.some(c => c[0] === 'refresh'));
  preview.mount({ querySelector: () => null }); // card gone (other tab)
  assert.equal(calls.at(-1)[0], 'destroy');
  preview.refresh(); preview.release(); // no presenter: no-ops
  assert.equal(calls.filter(c => c[0] === 'destroy').length, 1);
});

test('settings card shows the preview instead of the hint; the host mounts, refreshes and releases it', () => {
  const settings = read('frontend/scripts/desktop-settings.js');
  assert.doesNotMatch(settings, /新样式将进度、阶段和用时置于轨道内/);
  assert.match(settings, /\$\{window\.DesktopProgressPreview\?\.html\(\) \|\| ''\}/);
  assert.match(settings, /els\.deskSettingsBody\.innerHTML = visibleHtml\.join\(''\);\n    \}\n    progressPreview\?\.mount\(els\.deskSettingsBody\);/);
  assert.equal(settings.match(/progressPreview\?\.refresh\(\);/g).length, 2, 'select/reset sync and colour edits');
  assert.equal(settings.match(/progressPreview\?\.release\(\);/g).length, 3, 'loading, error and drawer close');
  const css = read('frontend/styles/desktop-progress.css');
  assert.match(css, /body\.desk-app \.desk-progress-preview \.desk-progress-material \{ position: relative; top: auto;/);
  const html = read('frontend/desktop.html');
  const at = s => html.indexOf(s);
  assert.ok(hasCacheKey(html, 'scripts/desktop-progress-preview.js') && at('scripts/desktop-progress-preview.js?') > at('scripts/desktop-progress.js?'));
  assert.ok(at('scripts/desktop-progress-preview.js?') < at('scripts/desktop-settings.js?'));
  assert.ok(hasCacheKey(html, 'scripts/desktop-settings.js') && hasCacheKey(html, 'styles/desktop-progress.css'));
});

test('instrument finish: housing, well and contour-following glass edge on canvas materials only', () => {
  const css = read('frontend/styles/desktop-progress.css');
  const R = 'body.desk-app .desk-progress-material[data-progress-style]';
  const T = `${R} > .desk-progress-material__track`;
  assert.match(css, /top: calc\(100% \+ 5px\);/, '5px below the node');
  assert.ok(css.includes(`${T} > .desk-progress-material__canvas { z-index: -2; }`), 'material below the finish layers');
  assert.ok(css.includes(`${R}::before {\n  content: "";\n  display: block;\n  position: absolute;\n  inset: -3px;`), 'housing outside the box, no layout change');
  // The edge highlight is an inset top shadow on a 1px-inset layer, so it follows the rounded corners.
  assert.ok(css.includes(`${T}::before {\n  inset: 1px;\n  border-radius: 9px;`));
  assert.match(css, /box-shadow: inset 0 1px 0 rgba\(255, 255, 255, \.55\);/);
  assert.ok(css.includes(`${T}::after {\n  inset: 0;\n  border-radius: inherit;\n  box-shadow: inset 0 2px 4px rgba(0, 0, 0, .5)`));
  assert.ok(css.includes('body.desk-app[data-theme="dark"] .desk-progress-material[data-progress-style]::before {'));
  // Classic never becomes .desk-progress-material, so its capsule is untouched.
  assert.doesNotMatch(css, /desk-progress-float__bar[^{]*\{[^}]*inset: -3px/);
});
