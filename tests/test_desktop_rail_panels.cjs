const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const ROOT = path.join(__dirname, '..');

function read(relPath) {
  return fs.readFileSync(path.join(ROOT, relPath), 'utf8');
}

function makeClassList(initial = []) {
  const set = new Set(initial);
  return {
    add: (...names) => names.forEach(name => set.add(name)),
    remove: (...names) => names.forEach(name => set.delete(name)),
    contains: name => set.has(name),
    toggle: (name, force) => {
      if (force === undefined) {
        if (set.has(name)) {
          set.delete(name);
          return false;
        }
        set.add(name);
        return true;
      }
      if (force) set.add(name);
      else set.delete(name);
      return Boolean(force);
    },
  };
}

function makeElement(id, dataset = {}, classes = []) {
  const attrs = new Map();
  const listeners = new Map();
  return {
    id,
    dataset: { ...dataset },
    classList: makeClassList(classes),
    setAttribute(name, value) { attrs.set(name, String(value)); },
    getAttribute(name) { return attrs.has(name) ? attrs.get(name) : null; },
    addEventListener(type, fn) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(fn);
    },
    click() {
      for (const fn of listeners.get('click') || []) fn({ currentTarget: this, target: this });
    },
  };
}

function buildRailHarness() {
  const source = read('frontend/scripts/desktop-canvas.js');
  const helperStart = source.indexOf('  function getOpenWorkspaceTool()');
  const helperEnd = source.indexOf('\n  function nodeMenuButtonHtml', helperStart);
  const bindStart = source.indexOf("    document.querySelectorAll('.desk-rail__item[data-tool]').forEach(button => {");
  const bindEnd = source.indexOf('\n    els.deskNodePalette?.addEventListener', bindStart);
  assert.ok(helperStart > 0 && helperEnd > helperStart, 'rail helper functions should exist in desktop-canvas.js');
  assert.ok(bindStart > 0 && bindEnd > bindStart, 'rail click handler should exist in desktop-canvas.js');

  const railButtons = [
    makeElement('railSelect', { tool: 'select' }, ['desk-rail__item', 'is-active']),
    makeElement('deskNodeToolBtn', { tool: 'node' }, ['desk-rail__item']),
    makeElement('railGallery', { tool: 'gallery' }, ['desk-rail__item']),
    makeElement('railPrompts', { tool: 'prompts' }, ['desk-rail__item']),
    makeElement('railSettings', { tool: 'settings' }, ['desk-rail__item']),
  ];
  const byTool = Object.fromEntries(railButtons.map(b => [b.dataset.tool, b]));
  const panels = {
    deskGalleryPanel: makeElement('deskGalleryPanel'),
    deskPromptLibraryPanel: makeElement('deskPromptLibraryPanel'),
    deskSettingsPanel: makeElement('deskSettingsPanel'),
    deskNodePalette: makeElement('deskNodePalette'),
  };

  const state = {
    blockPromptClose: false,
    blockGalleryClose: false,
    selectedNode: 'node-1',
    clearedEdges: 0,
  };

  const ctx = {
    document: {
      getElementById: id => panels[id] || null,
      querySelectorAll: selector => selector === '.desk-rail__item[data-tool]' ? railButtons : [],
    },
    els: { deskNodePalette: panels.deskNodePalette },
    canvasNodes: {
      setNodePaletteOpen(open) {
        panels.deskNodePalette.classList.toggle('is-open', Boolean(open));
        byTool.node.setAttribute('aria-expanded', open ? 'true' : 'false');
      },
    },
    clearSelectedEdge() { state.clearedEdges += 1; },
    selectNode(id) { state.selectedNode = id; },
    DesktopResults: { showError() {} },
    window: null,
  };
  ctx.window = ctx;
  ctx.DesktopHistory = {
    async openGallery() {
      if (ctx.DesktopPromptLibrary.close() === false) return false;
      ctx.DesktopSettings.close();
      panels.deskGalleryPanel.classList.add('is-open');
      ctx.syncRailActiveTool();
      return true;
    },
    closeGallery() {
      if (state.blockGalleryClose) return;
      panels.deskGalleryPanel.classList.remove('is-open');
      ctx.syncRailActiveTool();
      return true;
    },
  };
  ctx.DesktopPromptLibrary = {
    async open() {
      if (ctx.DesktopHistory.closeGallery() === false) return false;
      ctx.DesktopSettings.close();
      panels.deskPromptLibraryPanel.classList.add('is-open');
      ctx.syncRailActiveTool();
      return true;
    },
    close() {
      if (!panels.deskPromptLibraryPanel.classList.contains('is-open')) return true;
      if (state.blockPromptClose) return false;
      panels.deskPromptLibraryPanel.classList.remove('is-open');
      ctx.syncRailActiveTool();
      return true;
    },
  };
  ctx.DesktopSettings = {
    async open() {
      if (ctx.DesktopPromptLibrary.close() === false) return false;
      if (ctx.DesktopHistory.closeGallery() === false) return false;
      panels.deskSettingsPanel.classList.add('is-open');
      ctx.syncRailActiveTool();
      return true;
    },
    close() {
      panels.deskSettingsPanel.classList.remove('is-open');
      ctx.syncRailActiveTool();
      return true;
    },
  };
  ctx.openDesktopSettingsPanel = () => { ctx.DesktopSettings.open(); };

  const script = [
    source.slice(helperStart, helperEnd),
    'this.syncRailActiveTool = syncRailActiveTool;',
    source.slice(bindStart, bindEnd),
  ].join('\n');
  vm.runInNewContext(script, ctx);

  function activeTools() {
    return railButtons.filter(b => b.classList.contains('is-active')).map(b => b.dataset.tool);
  }
  function expandedTools() {
    return railButtons.filter(b => b.getAttribute('aria-expanded') === 'true').map(b => b.dataset.tool);
  }

  return { byTool, panels, state, activeTools, expandedTools };
}

