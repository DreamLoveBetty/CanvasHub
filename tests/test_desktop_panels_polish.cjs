// Regression for the desktop panel polish of 2026-10-30: combinable gallery spec facets,
// clickable record stats, a separated delete area, split settings tabs with status jumps,
// consistent settings copy, a quieter prompt assistant, and prompt-library editing defaults.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
const html = read('frontend/desktop.html');

function fakeElement() {
  const listeners = {};
  return {
    hidden: false, innerHTML: '', textContent: '', attributes: {},
    classList: { toggle() {}, contains: () => false },
    setAttribute(name, value) { this.attributes[name] = value; },
    querySelector: () => null,
    addEventListener: (type, handler) => { listeners[type] = handler; },
    contains: () => false,
    focus() {},
    listeners,
  };
}

function loadFacets() {
  const window = {};
  const document = { addEventListener() {} };
  vm.runInContext(read('frontend/scripts/desktop-gallery-facets.js'), vm.createContext({ window, document }));
  return window.DesktopGalleryFacets;
}

test('spec facets combine with AND, toggle off on a second pick and feed the asset API', () => {
  const toggle = fakeElement();
  const panel = fakeElement();
  panel.hidden = true;
  const root = fakeElement();
  root.querySelector = selector => (selector.includes('toggle') ? toggle : panel);
  let changes = 0;
  const facets = loadFacets().create({ root, escapeHtml: String, onChange: () => { changes += 1; } });
  facets.set('record', 'orphan');
  facets.set('format', 'jpg');
  assert.equal(facets.activeCount, 2);
  assert.deepEqual({ ...facets.params() }, { source: 'orphan', orientation: '', resolution: '', format: 'jpg' });
  assert.equal(facets.matches({ hasTaskRecord: false, format: 'JPEG' }), true);
  assert.equal(facets.matches({ hasTaskRecord: true, format: 'JPG' }), false);
  assert.equal(facets.matches({ hasTaskRecord: false, format: 'PNG' }), false);
  facets.set('record', 'orphan');
  assert.equal(facets.value('record'), '');
  assert.equal(changes, 3);
  facets.clear();
  assert.equal(facets.activeCount, 0);
});

test('the gallery scope select keeps one axis and specs move to the facet popover', () => {
  const select = html.slice(html.indexOf('<select id="deskGalleryFilterSelect"'), html.indexOf('</select>', html.indexOf('<select id="deskGalleryFilterSelect"')));
  for (const value of ['linked', 'orphan', 'missing_history', 'landscape', '2k', 'png']) {
    assert.ok(!select.includes(`value="${value}"`), value);
  }
  assert.equal(select.match(/<optgroup /g).length, 4);
  assert.match(html, /id="deskGalleryFacets"[\s\S]*data-gallery-facets-toggle[\s\S]*data-gallery-facets-panel/);
  const at = name => html.indexOf(`scripts/${name}?`);
  assert.ok(at('desktop-gallery-facets.js') > 0 && at('desktop-gallery-facets.js') < at('desktop-history.js'));
  assert.match(read('frontend/scripts/desktop-api.js'), /if \(options\.source\) params\.set\('source', options\.source\);/);
  const history = read('frontend/scripts/desktop-history.js');
  assert.equal(history.match(/\.\.\.galleryFacets\.params\(\),/g).length, 2);
  assert.ok(history.includes('if (!galleryFacets.matches(asset)) return false;'));
});

