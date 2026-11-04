// Regression for the desktop panel defects fixed on 2026-10-30: unsaved settings edits survive
// re-renders, consistent gallery wording and explained lineage badges, prompt-library dates and
// distinct module glyphs, settings access-mode copy and help glyph, and assistant mode targets.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');

function loadDrafts() {
  const window = {};
  vm.runInContext(read('frontend/scripts/desktop-settings-drafts.js'), vm.createContext({ window }));
  return window.DesktopSettingsDrafts;
}

function field(attribute, key, { type = 'text', value = '', tagName = 'INPUT' } = {}) {
  const el = {
    type, value, tagName, checked: Boolean(value),
    hasAttribute: name => name === attribute,
    getAttribute: name => (name === attribute ? key : null),
  };
  el.closest = () => el;
  return el;
}
const root = fields => ({ querySelectorAll: () => fields });
const type = (drafts, el, value) => {
  if (el.type === 'checkbox') el.checked = value; else el.value = value;
  drafts.track({ target: el });
};

test('unsaved settings edits come back after the body re-renders', () => {
  const refreshed = [];
  const drafts = loadDrafts().create({ refreshSelect: select => refreshed.push(select) });
  const url = field('data-system-setting-field', 'comfy.base_url', { value: 'http://old' });
  const timeout = field('data-gpt-provider-field', 'total_timeout_seconds', { value: '600' });
  const model = field('data-system-setting-field', 'gpt_provider.image_main_model', { value: 'a', tagName: 'SELECT', type: 'select-one' });
  const enabled = field('data-system-setting-field', 'chatgpt_pool.enabled', { type: 'checkbox', value: true });
  const session = field('data-system-setting-field', 'comfy.mode', { type: 'hidden', value: 'lan' });
  type(drafts, url, 'http://new');
  type(drafts, timeout, '900');
  type(drafts, model, 'b');
  type(drafts, enabled, false);
  type(drafts, session, 'local');
  assert.equal(drafts.size, 4, 'hidden inputs are not drafted');

  // A fresh render shows the server values again.
  const rendered = [
    field('data-system-setting-field', 'comfy.base_url', { value: 'http://old' }),
    field('data-gpt-provider-field', 'total_timeout_seconds', { value: '600' }),
    field('data-system-setting-field', 'gpt_provider.image_main_model', { value: 'a', tagName: 'SELECT', type: 'select-one' }),
    field('data-system-setting-field', 'chatgpt_pool.enabled', { type: 'checkbox', value: true }),
  ];
  drafts.restore(root(rendered));
  assert.deepEqual(rendered.map(el => (el.type === 'checkbox' ? el.checked : el.value)), ['http://new', '900', 'b', false]);
  assert.deepEqual(refreshed, [rendered[2]]);

  // Once the server reports the drafted value, the draft is in sync and dropped.
  drafts.restore(root([field('data-system-setting-field', 'comfy.base_url', { value: 'http://new' })]));
  assert.equal(drafts.size, 3);
});

test('passwords stay drafted until their card is saved', () => {
  const drafts = loadDrafts().create({ refreshSelect() {} });
  const secret = field('data-system-setting-field', 'telegram.bot_token', { type: 'password' });
  type(drafts, secret, 'token');
  const blank = field('data-system-setting-field', 'telegram.bot_token', { type: 'password' });
  drafts.restore(root([blank]));
  assert.equal(blank.value, 'token');
  drafts.restore(root([field('data-system-setting-field', 'telegram.bot_token', { type: 'password', value: 'token' })]));
  assert.equal(drafts.size, 1, 'a password equal to the field is not proof the server has it');
  drafts.forget(root([blank]));
  assert.equal(drafts.size, 0);
});

