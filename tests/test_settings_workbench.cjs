const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

function load(file, extra = {}) {
  const listeners = {};
  const context = { AbortController, window: { addEventListener: (type, fn) => { (listeners[type] ||= []).push(fn); }, innerWidth: 1440, requestAnimationFrame: fn => fn() }, document: {}, ...extra };
  vm.runInNewContext(read(file), context);
  return { context, listeners };
}

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

test('settings host: categories are built off-screen from loaded data; search is a separate module', () => {
  const js = read('frontend/scripts/desktop-settings.js');
  assert.match(js, /function buildSections\(data, tab\) \{\n\s+const activeTab = tab;/);
  assert.match(js, /buildSections\(lastDiagnostics, category\.tab\)\.sections/);
  assert.match(js, /function selectTab\(tab\)/);
  assert.match(js, /DesktopSettingsSearch\?\.create\(/);
  assert.doesNotMatch(js, /EXTRA_SETTINGS_TABS|tabsExpanded|deskSettingsTabsToggle|DesktopSettingsDrawer|deskSettingsResize/);
  assert.match(js, /label: button\.querySelector\('\.desk-settings-tabs__label'\)\?\.textContent\.trim\(\) \|\| ''/);
  const prefs = read('frontend/scripts/desktop-preferences.js');
  assert.doesNotMatch(prefs, /settingsWidth|DesktopSettingsDrawer/);
  assert.ok(!fs.existsSync(path.join(root, 'frontend/scripts/desktop-settings-drawer.js')));
  const html = read('frontend/desktop.html');
  const at = s => html.indexOf(s);
  assert.ok(!html.includes('desktop-settings-drawer.js') && !html.includes('deskSettingsResize'));
  assert.ok(hasCacheKey(html, 'scripts/desktop-settings-search.js') && at('scripts/desktop-settings-search.js?') < at('scripts/desktop-settings.js?'));
  assert.match(html, /<section class="desk-settings desk-settings--workbench" id="deskSettingsPanel" role="dialog" aria-modal="false"/);
  assert.doesNotMatch(html, /id="deskSettingsPanel"[^>]*desk-glass|class="desk-settings desk-glass/);
});

// The section helpers run on their own: extract them with the constants they use.
function loadSectionHelpers(statusHtml) {
  const js = read('frontend/scripts/desktop-settings.js');
  const slice = (from, to) => js.slice(js.indexOf(from), js.indexOf(to, js.indexOf(from)));
  const source = [
    slice('  const STATUS_AREAS', '\n\n'),
    slice('  function groupedSectionsHtml(', '\n  // Each tab'),
    slice('  function tabStatuses(', '\n  function tabButton('),
  ].join('\n');
  const context = {
    escapeHtml: value => String(value),
    buildSections: () => ({ sections: [{ tab: 'status', html: statusHtml }] }),
    tabStatusCache: null,
  };
  vm.runInNewContext(`let tabStatusCache = null;\n${source}\nthis.api = { STATUS_AREAS, groupedSectionsHtml, tabStatuses };`, context);
  return context.api;
}

test('cards group by area on the status page and by group elsewhere, keeping card order', () => {
  const { STATUS_AREAS, groupedSectionsHtml } = loadSectionHelpers('');
  assert.deepEqual([...STATUS_AREAS], ['系统与访问', '生成线路', '本地服务', '提示词与投递']);
  const status = groupedSectionsHtml([
    { area: '生成线路', html: '<i>pool</i>' },
    { area: '系统与访问', html: '<i>system</i>' },
    { area: '本地服务', html: '' },
  ], 'area', STATUS_AREAS);
  assert.ok(status.indexOf('系统与访问') < status.indexOf('生成线路'), 'areas follow the fixed order');
  assert.ok(!status.includes('本地服务'), 'empty areas are left out');
  const tab = groupedSectionsHtml([
    { group: '模型与传输', html: '<i>a</i>' }, { group: '模型与传输', html: '<i>b</i>' }, { group: '托管 Codex 账号', html: '<i>c</i>' },
  ], 'group');
  assert.deepEqual(tab.match(/<i>\w<\/i>/g), ['<i>a</i>', '<i>b</i>', '<i>c</i>']);
  assert.equal(tab.match(/desk-settings-group__title/g).length, 2);
  assert.equal(groupedSectionsHtml([{ html: '<i>x</i>' }, { html: '' }], 'group'), '<i>x</i>', 'ungrouped pages stay plain');
});

test('navigation lamps follow the status overview cards', () => {
  const card = (state, goto) => `<section class="desk-settings-card ${state}"><header><h3>t</h3><button data-settings-goto="${goto}">去设置</button></header></section>`;
  const { tabStatuses } = loadSectionHelpers(card('is-ok', 'telegram') + card('is-warn', 'telegram') + card('is-ok', 'comfy'));
  const statuses = tabStatuses({});
  assert.equal(statuses.telegram, 'warn', 'any warning card wins');
  assert.equal(statuses.comfy, 'ok');
  assert.equal(statuses.status, 'warn');
});

test('workbench geometry: the asset library place, light glass, two light columns', () => {
  const geometry = read('frontend/styles/desktop-geometry.css');
  const block = geometry.match(/body\.desk-app\[data-theme\] \.desk-settings \{([^}]+)\}/)[1];
  for (const declaration of ['inset: 52px calc(var(--desk-side-panel-width) + 18px) 48px 78px;', '--desk-settings-control-height: var(--desk-control-height-sm);', '--desk-radius-control: 6px;'])
    assert.ok(block.includes(declaration), declaration);
  assert.match(geometry, /\.desk-settings--workbench \{\n  -webkit-backdrop-filter: blur\(4px\) saturate\(1\.06\);\n  backdrop-filter: blur\(4px\) saturate\(1\.06\);/);
  assert.match(geometry, /@container desk-settings-content \(min-width: 760px\)/);
  assert.match(geometry, /\.desk-settings__body:has\(> \.desk-settings-card \+ \.desk-settings-card\) \{\n    columns: 2;/);
  const tokens = read('frontend/styles/desktop-tokens.css');
  for (const token of ['--desk-settings-panel-background: var(--desk-gallery-panel-background);', '--desk-settings-column-background: var(--desk-gallery-inspector-background);'])
    assert.equal(tokens.split(token).length - 1, 2, token);
});