test('record stats filter on click and metadata refresh left the selection basket', () => {
  const history = read('frontend/scripts/desktop-history.js');
  assert.ok(history.includes("recordFilter('有记录', 'task_record_image_count', 'linked')"));
  assert.ok(history.includes("galleryFacets.set('record', record.dataset.galleryStatRecord);"));
  assert.ok(history.includes('data-gallery-refresh-meta'));
  assert.ok(!html.includes('deskGalleryRefreshMetaBtn') && !history.includes('deskGalleryRefreshMetaBtn'));
  const basket = html.slice(html.indexOf('class="desk-gallery-inspector__actions"'), html.indexOf('</aside>', html.indexOf('class="desk-gallery-inspector__actions"')));
  const danger = basket.slice(basket.indexOf('desk-gallery-inspector__danger'));
  assert.ok(danger.includes('id="deskGalleryDeleteBtn"') && danger.includes('id="deskGalleryUndoDeleteBtn"'));
  assert.ok(!basket.slice(0, basket.indexOf('desk-gallery-inspector__danger')).includes('deskGalleryDeleteBtn'));
  for (const button of basket.match(/<button [^>]*>/g)) assert.match(button, / title="/, button);
});

test('asset cards stop repeating the model and show full text on hover', () => {
  const history = read('frontend/scripts/desktop-history.js');
  assert.ok(history.includes(": [sourceBadge, asset.format].filter(Boolean).join(' · ');"));
  assert.ok(history.includes('<strong title="${escapeHtml(modelLabel)}">'));
});

test('settings split appearance and Pinterest out of system and status cards jump to their tab', () => {
  const label = tab => new RegExp(`data-settings-tab="${tab}">[\\s\\S]*?class="desk-settings-tabs__label">([^<]+)<`).exec(html)?.[1];
  assert.equal(label('appearance'), '外观');
  assert.equal(label('pinterest'), 'Pinterest');
  assert.ok(html.indexOf('data-settings-tab="appearance"') < html.indexOf('data-settings-tab="system"'));
  const settings = read('frontend/scripts/desktop-settings.js');
  assert.ok(settings.includes("html: activeTab === 'system' ? renderSystemRuntimeSettings(editableServer, setting('auth', auth)) : ''"));
  assert.ok(settings.includes("html: activeTab === 'pinterest' ? renderPinterestSettings(pinterest) : ''"));
  assert.ok(settings.includes("html: activeTab === 'appearance' ? renderCanvasInteractionSettings() : ''"));
  assert.ok(settings.includes('? renderProgressSettings() + renderControlMaterialSettings() + renderFieldStyleSettings()\n'));
  for (const tab of ['system', 'telegram', 'provider', 'third-party', 'paths', 'comfy', 'video-inference', 'prompt', 'chatgpt-pool']) {
    assert.ok(settings.includes(`{ goto: '${tab}' }`), tab);
  }
  assert.ok(settings.includes("const goto = event.target.closest('[data-settings-goto]');"));
});

test('settings copy uses one label per reasoning effort and readable model names', () => {
  const settings = read('frontend/scripts/desktop-settings.js');
  const start = settings.indexOf('  const REASONING_EFFORT_LABELS');
  const end = settings.indexOf('  function optionHtml(');
  const run = vm.runInContext(`let lastGptModelCatalog = { routes: { pool: { models: [{ id: 'gpt-image-2', label: 'GPT Image 2' }] } } };\n${settings.slice(start, end)}\n[reasoningEffortLabel('high'), reasoningEffortLabel('xhigh'), modelLabel('gpt-5-5'), modelLabel('gpt-image-2')]`, vm.createContext({}));
  assert.deepEqual([...run], ['高', '超高', 'GPT-5.5', 'GPT Image 2']);
  assert.ok(!settings.includes('optionHtml(value, value, selected'));
  for (const label of ["'Sidecar'", "'Auth File 配置'", "'AT 将过期", '保存 GPT Provider 配置']) assert.ok(!settings.includes(label), label);
});

test('the prompt assistant states the binding once and names its collapsed handle', () => {
  const drawer = read('frontend/scripts/desktop-prompt-drawer.js');
  assert.ok(!drawer.includes('无需文本节点') && !drawer.includes('title="可选"'));
  assert.ok(drawer.includes("els.deskPromptDrawerToggle?.setAttribute('aria-expanded'"));
  const geometry = read('frontend/styles/desktop-prompt-assistant-geometry.css');
  assert.match(geometry, /\.desk-prompt-drawer:not\(\.is-open\) \.desk-prompt-drawer__handle:is\(:hover, :focus-visible\)::after \{\n  opacity: 1;/);
  assert.match(read('frontend/styles/desktop-liquid.css'), /\.desk-prompt-drawer__grid \{\n  display: grid;\n  grid-template-columns: minmax\(240px, 1fr\) minmax\(270px, 1fr\);/);
  assert.ok(read('frontend/scripts/desktop-prompt-agent.js').includes("classList.toggle('is-draft', !state.run && !state.events.length)"));
  assert.match(read('frontend/styles/desktop-geometry.css'), /\.desk-agent-workbench\.is-draft \.desk-agent-pane--activity \{\n    display: none;/);
});

test('prompt library edits types by name, explains insert and opens on the list', () => {
  const library = read('frontend/scripts/desktop-prompt-library.js');
  const labels = library.match(/const TYPE_LABELS = \{[^}]*\};/)[0];
  const start = library.indexOf('  function typeIdFromLabel(text)');
  const body = library.slice(start, library.indexOf('\n  }\n', start) + 4);
  const run = vm.runInContext(`${labels}\nconst state = { templates: [{ name: '自定义类型', primary_type: 'custom_type' }] };\n${body}\n['人像人物', '海报与 KV', '自定义类型', 'mystery'].map(typeIdFromLabel)`, vm.createContext({}));
  assert.deepEqual([...run], ['portrait', 'poster', 'custom_type', 'mystery']);
  assert.ok(library.includes(".map(typeLabel).join(', ')"));
  assert.ok(!library.includes("'/ 插入'") && !library.includes('>/ 插入<') && !library.includes('# 插入'));
  assert.ok(library.includes("if (workspace !== 'blocks' && !state.selected[workspace]"));
  assert.ok(library.includes('].filter(value => value !== title)'));
});
