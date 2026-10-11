const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const frontend = path.join(__dirname, '../frontend');
const read = file => fs.readFileSync(path.join(frontend, file), 'utf8');
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[c]));

function fixture(items) {
  const document = { activeElement: null };
  const timers = new Map();
  let sequence = 0;
  const context = { document, setTimeout: fn => { timers.set(++sequence, fn); return sequence; },
    clearTimeout: id => timers.delete(id) };
  context.window = context;
  vm.createContext(context);
  // Use actual domain menu declarations and the host's injected catalog, not a
  // second list of labels that can silently drift when new node types are added.
  for (const name of ['topaz-model', 'krea2-model', 'qwen21-model', 'cyimg-model',
    'canvas-audio', 'video-control-model', 'topaz-video-pipeline', 'topaz-video-model', 'music-model', 'canvas-nodes']) {
    vm.runInContext(read(`scripts/desktop-${name}.js`), context);
  }
  const catalogSource = read('scripts/desktop-canvas.js').match(/const NODE_MENU_ITEMS = (\[[\s\S]+?\n  \]);/)[1];
  const catalog = items || vm.runInContext(catalogSource, context);
  const classes = new Set();
  const palette = {
    markup: '', groups: [], buttons: [],
    classList: { add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c) },
    contains: element => Boolean(element && element.palette),
    get innerHTML() { return this.markup; },
    set innerHTML(value) {
      this.markup = value;
      this.groups = [...value.matchAll(/<details\b([^>]*)>([\s\S]*?)<\/details>/g)].map(([, attrs, body]) => ({
        dataset: { nodeMenuGroup: attrs.match(/data-node-menu-group="([^"]+)"/)[1] },
        open: /\sopen(?:\s|$)/.test(attrs),
        types: [...body.matchAll(/data-add-node="([^"]+)"/g)].map(m => m[1]),
        count: Number(body.match(/class="desk-node-palette__count"[^>]*>(\d+)/)[1]),
        nativeAccordion: attrs.includes('name="desk-node-palette-groups"')
      }));
      this.buttons = [...value.matchAll(/data-add-node="([^"]+)"/g)].map(m => ({ type: m[1], draggable: false }));
    },
    querySelectorAll(selector) { return selector === '[data-node-menu-group]' ? this.groups : this.buttons; }
  };
  const tool = { attributes: {}, focus() { document.activeElement = this; },
    setAttribute(name, value) { this.attributes[name] = value; } };
  const timerRef = { current: 0 };
  const api = context.DesktopCanvasNodes.create({ NODE_MENU_ITEMS: catalog,
    els: { deskNodePalette: palette, deskNodeToolBtn: tool }, escapeHtml,
    nodePaletteCloseTimerRef: timerRef, ORDINARY_MENU_CLOSE_FALLBACK_MS: 200 });
  return { api, palette, catalog, document, tool, timerRef, timers };
}

test('all 23 registered nodes appear once in five semantic groups', () => {
  const h = fixture();
  const before = JSON.stringify(h.catalog);
  h.api.renderNodePaletteItems();
  const expected = {
    image: ['image', 'input', 'krea2', 'qwen21', 'cyimg_image', 'pose'],
    video: ['video', 'video_inference', 'cyimg_video', 'video_control'],
    audio: ['audio', 'music_generate', 'music_transcribe', 'music_abc', 'music_score', 'music_compare'],
    enhance: ['upscale', 'topaz', 'topaz_video'],
    general: ['text', 'comfy', 'file_output', 'layout']
  };
  assert.deepEqual(Object.fromEntries(h.palette.groups.map(g => [g.dataset.nodeMenuGroup, g.types])), expected);
  const types = h.palette.buttons.map(b => b.type);
  assert.equal(types.length, 23);
  assert.equal(new Set(types).size, types.length);
  assert.deepEqual(types.sort(), Array.from(h.catalog, item => item.type).sort());
  assert.equal(JSON.stringify(h.catalog), before, 'catalog/model objects must not be mutated');
  for (const group of h.palette.groups) {
    assert.equal(group.count, group.types.length);
    assert.ok(group.nativeAccordion);
  }
});

