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
  assert.match(geometry, /\.desk-settings__body:has\(> \.desk-settings-card \+ \.desk-settings-card\) \{\n    display: grid;\n    grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);/);
  // 限高滚动容器里用多栏会横向溢出；账号添加方式全部平铺，不再折叠。
  assert.doesNotMatch(geometry, /\.desk-settings__body[^{]*\{[^}]*columns: 2;/);
  for (const script of ['desktop-settings.js', 'desktop-google-pool.js', 'desktop-google-web.js'])
    assert.doesNotMatch(read(`frontend/scripts/${script}`), /<details/, script);
  assert.match(geometry, /\.desk-settings__body > \.desk-google-pool-tabs \{\n  grid-column: 1 \/ -1;\n  margin-bottom: 16px;/);
  const tokens = read('frontend/styles/desktop-tokens.css');
  for (const token of ['--desk-settings-panel-background: var(--desk-gallery-panel-background);', '--desk-settings-column-background: var(--desk-gallery-inspector-background);'])
    assert.equal(tokens.split(token).length - 1, 2, token);
});

test('searching before settings load says so, then re-runs once they arrive', () => {
  const S = load('frontend/scripts/desktop-settings-search.js').context.window.DesktopSettingsSearch;
  const handlers = {};
  const input = { value: '超时', setAttribute() {}, removeAttribute() {}, addEventListener: (type, fn) => { handlers[type] = fn; } };
  const results = { hidden: true, innerHTML: '', querySelectorAll: () => [], querySelector: () => null, addEventListener() {} };
  let index = null;
  const box = S.create({ input, results, getIndex: () => index, onSelect() {} });
  handlers.input();
  assert.match(results.innerHTML, /正在读取设置/);
  index = [{ tab: 'comfy', tabLabel: 'ComfyUI', cardIndex: 0, title: 'ComfyUI 服务连接', fields: ['请求超时'], notes: [] }];
  box.refresh();
  assert.match(results.innerHTML, /请求<mark>超时<\/mark>/);
  const js = read('frontend/scripts/desktop-settings.js');
  assert.match(js, /function settingsSearchIndex\(\) \{\n    if \(!lastDiagnostics\) return null;/);
  assert.ok(js.includes('    settingsSearch?.refresh();\n'));
});

test('settings nav is text only; a lone grouped card takes the row', () => {
  const html = read('frontend/desktop.html');
  const tabs = html.match(/data-settings-tab="[\w-]+">[^\n]*<\/button>/g);
  assert.equal(tabs.length, 12);
  for (const tab of tabs) assert.match(tab, /^data-settings-tab="[\w-]+"><span class="desk-settings-tabs__label">[^<]+<\/span><b class="desk-settings-tabs__dot"/);
  const geometry = read('frontend/styles/desktop-geometry.css');
  assert.ok(!(html + geometry).includes('desk-settings-tabs__glyph'));
  assert.match(geometry, /\.desk-settings-tabs button\.is-active::before \{[^}]*width: 2px;[^}]*background: currentColor;/);
  assert.match(geometry, /\.desk-settings__body:not\(\[data-settings-page="status"\]\) \.desk-settings-group__cards:has\(> :only-child\) \{\n    grid-template-columns: minmax\(0, 1fr\);/);
});

test('a settings form keeps its commands in one action row, the save command last', () => {
  const js = read('frontend/scripts/desktop-settings.js');
  // No action row directly followed by the save row: that stacked two single-button rows.
  assert.doesNotMatch(js, /<\/div>\s*\$\{renderSystemSaveButton\(/);
  assert.match(js, /function renderSystemSaveButton\(scope, label = '保存配置', secondaryActions = ''\) \{/);
  assert.match(js, /\$\{secondaryActions\}<button type="button" class="is-primary" data-system-settings-save=/);
  assert.match(js, /renderSystemSaveButton\('provider', '保存模型设置', '<button type="button" data-gpt-generation-models-refresh>刷新线路模型<\/button>'\)/);
  assert.match(js, /renderSystemSaveButton\('chatgpt-pool', '保存账号池配置', '<button type="button" data-gpt-generation-models-refresh>刷新网页模型<\/button>'\)/);
});

test('the account pool switch is a track with one sliding thumb, not a bank of keys', () => {
  const js = read('frontend/scripts/desktop-google-pool.js');
  assert.match(js, /<div class="desk-track-switch desk-google-pool-tabs" role="tablist"[^>]*style="--track-count: \$\{providers\.length\}; --track-index: \$\{index\}; --track-from: \$\{from\}; --track-elapsed: \$\{elapsed\}ms">/);
  assert.ok(!/desk-key-bank desk-google-pool-tabs|desk-google-pool-tabs--web/.test(js));
  const geometry = read('frontend/styles/desktop-geometry.css');
  assert.match(geometry, /\.desk-track-switch \{[^}]*grid-template-columns: repeat\(var\(--track-count\), minmax\(0, 1fr\)\);/);
  assert.match(geometry, /\.desk-track-switch::before \{[^}]*translate: calc\(var\(--track-index\) \* 100%\) 0;[^}]*animation: desk-track-switch-slide [^;]*calc\(-1 \* var\(--track-elapsed, 0ms\)\) both;/);
  assert.match(geometry, /@keyframes desk-track-switch-slide \{\n  from \{ translate: calc\(var\(--track-from\) \* 100%\) 0; \}/);
  assert.ok(!read('frontend/styles/desktop-google-web-geometry.css').includes('desk-google-pool-tabs--web'));
  const tokens = read('frontend/styles/desktop-tokens.css');
  for (const token of ['--desk-settings-track-background:', '--desk-settings-track-thumb-background:', '--desk-settings-track-thumb-shadow:'])
    assert.equal(tokens.split(token).length - 1, 2, token);
  assert.match(read('frontend/styles/desktop-graphite.css'), /--desk-settings-track-thumb-background: var\(--desk-graphite-card\);/);
});

test('the Gemini Web cookie file is picked with a key, not a native file field in a label', () => {
  const js = read('frontend/scripts/desktop-google-web.js');
  assert.match(js, /<div class="desk-google-web-actions desk-settings-form__actions">\$\{button\('file-pick','选择 JSON 文件'\)\}\$\{button\('accounts-import','导入 Cookie','class="is-primary" '\)\}<input type="file" accept="\.json,application\/json" data-google-web-file hidden>/);
  assert.match(js, /if\(action==='file-pick'\)\{panel\.querySelector\('\[data-google-web-file\]'\)\?\.click\(\);return true;\}/);
  assert.ok(!/<label[^>]*>[^<]*<input type="file"/.test(js));
  assert.ok(!read('frontend/styles/desktop-google-web.css').includes('desk-google-web-file'));
});

test('Gemini Web sits in a settings card and its cookie box is a settings field', () => {
  const pool = read('frontend/scripts/desktop-google-pool.js');
  assert.match(pool, /if \(provider === 'web'\) return tabs \+ renderCard\('Gemini Web 账号', \[webSettings\.render\(\)\], webSettings\.isEnabled\(\)\);/);
  const web = read('frontend/scripts/desktop-google-web.js');
  assert.match(web, /<textarea class="desk-settings-textarea" rows="4" data-google-web-cookies/);
  assert.match(web, /isEnabled:\(\)=>!!status\?\.enabled/);
  // Its button rows are settings action rows, so they take the same key paint as Google OAuth.
  assert.equal(web.match(/desk-settings-form__actions/g).length, 5, 'every Gemini Web button row, Chrome import included, is a settings action row');
  assert.match(web, /<input type="text" class="desk-input" maxlength="120" data-google-web-label/);
  assert.doesNotMatch(read('frontend/styles/desktop-google-web.css'), /desk-google-web (input|textarea|button)/, 'settings rules own Gemini Web fields and keys');
  // Dark settings fields take the field tokens, so graphite's mapping applies in dark too.
  assert.doesNotMatch(read('frontend/styles/desktop-liquid.css'), /\[data-theme="dark"\] \.desk-settings-textarea \{/);
});

test('prompt skill settings support Google OAuth pool LLM models and group account pool chips', () => {
  const api = read('frontend/scripts/desktop-api.js');
  assert.match(api, /if \(options\.refresh\) query\.set\('refresh', '1'\)/);
  const settings = read('frontend/scripts/desktop-settings.js');
  assert.match(settings, /lastPromptConfig = \{ \.\.\.payload, selected_provider: provider \|\| payload\?\.provider \|\| '' \}/);
  assert.match(settings, /currentProvider === 'google_pool'/);
  assert.match(settings, /renderKv\('服务商', promptProviderLabel\(promptRuntime, cfg\.provider \|\| promptRuntime\?\.provider\)\)/);
  const pool = read('frontend/scripts/desktop-google-pool.js');
  assert.match(pool, /modelRow\('图像', imageModels\) \+ modelRow\('LLM', textModels\)/);
});

test('model-tools page uses a top track switch to show one model module at a time while keeping all cards searchable', () => {
  const settings = read('frontend/scripts/desktop-settings.js');
  assert.match(settings, /<div class="desk-track-switch desk-model-tools-tabs" role="tablist"/);
  for (const id of ['krea2', 'qwen21', 'moss', 'common']) {
    assert.ok(settings.includes(`{ id: '${id}'`), `model-tools stop ${id}`);
  }
  assert.match(settings, /if \(buildingSearchIndex\) \{\s*return MODEL_TOOLS_TABS\.map\(item => renderModelToolsSubtabContent\(item\.id\)\)\.join\(''\);\s*\}/);
  assert.match(settings, /const targetSubtab = modelToolsSubtabForCardTitle\(hit\.entry\.title\);/);
  const geometry = read('frontend/styles/desktop-geometry.css');
  assert.match(geometry, /\.desk-settings__body > \.desk-model-tools-tabs,\nbody\.desk-app\[data-theme\] \.desk-settings__body > \.desk-google-pool-tabs \{/);
  assert.match(geometry, /scale: calc\(1 - 0\.34 \* var\(--track-travel\)\) calc\(1 \+ 0\.15 \* var\(--track-travel\)\);/);
  assert.match(geometry, /scale: calc\(1 \+ 0\.11 \* var\(--track-travel\)\) calc\(1 - 0\.09 \* var\(--track-travel\)\);/);
});