test('the settings host tracks, restores after every render and forgets saved cards', () => {
  const settings = read('frontend/scripts/desktop-settings.js');
  assert.match(settings, /els\.deskSettingsBody\.innerHTML = html;\n      els\.deskSettingsBody\.dataset\.settingsPage = activeTab;\n      settingsDrafts\.restore\(els\.deskSettingsBody\);/);
  assert.match(settings, /addEventListener\('input', event => \{\n      settingsDrafts\.track\(event\);/);
  assert.match(settings, /addEventListener\('change', event => \{\n      settingsDrafts\.track\(event\);/);
  assert.equal(settings.match(/settingsDrafts\.forget\(card\);/g).length, 3);
  assert.match(settings, /saveGptConfig\(collectGptProviderForm\(\)\);\n    settingsDrafts\.forget\(els\.deskSettingsBody, '\[data-gpt-provider-field\]'\);/);
  const html = read('frontend/desktop.html');
  const at = name => html.indexOf(`scripts/${name}?`);
  assert.ok(at('desktop-settings-drafts.js') > 0 && at('desktop-settings-drafts.js') < at('desktop-settings.js'));
});

test('gallery uses one word per concept and explains lineage badges', () => {
  const history = read('frontend/scripts/desktop-history.js');
  const html = read('frontend/desktop.html');
  for (const source of [history, html]) {
    assert.ok(!source.includes('孤儿'), 'orphan wording');
    assert.ok(!source.includes('仅归档文件') && !source.includes('有任务记录'));
  }
  assert.ok(history.includes("recordFilter('仅归档', 'orphan_asset_count', 'orphan')"));
  assert.ok(history.includes("recordFilter('未归档记录', 'history_missing_archive_count', 'missing_history')"));
  const stats = html.slice(html.indexOf('id="deskGalleryStats"'), html.indexOf('<div class="desk-gallery__body">'));
  assert.equal(stats.match(/<span>/g).length, 7, 'placeholders match the loaded stats');
  assert.match(history, /<em title="生成时参考了 \$\{refCount\} 张来源图" aria-label="来源图 \$\{refCount\} 张">源 \$\{refCount\}<\/em>/);
  assert.match(history, /<em title="以此图为参考衍生出 \$\{derivedCount\} 张图" aria-label="衍生图 \$\{derivedCount\} 张">派 \$\{derivedCount\}<\/em>/);
});

test('prompt library dates never read like fractions and module glyphs are distinct', () => {
  const library = read('frontend/scripts/desktop-prompt-library.js');
  assert.match(library, /new Intl\.DateTimeFormat\('zh-CN', \{ month: 'long', day: 'numeric' \}\)/);
  assert.match(library, /title="\$\{escapeHtml\(sideTitle\)\}"/);
  const labels = library.slice(library.indexOf('const MODULE_LABELS = {'), library.indexOf('};', library.indexOf('const MODULE_LABELS = {')) + 2);
  const icons = library.match(/const MODULE_ICONS = \{[^}]*\};/)[0];
  const start = library.indexOf('function moduleIcons(keys)');
  const body = library.slice(start, library.indexOf('\n  }\n', start) + 4);
  const run = vm.runInContext(`${icons}\n${labels}\nconst moduleLabel = key => MODULE_LABELS[key] || key;\n${body}\nmoduleIcons(Object.keys(MODULE_LABELS))`, vm.createContext({}));
  assert.equal(new Set(run).size, run.length, run.join(' '));
});

test('settings status and help read correctly', () => {
  const settings = read('frontend/scripts/desktop-settings.js');
  assert.ok(settings.includes("renderKv('访问模式', server.public_mode ? '公网' : '本机'),"));
  assert.ok(!settings.includes("renderKv('公网模式'"));
  assert.match(read('frontend/desktop.html'), /id="deskSettingsInfoBtn"[^>]*>\n\s*<svg viewBox="0 0 24 24" aria-hidden="true"><circle/);
});

test('assistant mode controls are at least 24px tall', () => {
  const geometry = read('frontend/styles/desktop-prompt-assistant-geometry.css');
  assert.match(geometry, /\.desk-prompt-mode-switch \{\n  display: grid;\n  height: 30px;/);
  assert.match(geometry, /\.desk-prompt-task-mode \{[^}]*width: 84px;\n  height: 28px;/);
  const liquid = read('frontend/styles/desktop-liquid.css');
  assert.match(liquid, /\.desk-prompt-mode-switch button:not\(\.desk-prompt-drawer__handle\) \{\n  min-height: 24px;/);
  assert.match(liquid, /\.desk-prompt-task-mode button:not\(\.desk-prompt-drawer__handle\) \{\n  position: relative;\n  z-index: 1;\n  display: grid;\n  min-width: 0;\n  height: 24px;/);
});