test('first group opens initially; rerender preserves another group or all-collapsed state', () => {
  const h = fixture();
  h.api.renderNodePaletteItems();
  assert.deepEqual(h.palette.groups.filter(g => g.open).map(g => g.dataset.nodeMenuGroup), ['image']);
  for (const group of h.palette.groups) group.open = group.dataset.nodeMenuGroup === 'audio';
  h.api.renderNodePaletteItems();
  assert.deepEqual(h.palette.groups.filter(g => g.open).map(g => g.dataset.nodeMenuGroup), ['audio']);
  for (const group of h.palette.groups) group.open = false;
  h.api.renderNodePaletteItems();
  assert.ok(h.palette.groups.every(g => !g.open));
  assert.ok(h.palette.buttons.every(b => b.draggable));
});

test('unclassified nodes fall back to General and empty groups are omitted', () => {
  const h = fixture([{ type: 'future_type', title: 'Future', subtitle: '', icon: '' }]);
  h.api.renderNodePaletteItems();
  assert.equal(h.palette.groups.length, 1);
  assert.equal(h.palette.groups[0].dataset.nodeMenuGroup, 'general');
  assert.deepEqual(h.palette.groups[0].types, ['future_type']);
  assert.ok(h.palette.groups[0].open);
  const empty = fixture([]);
  empty.api.renderNodePaletteItems();
  assert.equal(empty.palette.innerHTML, '');
});

test('palette closing/reopening preserves accordion state and handles keyboard focus', () => {
  const h = fixture();
  h.api.renderNodePaletteItems();
  h.api.setNodePaletteOpen(true);
  h.document.activeElement = { palette: true };
  h.api.setNodePaletteOpen(false);
  assert.equal(h.document.activeElement, h.tool);
  assert.equal(h.tool.attributes['aria-expanded'], 'false');
  assert.equal(h.timers.size, 1);
  h.api.setNodePaletteOpen(true);
  assert.equal(h.timers.size, 0);
  assert.equal(h.tool.attributes['aria-expanded'], 'true');
  const external = {};
  h.document.activeElement = external;
  h.api.setNodePaletteOpen(false);
  assert.equal(h.document.activeElement, external, 'do not steal focus from canvas/editors');
  for (const callback of h.timers.values()) callback();
  assert.ok(!h.palette.classList.contains('is-closing'));
  assert.ok(h.palette.groups[0].open);
});

test('shared node button remains flat, searchable and escapes full-label tooltips', () => {
  const h = fixture();
  const html = h.api.nodeMenuButtonHtml({ type: 'test"<', title: 'A "long" <title>', subtitle: 'B & C', icon: '<svg></svg>' });
  assert.ok(!html.includes('<details'));
  assert.match(html, /data-add-node="test&quot;&lt;"/);
  assert.match(html, /data-node-menu-search="a &quot;long&quot; &lt;title&gt; b &amp; c test&quot;&lt;"/);
  assert.match(html, /<strong title="A &quot;long&quot; &lt;title&gt;">/);
  assert.match(html, /<em title="B &amp; C">/);
  assert.ok(read('scripts/desktop-canvas-connections.js').includes('safeItems.map(nodeMenuButtonHtml)'));
});

test('sidebar geometry is bounded without changing the canvas connection picker', () => {
  const css = read('styles/desktop-canvas-nodes.css');
  const paletteRule = css.match(/\.desk-node-palette:not\(\.desk-node-context-menu\)\s*\{([^}]+)\}/)[1];
  for (const declaration of ['width: 320px', 'max-height: calc(100dvh - 232px)',
    'overflow-y: auto', 'overscroll-behavior: contain']) assert.ok(paletteRule.includes(declaration));
  assert.match(css, /\.desk-node-palette:not\(\.desk-node-context-menu\) button\s*\{[^}]*min-height: 48px/);
  assert.match(css, /\.desk-node-palette:not\(\.desk-node-context-menu\) :is\(strong, em\)\s*\{[^}]*white-space: nowrap/);
  assert.match(css, /\.desk-node-palette__category:focus-visible/);
});