test('clicking select or node closes any open workspace panel and keeps single active highlight', () => {
  const h = buildRailHarness();

  // Open Prompts -> click Select -> closes Prompts, activates only select
  h.byTool.prompts.click();
  assert.equal(h.panels.deskPromptLibraryPanel.classList.contains('is-open'), true);
  assert.deepEqual(h.activeTools(), ['prompts']);
  assert.deepEqual(h.expandedTools(), ['prompts']);

  h.byTool.select.click();
  assert.equal(h.panels.deskPromptLibraryPanel.classList.contains('is-open'), false);
  assert.equal(h.state.selectedNode, '');
  assert.deepEqual(h.activeTools(), ['select']);
  assert.deepEqual(h.expandedTools(), []);

  // Open Settings -> click Node -> closes Settings, opens node palette, activates only node
  h.byTool.settings.click();
  assert.equal(h.panels.deskSettingsPanel.classList.contains('is-open'), true);
  assert.deepEqual(h.activeTools(), ['settings']);

  h.byTool.node.click();
  assert.equal(h.panels.deskSettingsPanel.classList.contains('is-open'), false);
  assert.equal(h.panels.deskNodePalette.classList.contains('is-open'), true);
  assert.deepEqual(h.activeTools(), ['node']);
  assert.deepEqual(h.expandedTools(), ['node']);

  // Click Node again on canvas -> closes node palette and returns highlight to select
  h.byTool.node.click();
  assert.equal(h.panels.deskNodePalette.classList.contains('is-open'), false);
  assert.deepEqual(h.activeTools(), ['select']);
  assert.deepEqual(h.expandedTools(), []);

  // Open Gallery -> click Node -> closes Gallery, opens node palette
  h.byTool.gallery.click();
  assert.equal(h.panels.deskGalleryPanel.classList.contains('is-open'), true);
  h.byTool.node.click();
  assert.equal(h.panels.deskGalleryPanel.classList.contains('is-open'), false);
  assert.equal(h.panels.deskNodePalette.classList.contains('is-open'), true);
  assert.deepEqual(h.activeTools(), ['node']);
});

test('clicking the currently open workspace rail icon toggles it closed back to canvas', () => {
  const h = buildRailHarness();

  for (const [tool, panelId] of [
    ['gallery', 'deskGalleryPanel'],
    ['prompts', 'deskPromptLibraryPanel'],
    ['settings', 'deskSettingsPanel'],
  ]) {
    h.byTool[tool].click();
    assert.equal(h.panels[panelId].classList.contains('is-open'), true, `${tool} should open`);
    assert.deepEqual(h.activeTools(), [tool]);
    assert.deepEqual(h.expandedTools(), [tool]);

    h.byTool[tool].click();
    assert.equal(h.panels[panelId].classList.contains('is-open'), false, `${tool} should toggle closed`);
    assert.deepEqual(h.activeTools(), ['select']);
    assert.deepEqual(h.expandedTools(), []);
  }
});

test('unsaved draft guard cancels select, node, and toggle-close without double highlights', () => {
  const h = buildRailHarness();

  h.byTool.prompts.click();
  h.state.blockPromptClose = true;

  h.byTool.select.click();
  assert.equal(h.panels.deskPromptLibraryPanel.classList.contains('is-open'), true);
  assert.deepEqual(h.activeTools(), ['prompts']);
  assert.deepEqual(h.expandedTools(), ['prompts']);

  h.byTool.node.click();
  assert.equal(h.panels.deskPromptLibraryPanel.classList.contains('is-open'), true);
  assert.equal(h.panels.deskNodePalette.classList.contains('is-open'), false);
  assert.deepEqual(h.activeTools(), ['prompts']);
  assert.deepEqual(h.expandedTools(), ['prompts']);

  h.byTool.prompts.click();
  assert.equal(h.panels.deskPromptLibraryPanel.classList.contains('is-open'), true);
  assert.deepEqual(h.activeTools(), ['prompts']);

  h.state.blockPromptClose = false;
  h.byTool.gallery.click();
  assert.equal(h.panels.deskPromptLibraryPanel.classList.contains('is-open'), false);
  assert.equal(h.panels.deskGalleryPanel.classList.contains('is-open'), true);

  h.state.blockGalleryClose = true;
  h.byTool.node.click();
  assert.equal(h.panels.deskGalleryPanel.classList.contains('is-open'), true);
  assert.equal(h.panels.deskNodePalette.classList.contains('is-open'), false);
  assert.deepEqual(h.activeTools(), ['gallery']);
});

test('desktop.html removes duplicate settings onclick, wires rail ARIA controls, and busts updated scripts', () => {
  const html = read('frontend/desktop.html');
  assert.doesNotMatch(html, /data-tool="settings"[^>]*onclick=/);
  assert.match(html, /data-tool="gallery"[^>]*aria-controls="deskGalleryPanel"[^>]*aria-expanded="false"/);
  assert.match(html, /data-tool="prompts"[^>]*aria-controls="deskPromptLibraryPanel"[^>]*aria-expanded="false"/);
  assert.match(html, /data-tool="settings"[^>]*aria-controls="deskSettingsPanel"[^>]*aria-expanded="false"/);
  for (const script of [
    'scripts/desktop-canvas.js',
    'scripts/desktop-history.js',
    'scripts/desktop-settings.js',
    'scripts/desktop-prompt-library.js',
  ]) {
    assert.ok(hasCacheKey(html, script), `${script} should have a cache key`);
  }
});
