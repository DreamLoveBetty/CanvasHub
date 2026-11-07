const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { hasCacheKey } = require('./asset_keys.cjs');

const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

function fakeList({ cardHeight = 148, rowGap = '8px', padding = '1px' } = {}) {
  const props = new Map();
  const card = cardHeight == null ? null : { offsetHeight: cardHeight };
  return {
    isConnected: true,
    computed: { rowGap, paddingTop: padding, paddingBottom: padding },
    style: {
      setProperty: (key, value) => props.set(key, value),
      removeProperty: key => props.delete(key),
      getPropertyValue: key => props.get(key) || '',
    },
    querySelector: selector => (selector === '.desk-comfy-workflow-card' ? card : null),
    setCardHeight(value) { card.offsetHeight = value; },
  };
}

function load(lists) {
  const observers = [];
  class ResizeObserver {
    constructor(callback) { this.callback = callback; this.targets = new Set(); observers.push(this); }
    observe(target) { this.targets.add(target); }
    unobserve(target) { this.targets.delete(target); }
    disconnect() { this.targets.clear(); }
    fire(target, width, height = 230) { this.callback([{ target, contentRect: { width, height } }]); }
  }
  const context = {
    window: {},
    ResizeObserver,
    getComputedStyle: element => element.computed,
    document: { querySelectorAll: () => lists },
  };
  vm.runInNewContext(read('frontend/scripts/desktop-canvas-comfy-layout.js'), context);
  return { Layout: context.window.DesktopCanvasComfyLayout, observers };
}

test('the workflow card list is one card, a row gap and half a card tall', () => {
  const { Layout } = load([]);
  assert.equal(Layout.VISIBLE_CARDS, 1.5);
  assert.equal(Layout.listHeight(148, 8, 2), 232);
  const list = fakeList();
  Layout.create().sync(list);
  assert.equal(list.style.getPropertyValue('--desk-comfy-workflow-list-height'), '232px');
  // No cards (empty catalog): fall back to the stylesheet default.
  const empty = fakeList({ cardHeight: null });
  empty.style.setProperty('--desk-comfy-workflow-list-height', '300px');
  Layout.create().sync(empty);
  assert.equal(empty.style.getPropertyValue('--desk-comfy-workflow-list-height'), '');
});

test('lists are re-measured when their width changes, not when the written height resizes them', () => {
  const list = fakeList();
  const lists = [list];
  const { Layout, observers } = load(lists);
  const layout = Layout.create();
  layout.reconcile();
  layout.reconcile();
  assert.equal(observers.length, 1);
  assert.equal(observers[0].targets.size, 1, 'each list is observed once');
  observers[0].fire(list, 390);
  assert.equal(list.style.getPropertyValue('--desk-comfy-workflow-list-height'), '232px');
  // Height-only change caused by our own write: no re-measure even if the card moved.
  list.setCardHeight(175);
  observers[0].fire(list, 390, 232);
  assert.equal(list.style.getPropertyValue('--desk-comfy-workflow-list-height'), '232px');
  // A narrower node re-flows to fewer, wider columns: taller cards, taller list.
  observers[0].fire(list, 330);
  assert.equal(list.style.getPropertyValue('--desk-comfy-workflow-list-height'), '273px');
  // Removed nodes are dropped on the next reconcile.
  list.isConnected = false;
  lists.length = 0;
  layout.reconcile();
  assert.equal(observers[0].targets.size, 0);
});

test('the card list holds its height and only the input panel stretches', () => {
  const css = read('frontend/styles/desktop-canvas-nodes-geometry.css');
  assert.match(css, /\.desk-comfy-workflow-list \{[^}]*flex: 0 1 var\(--desk-comfy-workflow-list-height, 230px\);/);
  assert.match(css, /\.desk-comfy-node__params \{[^}]*flex: 1 1 0;[^}]*min-height: 130px;/);

  const html = read('frontend/desktop.html');
  assert.ok(hasCacheKey(html, 'scripts/desktop-canvas-comfy-layout.js'));
  const at = file => html.indexOf(`scripts/${file}?v=`);
  assert.ok(at('desktop-canvas-comfy-layout.js') < at('desktop-canvas.js'), 'layout module loads before the host');

  const host = read('frontend/scripts/desktop-canvas.js');
  assert.match(host, /const canvasComfyLayout = window\.DesktopCanvasComfyLayout\.create\(\);/);
  assert.equal(host.split('comfyLayout: canvasComfyLayout').length - 1, 2, 'nodes and model nodes share one instance');
  assert.match(read('frontend/scripts/desktop-canvas-nodes.js'), /comfyLayout\?\.reconcile\(\);/);
  assert.match(read('frontend/scripts/desktop-canvas-model-nodes.js'), /list\.innerHTML = comfyWorkflowCardsHtml\(state\.workflow \|\| ''\);\n\s*comfyLayout\?\.sync\(list\);/);
});