test('host keeps click/drag creation and dispatches Escape; changed assets are cache-busted', () => {
  const host = read('scripts/desktop-canvas.js');
  assert.match(host, /deskNodePalette\?\.addEventListener\('click'[\s\S]+?closest\('\[data-add-node\]'\)[\s\S]+?addNodeFromMenu/);
  assert.match(host, /deskNodePalette\?\.addEventListener\('dragstart'[\s\S]+?application\/x-desktop-add-node/);
  assert.match(host, /if \(event.key === 'Escape'\)\s*\{[\s\S]+?setNodePaletteOpen\(false\);/);
  assert.match(host, /deskCanvasViewport\?\.addEventListener\('pointerdown', \(\) => \{[^}]*setNodePaletteOpen\(false\);\s*\}, true\)/);
  const html = read('desktop.html');
  for (const asset of ['scripts/desktop-canvas.js', 'scripts/desktop-canvas-nodes.js',
    'scripts/desktop-i18n.js', 'styles/desktop-canvas-nodes.css', 'styles/desktop-tokens.css']) {
    assert.ok(hasCacheKey(html, asset), asset);
  }
  const i18n = read('scripts/desktop-i18n.js');
  for (const group of ['image', 'video', 'audio', 'enhance', 'general']) {
    assert.equal((i18n.match(new RegExp(`nodePaletteGroup_${group}:`, 'g')) || []).length, 2);
  }
});

test('rail glass lives on a noninteractive sibling paint layer, not the menu ancestor', () => {
  const shell = read('styles/desktop-shell.css');
  const rail = shell.match(/body\.desk-app\[data-theme\] \.desk-rail\s*\{([^}]+)\}/)[1];
  const paint = shell.match(/body\.desk-app\[data-theme\] \.desk-rail::before\s*\{([^}]+)\}/)[1];
  for (const declaration of ['background: transparent', 'border: 1px solid transparent',
    '-webkit-backdrop-filter: none', 'backdrop-filter: none']) assert.ok(rail.includes(declaration));
  for (const declaration of ['pointer-events: none', 'z-index: -1', 'inset: -1px',
    'background: var(--desk-shell-rail-background)', 'border: 1px solid var(--desk-shell-rail-border)',
    'backdrop-filter: var(--desk-shell-rail-filter)']) assert.ok(paint.includes(declaration));
  assert.ok(hasCacheKey(read('desktop.html'), 'styles/desktop-shell.css'));
});

test('both palette themes keep a translucent tint over an independent backdrop blur', () => {
  const tokens = read('styles/desktop-tokens.css');
  const backgrounds = [...tokens.matchAll(/--desk-canvas-palette-background:\s*([^;]+);/g)].map(m => m[1]);
  assert.equal(backgrounds.length, 2);
  for (const fill of backgrounds) {
    const alphas = [...fill.matchAll(/rgba\([^)]*,\s*(0?\.\d+)\)/g)].map(m => Number(m[1]));
    assert.ok(alphas.length && alphas.every(alpha => alpha >= .4 && alpha < .8), fill);
  }
  const css = read('styles/desktop-canvas-nodes.css');
  const palette = css.match(/\.desk-node-palette:not\(\.desk-node-context-menu\)\s*\{([^}]+)\}/)[1];
  assert.ok(palette.includes('backdrop-filter: var(--desk-canvas-palette-filter)'));
  assert.ok(palette.includes('-webkit-backdrop-filter: var(--desk-canvas-palette-filter)'));
});
