const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const VERSION = '20261009-settings-drawer2';

function load(file, extra = {}) {
  const listeners = {};
  const context = { AbortController, window: { addEventListener: (type, fn) => { (listeners[type] ||= []).push(fn); }, innerWidth: 1440, requestAnimationFrame: fn => fn() }, document: {}, ...extra };
  vm.runInNewContext(read(file), context);
  return { context, listeners };
}

function element() {
  const handlers = {}, attrs = {}, style = {}, classes = new Set();
  return {
    attrs, style: { setProperty: (k, v) => { style[k] = v; } }, styleMap: style, classes,
    classList: { add: c => classes.add(c), remove: c => classes.delete(c) },
    setAttribute: (k, v) => { attrs[k] = String(v); },
    setPointerCapture() {},
    addEventListener: (type, fn) => { (handlers[type] ||= []).push(fn); },
    fire(type, event = {}) { (handlers[type] || []).forEach(fn => fn({ preventDefault() {}, button: 0, pointerId: 1, ...event })); },
  };
}

test('drawer width: 760 default, 560–1100 stored, displayed width also fits the window', () => {
  const D = load('frontend/scripts/desktop-settings-drawer.js').context.window.DesktopSettingsDrawer;
  assert.equal(D.DEFAULT, 760);
  assert.equal(D.normalizeWidth(undefined), 760);
  assert.equal(D.normalizeWidth(200), 560);
  assert.equal(D.normalizeWidth(5000), 1100);
  assert.equal(D.displayWidth(1100, 900), 804, 'rail + gutter stay visible');
  assert.equal(D.displayWidth(900, 2560), 900);
});

test('drawer resizing: drag, keyboard, double-click reset; persists only committed widths', () => {
  const { context } = load('frontend/scripts/desktop-settings-drawer.js');
  const D = context.window.DesktopSettingsDrawer;
  const panel = element(), handle = element(), saved = [];
  let stored = 760;
  const drawer = D.create({ panel, handle, getWidth: () => stored, setWidth: w => { stored = w; saved.push(w); }, viewportWidth: () => 1600, requestFrame: fn => fn() });
  assert.equal(panel.styleMap['--desk-settings-width'], '760px');
  assert.equal(handle.attrs['aria-valuemin'], '560');
  handle.fire('pointerdown', { clientX: 900 });
  assert.ok(panel.classes.has('is-resizing'));
  handle.fire('pointermove', { clientX: 1000 });
  handle.fire('pointermove', { clientX: 1140 });
  assert.equal(panel.styleMap['--desk-settings-width'], '1000px');
  assert.deepEqual(saved, [], 'nothing persisted mid-drag');
  handle.fire('pointerup', {});
  assert.deepEqual(saved, [1000]);
  assert.ok(!panel.classes.has('is-resizing'));
  handle.fire('keydown', { key: 'ArrowLeft' });
  assert.equal(drawer.width(), 980);
  handle.fire('keydown', { key: 'End' });
  assert.equal(drawer.width(), 1100);
  handle.fire('dblclick', {});
  assert.equal(drawer.width(), 760);
  assert.deepEqual(saved, [1000, 980, 1100, 760]);
});

test('search: every term must match; titles outrank fields; hint-only matches are labelled', () => {
  const S = load('frontend/scripts/desktop-settings-search.js').context.window.DesktopSettingsSearch;
  const entries = [
    { tab: 'system', tabLabel: '系统', cardIndex: 2, title: '节点按钮材质', fields: ['按钮材质', '强调色 · 悬停 / 焦点'], notes: [] },
    { tab: 'telegram', tabLabel: 'Telegram', cardIndex: 0, title: 'Telegram 与访问', fields: ['Bot Token', 'Telegram 代理'], notes: [] },
    { tab: 'comfy', tabLabel: 'ComfyUI', cardIndex: 0, title: 'ComfyUI 服务连接', fields: ['Base URL'], notes: ['Base URL 已包含协议、地址和端口'] },
    { tab: 'paths', tabLabel: '路径', cardIndex: 0, title: '路径与存储', fields: ['归档目录'], notes: [] },
  ];
  assert.equal(S.search(entries, '')?.length, 0);
  const material = S.search(entries, '强调色');
  assert.equal(material.length, 1);
  assert.equal(material[0].entry.tab, 'system');
  assert.equal(material[0].field, '强调色 · 悬停 / 焦点');
  assert.equal(S.search(entries, 'TELEGRAM 代理')[0].field, 'Telegram 代理');
  const viaNote = S.search(entries, '地址');
  assert.equal(viaNote.length, 1);
  assert.equal(viaNote[0].viaNote, true);
  assert.equal(S.search(entries, 'comfyui 地址')[0].entry.tab, 'comfy');
  assert.equal(S.search(entries, '不存在的设置').length, 0);
  assert.equal(S.highlight('<b>强调色</b>', '强调'), '&lt;b&gt;<mark>强调</mark>色&lt;/b&gt;');
});

test('settings host: categories are built off-screen from loaded data; drawer and search are separate modules', () => {
  const js = read('frontend/scripts/desktop-settings.js');
  assert.match(js, /function buildSections\(data, tab\) \{\n\s+const activeTab = tab;/);
  assert.match(js, /buildSections\(lastDiagnostics, category\.tab\)\.sections/);
  assert.match(js, /function selectTab\(tab\)/);
  assert.match(js, /DesktopSettingsDrawer\?\.create\(/);
  assert.match(js, /DesktopSettingsSearch\?\.create\(/);
  assert.doesNotMatch(js, /EXTRA_SETTINGS_TABS|tabsExpanded|deskSettingsTabsToggle/);
  const prefs = read('frontend/scripts/desktop-preferences.js');
  assert.match(prefs, /settingsWidth: state\.settingsWidth/);
  assert.match(prefs, /DesktopSettingsDrawer\?\.normalizeWidth/);
  const html = read('frontend/desktop.html');
  const at = s => html.indexOf(s);
  assert.ok(at(`scripts/desktop-settings-drawer.js?v=${VERSION}`) > 0 && at('scripts/desktop-settings-drawer.js?') < at('scripts/desktop-preferences.js?'));
  assert.ok(at('scripts/desktop-settings-search.js?v=20261010-color-bloom1') > 0 && at('scripts/desktop-settings-search.js?') < at('scripts/desktop-settings.js?'));
  assert.match(html, /<section class="desk-settings desk-settings--drawer" id="deskSettingsPanel" role="dialog" aria-modal="false"/);
  assert.doesNotMatch(html, /id="deskSettingsPanel"[^>]*desk-glass|class="desk-settings desk-glass/);
});

test('drawer geometry: between title bar and status bar, right of the rail, no backdrop blur', () => {
  const geometry = read('frontend/styles/desktop-geometry.css');
  const block = geometry.match(/body\.desk-app\[data-theme\] \.desk-settings \{([^}]+)\}/)[1];
  for (const declaration of ['--desk-settings-drawer-top: 42px;', '--desk-settings-drawer-bottom: 36px;', '--desk-settings-drawer-left: 72px;', 'width: var(--desk-settings-width, 760px);', 'transform: translateX(-24px);'])
    assert.ok(block.includes(declaration), declaration);
  assert.match(geometry, /\.desk-settings--drawer \{\n  -webkit-backdrop-filter: none;\n  backdrop-filter: none;/);
  assert.match(geometry, /@container desk-settings-content \(min-width: 820px\)/);
  const tokens = read('frontend/styles/desktop-tokens.css');
  for (const alpha of ['0.97', '0.98']) assert.ok(tokens.includes(alpha));
});
